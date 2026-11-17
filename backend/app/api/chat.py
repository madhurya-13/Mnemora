"""Persistent Gemini chat and streaming endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session, sessionmaker

from app.agents.assistant import respond, stream_response
from app.config import settings
from app.database.db import get_db
from app.models.user import User
from app.memory.retriever import retrieve_context
from app.knowledge_graph.graph_workflow import process_pending_graph_sync
from app.memory.workflow import process_pending_jobs
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.chat import ChatHealthResponse, ChatRequest, ChatResponse
from app.services import chat_service
from app.services.conversation_service import ConversationNotFoundError
from app.services.llm_service import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMRequestError,
    LLMServiceError,
    LLMUnavailableError,
)
from app.services.session_service import get_current_user
from app.services.adaptive_memory.workflow import process_adaptive_jobs
from app.services.voice.preferences import get_preferences
from app.services.vision import (
    ImageProcessingError,
    ImageTooLargeError,
    ImageValidationError,
    UnsupportedImageFormatError,
    VisionServiceError,
    analyze_image,
    validate_image,
)
from app.services.voice import (
    AudioProcessingError,
    AudioTooLargeError,
    AudioValidationError,
    STTServiceError,
    UnsupportedAudioFormatError,
    transcribe_audio,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _memory_labels(blocks: list[str]) -> list[str]:
    """Surface only memory lines that retrieval actually placed in context."""
    labels: list[str] = []
    for block in blocks:
        if not block.startswith("RELEVANT USER CONTEXT:"):
            continue
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                label = stripped[2:].strip()
                if label:
                    labels.append(label[:240])
    return labels


async def _process_post_turn(factory: sessionmaker) -> None:
    """Run durable extraction and adaptive work without blocking the response."""
    try:
        await process_pending_jobs(factory)
    except Exception:
        logger.exception("Post-turn memory extraction failed.")
    try:
        await process_pending_graph_sync(factory)
    except Exception:
        logger.exception("Post-turn graph construction failed.")
    try:
        await process_adaptive_jobs(factory)
    except Exception:
        logger.exception("Post-turn adaptive processing failed.")


def _image_user_message(filename: str, user_text: str, visual_analysis: str) -> str:
    """Persist the question and an uncertain visual summary. Raw image bytes are not stored."""
    parts = [f"[Attached image: {filename}]"]
    if user_text.strip():
        parts.append(user_text.strip())
    summary = visual_analysis.strip() or "No visual description was produced."
    parts.append(
        "Uncertain visual interpretation (not a confirmed fact; do not infer personal details):\n" + summary
    )
    return "\n\n".join(parts)


@router.get("/health", response_model=ChatHealthResponse)
async def chat_health() -> ChatHealthResponse:
    """Report local AI configuration without making a provider request."""
    configured = bool(settings.google_api_key.strip())
    return ChatHealthResponse(
        status="ready" if configured else "not_configured",
        configured=configured,
        model=settings.gemini_model,
    )


def _raise_chat_error(error: Exception) -> None:
    if isinstance(error, LLMConfigurationError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    if isinstance(error, LLMAuthenticationError):
        raise HTTPException(status_code=502, detail="Google rejected the configured API key. Check backend/.env.") from error
    if isinstance(error, LLMRateLimitError):
        raise HTTPException(status_code=429, detail=str(error)) from error
    if isinstance(error, LLMUnavailableError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    if isinstance(error, LLMRequestError):
        raise HTTPException(status_code=502, detail=str(error)) from error
    if isinstance(error, LLMServiceError):
        raise HTTPException(status_code=502, detail="The AI service could not complete this request.") from error
    raise error


def _prepare(payload: ChatRequest, db: Session, user: User) -> chat_service.PreparedTurn:
    try:
        return chat_service.prepare_turn(
            db,
            user.user_id,
            payload.conversation_id,
            payload.message,
            regenerate=payload.regenerate,
        )
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="Conversation not found.") from error


def _mark_failed(factory: sessionmaker, user_id: UUID, conversation_id: UUID, user_message_id: UUID) -> None:
    try:
        with factory() as db:
            chat_service.fail_turn(db, user_id, conversation_id, user_message_id)
    except Exception:
        logger.exception("Could not persist a failed message status.")


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    prepared = _prepare(payload, db, user)
    try:
        memory_context = await retrieve_context(db, user.user_id, payload.message)
        if memory_context:
            result = await respond(str(prepared.conversation_id), payload.message, prepared.history, memory_context)
        else:
            result = await respond(str(prepared.conversation_id), payload.message, prepared.history)
        assistant = chat_service.complete_turn(
            db, user.user_id, prepared.conversation_id, prepared.user_message_id, result.response
        )
        background_tasks.add_task(
            _process_post_turn,
            sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False),
        )
        return ChatResponse(
            conversation_id=prepared.conversation_id,
            response=result.response,
            assistant_message_id=assistant.message_id,
            memories_used=_memory_labels(memory_context),
        )
    except Exception as error:
        try:
            chat_service.fail_turn(db, user.user_id, prepared.conversation_id, prepared.user_message_id)
        except Exception:
            logger.exception("Could not persist a failed message status.")
        if isinstance(error, LLMServiceError):
            _raise_chat_error(error)
        logger.exception("Persistent chat request failed.")
        raise HTTPException(status_code=500, detail="The server could not complete this request.") from error


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    prepared = _prepare(payload, db, user)
    user_id = user.user_id
    conversation_id = prepared.conversation_id
    user_message_id = prepared.user_message_id
    memory_context = await retrieve_context(db, user_id, payload.message)
    session_factory = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False)
    # Do not hold a database connection while the remote model streams.
    db.close()

    async def events() -> AsyncIterator[str]:
        yield _sse("conversation", {"conversation_id": str(conversation_id)})
        yield _sse("retrieval", {"memories": _memory_labels(memory_context)})
        parts: list[str] = []
        try:
            if memory_context:
                token_stream = stream_response(prepared.history, payload.message, memory_context)
            else:
                token_stream = stream_response(prepared.history, payload.message)
            async for token in token_stream:
                parts.append(token)
                yield _sse("token", {"text": token})
            response_text = "".join(parts).strip()
            if not response_text:
                raise LLMRequestError("The AI service returned an empty response. Please try again.")
            with session_factory() as session:
                assistant = chat_service.complete_turn(
                    session, user_id, conversation_id, user_message_id, response_text
                )
            yield _sse("done", {
                "conversation_id": str(conversation_id),
                "role": "assistant",
                "assistant_message_id": str(assistant.message_id),
            })
        except asyncio.CancelledError:
            _mark_failed(session_factory, user_id, conversation_id, user_message_id)
            raise
        except LLMServiceError as error:
            _mark_failed(session_factory, user_id, conversation_id, user_message_id)
            retryable = not isinstance(error, (LLMConfigurationError, LLMAuthenticationError))
            yield _sse("error", {"message": str(error), "retryable": retryable})
        except Exception:
            _mark_failed(session_factory, user_id, conversation_id, user_message_id)
            logger.exception("Persistent chat stream failed for conversation %s.", conversation_id)
            yield _sse("error", {"message": "The assistant could not complete this response. Please try again.", "retryable": True})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(_process_post_turn, session_factory),
    )


def _resolve_target_conversation_id(conversation_id: str) -> UUID | None:
    if conversation_id.strip().lower() in {"new", "none", ""}:
        return None
    try:
        return UUID(conversation_id.strip())
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid conversation ID format.") from error


@router.post("/{conversation_id}/message-with-image", response_model=ChatResponse)
async def chat_with_image(
    conversation_id: str,
    background_tasks: BackgroundTasks,
    message: str = Form(""),
    image: UploadFile = File(..., description="Image file attachment (JPEG, PNG, WebP, GIF)."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    """Send an image attachment and question to the conversation pipeline."""
    if not get_preferences(user.user_id)["image_input_enabled"]:
        raise HTTPException(status_code=503, detail="Image input is currently disabled.")
    target_id = _resolve_target_conversation_id(conversation_id)

    # 1. Verify conversation ownership upfront if an ID was provided
    if target_id is not None:
        conv = ConversationRepository(db).get(user.user_id, target_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

    # 2. Read and validate image bytes upfront
    try:
        image_bytes = await image.read()
        safe_name, detected_format, mime_type = validate_image(
            image_bytes,
            filename=image.filename,
            content_type=image.content_type,
        )
    except ImageValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnsupportedImageFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ImageTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    # 3. Analyze image with vision service
    try:
        visual_analysis = await analyze_image(
            image_bytes,
            prompt=message.strip() or "Describe what is in this image in detail.",
            filename=safe_name,
            content_type=mime_type,
        )
    except VisionServiceError as exc:
        raise HTTPException(status_code=502, detail=f"Visual analysis failed: {exc}") from exc
    except Exception as exc:
        logger.exception("Unexpected error processing image upload.")
        raise HTTPException(status_code=500, detail="The image could not be processed.") from exc

    user_text = message.strip()
    persisted_user_content = _image_user_message(safe_name, user_text, visual_analysis)

    try:
        prepared = chat_service.prepare_turn(
            db,
            user.user_id,
            target_id,
            persisted_user_content,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found.") from exc

    try:
        retrieval_query = f"{user_text} {visual_analysis}".strip()
        memory_context = await retrieve_context(db, user.user_id, retrieval_query)

        assistant_prompt = (
            f"The user attached an image ({safe_name}).\n"
            f"Visual Description of Image:\n{visual_analysis}\n\n"
            f"User Question/Prompt:\n{user_text or 'Explain what is shown in this image.'}"
        )

        if memory_context:
            result = await respond(str(prepared.conversation_id), assistant_prompt, prepared.history, memory_context)
        else:
            result = await respond(str(prepared.conversation_id), assistant_prompt, prepared.history)

        assistant = chat_service.complete_turn(
            db, user.user_id, prepared.conversation_id, prepared.user_message_id, result.response
        )
        background_tasks.add_task(
            _process_post_turn,
            sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False),
        )
        return ChatResponse(
            conversation_id=prepared.conversation_id,
            response=result.response,
            assistant_message_id=assistant.message_id,
            memories_used=_memory_labels(memory_context),
        )
    except Exception as error:
        try:
            chat_service.fail_turn(db, user.user_id, prepared.conversation_id, prepared.user_message_id)
        except Exception:
            logger.exception("Could not persist a failed message status.")
        if isinstance(error, LLMServiceError):
            _raise_chat_error(error)
        logger.exception("Chat with image request failed.")
        raise HTTPException(status_code=500, detail="The server could not complete this request.") from error


@router.post("/{conversation_id}/message-with-audio", response_model=ChatResponse)
async def chat_with_audio(
    conversation_id: str,
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(..., description="Audio file to transcribe and send to conversation."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    """Send voice audio recording to be transcribed and processed as a conversation turn."""
    if not get_preferences(user.user_id)["voice_enabled"]:
        raise HTTPException(status_code=503, detail="Voice input is currently disabled.")
    target_id = _resolve_target_conversation_id(conversation_id)

    # 1. Verify conversation ownership upfront if an ID was provided
    if target_id is not None:
        conv = ConversationRepository(db).get(user.user_id, target_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

    try:
        audio_bytes = await audio.read()
        transcribed_text = await transcribe_audio(
            audio_bytes,
            filename=audio.filename,
            content_type=audio.content_type,
        )
    except AudioValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnsupportedAudioFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AudioTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except STTServiceError as exc:
        raise HTTPException(status_code=502, detail=f"Speech transcription failed: {exc}") from exc
    except Exception as exc:
        logger.exception("Unexpected error transcribing audio input.")
        raise HTTPException(status_code=500, detail="The audio input could not be transcribed.") from exc

    clean_text = transcribed_text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="No speech could be recognized in the audio input.")

    try:
        prepared = chat_service.prepare_turn(
            db,
            user.user_id,
            target_id,
            clean_text,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found.") from exc

    try:
        memory_context = await retrieve_context(db, user.user_id, clean_text)
        if memory_context:
            result = await respond(str(prepared.conversation_id), clean_text, prepared.history, memory_context)
        else:
            result = await respond(str(prepared.conversation_id), clean_text, prepared.history)

        assistant = chat_service.complete_turn(
            db, user.user_id, prepared.conversation_id, prepared.user_message_id, result.response
        )
        background_tasks.add_task(
            _process_post_turn,
            sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False),
        )
        return ChatResponse(
            conversation_id=prepared.conversation_id,
            response=result.response,
            assistant_message_id=assistant.message_id,
            memories_used=_memory_labels(memory_context),
        )
    except Exception as error:
        try:
            chat_service.fail_turn(db, user.user_id, prepared.conversation_id, prepared.user_message_id)
        except Exception:
            logger.exception("Could not persist a failed message status.")
        if isinstance(error, LLMServiceError):
            _raise_chat_error(error)
        logger.exception("Chat with audio request failed.")
        raise HTTPException(status_code=500, detail="The server could not complete this request.") from error

"""Persistent Gemini chat and streaming endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session, sessionmaker

from app.agents.assistant import respond, stream_response
from app.config import settings
from app.database.db import get_db
from app.models.user import User
from app.memory.retriever import retrieve_context
from app.memory.workflow import process_pending_jobs
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
        chat_service.complete_turn(
            db, user.user_id, prepared.conversation_id, prepared.user_message_id, result.response
        )
        background_tasks.add_task(
            process_pending_jobs,
            sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False),
        )
        return ChatResponse(conversation_id=prepared.conversation_id, response=result.response)
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
                chat_service.complete_turn(
                    session, user_id, conversation_id, user_message_id, response_text
                )
            yield _sse("done", {"conversation_id": str(conversation_id), "role": "assistant"})
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
        background=BackgroundTask(process_pending_jobs, session_factory),
    )

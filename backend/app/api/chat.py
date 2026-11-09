"""Versioned chat, stream, and in-memory conversation management endpoints."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from app.agents.assistant import respond, stream_response
from app.config import settings
from app.schemas.chat import (
    ChatHealthResponse,
    ChatRequest,
    ChatResponse,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationRenameRequest,
    ConversationSummary,
)
from app.services.conversation_store import conversation_store
from app.services.llm_service import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMRequestError,
    LLMServiceError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _raise_chat_error(error: LLMServiceError) -> None:
    if isinstance(error, LLMConfigurationError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    if isinstance(error, LLMAuthenticationError):
        raise HTTPException(status_code=502, detail="Google rejected the configured API key. Check backend/.env.") from error
    if isinstance(error, LLMRateLimitError):
        raise HTTPException(status_code=429, detail=str(error)) from error
    if isinstance(error, LLMUnavailableError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    raise HTTPException(status_code=502, detail=str(error)) from error


def _require_conversation(conversation_id: str) -> ConversationDetail:
    conversation = conversation_store.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


@router.get("/health", response_model=ChatHealthResponse)
async def chat_health() -> ChatHealthResponse:
    """Report local configuration without making a billable model request."""
    configured = bool(settings.google_api_key.strip())
    return ChatHealthResponse(
        status="ready" if configured else "not_configured",
        configured=configured,
        model=settings.gemini_model,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations() -> list[ConversationSummary]:
    return conversation_store.list()


@router.post("/conversations", response_model=ConversationDetail, status_code=status.HTTP_201_CREATED)
async def create_conversation(payload: ConversationCreateRequest) -> ConversationDetail:
    return conversation_store.create(payload.title)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str) -> ConversationDetail:
    return _require_conversation(conversation_id)


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str,
    payload: ConversationRenameRequest,
) -> ConversationSummary:
    result = conversation_store.rename(conversation_id, payload.title)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return result


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str) -> Response:
    async with conversation_store.turn_lock(conversation_id):
        if not conversation_store.delete(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/conversations/{conversation_id}/messages", response_model=ConversationDetail)
async def clear_conversation(conversation_id: str) -> ConversationDetail:
    async with conversation_store.turn_lock(conversation_id):
        if not conversation_store.clear(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return _require_conversation(conversation_id)


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    conversation = conversation_store.create() if payload.conversation_id is None else _require_conversation(payload.conversation_id)
    conversation_id = conversation.conversation_id
    async with conversation_store.turn_lock(conversation_id):
        if payload.regenerate:
            conversation_store.remove_last_turn(conversation_id, payload.message)
        history = conversation_store.get_history(conversation_id) or []
        try:
            result = await respond(conversation_id, payload.message, history)
        except LLMServiceError as error:
            _raise_chat_error(error)
        conversation_store.append_turn(conversation_id, payload.message, result.response)
        return result


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    conversation = conversation_store.create() if payload.conversation_id is None else _require_conversation(payload.conversation_id)
    conversation_id = conversation.conversation_id

    async def events() -> AsyncIterator[str]:
        yield _sse("conversation", {"conversation_id": conversation_id})
        async with conversation_store.turn_lock(conversation_id):
            if payload.regenerate:
                conversation_store.remove_last_turn(conversation_id, payload.message)
            history = conversation_store.get_history(conversation_id) or []
            parts: list[str] = []
            try:
                async for token in stream_response(history, payload.message):
                    parts.append(token)
                    yield _sse("token", {"text": token})
                response_text = "".join(parts).strip()
                if not response_text:
                    raise LLMRequestError("The AI service returned an empty response. Please try again.")
                conversation_store.append_turn(conversation_id, payload.message, response_text)
                yield _sse("done", {"conversation_id": conversation_id, "role": "assistant"})
            except LLMServiceError as error:
                retryable = not isinstance(error, (LLMConfigurationError, LLMAuthenticationError))
                yield _sse("error", {"message": str(error), "retryable": retryable})
            except Exception:
                logger.exception("Unexpected chat streaming error for conversation %s.", conversation_id)
                yield _sse("error", {"message": "The assistant could not complete this response. Please try again.", "retryable": True})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

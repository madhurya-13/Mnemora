"""Conversation-aware assistant orchestration, independent of storage details."""

from collections.abc import AsyncIterator

from app.config import settings
from app.schemas.chat import ChatMessage, ChatResponse
from app.services import llm_service
from app.utils.prompts import SYSTEM_PROMPT


def build_model_messages(history: list[ChatMessage], message: str) -> list[tuple[str, str]]:
    """Build a bounded, role-tagged Gemini message list with system prompt first."""
    context_limit = max(0, settings.chat_max_history_messages)
    recent_history = history[-context_limit:] if context_limit else []
    prompt = settings.assistant_system_prompt.strip() or SYSTEM_PROMPT
    messages = [("system", prompt)]
    messages.extend((item.role, item.content) for item in recent_history)
    messages.append(("human", message))
    return messages


async def respond(
    conversation_id: str,
    message: str,
    history: list[ChatMessage],
) -> ChatResponse:
    content = await llm_service.generate(build_model_messages(history, message))
    return ChatResponse(conversation_id=conversation_id, response=content)


async def stream_response(history: list[ChatMessage], message: str) -> AsyncIterator[str]:
    async for chunk in llm_service.stream(build_model_messages(history, message)):
        yield chunk

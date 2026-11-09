"""Gemini API client and safe async chat/stream operations."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from functools import lru_cache
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)
ChatInput = Sequence[tuple[str, str]]


class LLMServiceError(RuntimeError):
    """Base class for safe, user-facing model service failures."""


class LLMConfigurationError(LLMServiceError):
    pass


class LLMAuthenticationError(LLMServiceError):
    pass


class LLMRateLimitError(LLMServiceError):
    pass


class LLMUnavailableError(LLMServiceError):
    pass


class LLMRequestError(LLMServiceError):
    pass


@lru_cache(maxsize=2)
def get_genai_client():
    """Lazily build the Google GenAI client; construction does not make a request."""
    api_key = settings.google_api_key.strip()
    if not api_key:
        raise LLMConfigurationError("The assistant is not configured. Add GOOGLE_API_KEY to backend/.env.")
    try:
        from google import genai
        from google.genai import types
    except ImportError as error:
        logger.error("Google GenAI SDK is not installed.")
        raise LLMConfigurationError("The Gemini integration is unavailable. Install backend requirements.") from error
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=settings.gemini_timeout_seconds * 1000),
    )


def _request_parts(messages: ChatInput) -> tuple[str, list[dict[str, Any]]]:
    system_instruction = ""
    contents: list[dict[str, Any]] = []
    for role, text in messages:
        if role == "system":
            system_instruction = text
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": text}],
        })
    return system_instruction, contents


def _generation_config(system_instruction: str) -> Any:
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_tokens,
    )


def _map_gemini_error(error: Exception) -> LLMServiceError:
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None

    if code in {401, 403}:
        return LLMAuthenticationError("Google rejected the configured API key.")
    if code == 429:
        return LLMRateLimitError("Gemini's free-tier quota or rate limit was reached. Try again later or check Google AI Studio usage limits.")
    if code in {408, 500, 502, 503, 504} or isinstance(error, (TimeoutError, ConnectionError)):
        return LLMUnavailableError("The Gemini service could not be reached. Check the connection and try again.")
    if code is not None or type(error).__name__ in {"APIError", "ClientError", "ServerError"}:
        return LLMRequestError("Gemini could not process this request. Check the model and request settings.")
    return LLMRequestError("The assistant could not complete this request.")


async def generate(messages: ChatInput) -> str:
    """Generate one response with the official asynchronous Google GenAI SDK."""
    try:
        system_instruction, contents = _request_parts(messages)
        response = await get_genai_client().aio.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=_generation_config(system_instruction),
        )
        text = (response.text or "").strip()
        if not text:
            raise LLMRequestError("The AI service returned an empty response. Please try again.")
        return text
    except LLMServiceError:
        raise
    except Exception as error:
        logger.error("Gemini response generation failed (%s).", type(error).__name__)
        raise _map_gemini_error(error) from error


async def stream(messages: ChatInput) -> AsyncIterator[str]:
    """Yield text chunks from Google's asynchronous content stream."""
    try:
        system_instruction, contents = _request_parts(messages)
        chunks = await get_genai_client().aio.models.generate_content_stream(
            model=settings.gemini_model,
            contents=contents,
            config=_generation_config(system_instruction),
        )
        async for chunk in chunks:
            text = chunk.text or ""
            if text:
                yield text
    except LLMServiceError:
        raise
    except Exception as error:
        logger.error("Gemini streaming failed (%s).", type(error).__name__)
        raise _map_gemini_error(error) from error

"""Speech-to-text service with OpenAI Whisper and Google Gemini support."""

from __future__ import annotations

import logging
import re
import time

from app.config import settings
from app.services.voice.audio_processor import (
    temporary_audio_file,
    validate_audio,
)

logger = logging.getLogger(__name__)

_OPENAI_COOLDOWN_SECONDS = 120
_openai_unavailable_until = 0.0

_GEMINI_MIME_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}

_TRANSCRIPTION_PROMPT = (
    "Transcribe the speech in this audio verbatim. Return only the spoken words, with no "
    "commentary, labels, timestamps, or quotation marks. Preserve the speaker's wording and "
    "language. If the audio contains no intelligible speech, return an empty response."
)


class STTServiceError(Exception):
    """Base error for speech-to-text service failures."""


class STTConfigurationError(STTServiceError):
    """Raised when STT is not configured."""


class STTAuthenticationError(STTServiceError):
    """Raised when API credentials are rejected."""


class STTRateLimitError(STTServiceError):
    """Raised when rate limits are exceeded."""


class STTUnavailableError(STTServiceError):
    """Raised when speech-to-text service is unreachable."""


def _get_openai_client():
    """Return an OpenAI client, or None when no key is configured or the SDK is missing."""
    api_key = settings.openai_api_key.strip()
    if not api_key or time.monotonic() < _openai_unavailable_until:
        return None
    try:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key)
    except ImportError:
        logger.warning("The openai package is not installed; skipping OpenAI speech-to-text.")
        return None


def _mark_openai_unavailable() -> None:
    """Skip OpenAI briefly after a quota or authentication failure so Gemini responds promptly."""
    global _openai_unavailable_until
    _openai_unavailable_until = time.monotonic() + _OPENAI_COOLDOWN_SECONDS


def _get_gemini_client():
    """Return a Gemini client, or None when no Google key is configured or the SDK is missing."""
    api_key = settings.google_api_key.strip()
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=settings.gemini_timeout_seconds * 1000),
        )
    except ImportError:
        logger.warning("The google-genai package is not installed; skipping Gemini speech-to-text.")
        return None


def _map_openai_error(error: Exception) -> STTServiceError:
    status_code = getattr(error, "status_code", None)
    try:
        status_code = int(status_code)
    except (TypeError, ValueError):
        status_code = None

    error_body = getattr(error, "body", None)
    error_text = " ".join(
        str(value).lower()
        for value in (
            error,
            error_body,
            getattr(error_body, "get", lambda *_: "")("code") if isinstance(error_body, dict) else "",
        )
    )

    if status_code in {401, 403}:
        return STTAuthenticationError("OpenAI rejected the configured API key.")
    if status_code == 429:
        if "insufficient_quota" in error_text or "quota" in error_text or "credit" in error_text or "billing" in error_text:
            return STTRateLimitError(
                "OpenAI speech-to-text has no remaining quota or credits. "
                "Add billing to the OpenAI project, or configure GOOGLE_API_KEY for the Gemini fallback."
            )
        return STTRateLimitError(
            "OpenAI temporarily rate-limited speech-to-text. Wait briefly and try again."
        )
    if status_code in {408, 500, 502, 503, 504} or isinstance(error, (TimeoutError, ConnectionError)):
        return STTUnavailableError("The speech-to-text service could not be reached. Check connection and retry.")
    return STTServiceError(f"Speech transcription failed: {type(error).__name__}")


def _map_gemini_error(error: Exception) -> STTServiceError:
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None

    if code in {401, 403}:
        return STTAuthenticationError("Google rejected the configured API key.")
    if code == 429:
        return STTRateLimitError(
            "Gemini's free-tier quota or rate limit was reached for transcription. Try again later."
        )
    if code in {408, 500, 502, 503, 504} or isinstance(error, (TimeoutError, ConnectionError)):
        return STTUnavailableError("The Gemini transcription service could not be reached. Check connection and retry.")
    return STTServiceError(f"Speech transcription failed with Gemini: {type(error).__name__}")


def _clean_transcript(text: str) -> str:
    """Remove wrapper quotes or labels that some models add despite the instruction."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^(?:here is|this is)\s+(?:the\s+)?transcription\s*[:\-]\s*", "", cleaned, flags=re.IGNORECASE)
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'", "“", "”"}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


async def _transcribe_with_openai(
    data: bytes,
    safe_name: str,
    detected_format: str,
    language: str | None,
) -> str:
    client = _get_openai_client()
    if client is None:
        raise STTConfigurationError("OpenAI speech-to-text is not configured.")

    model = settings.openai_stt_model or "whisper-1"
    with temporary_audio_file(data, suffix=f".{detected_format}") as temp_path:
        with open(temp_path, "rb") as audio_file:
            kwargs: dict[str, object] = {"model": model, "file": audio_file}
            if language:
                kwargs["language"] = language
            response = await client.audio.transcriptions.create(**kwargs)

    text = _clean_transcript(getattr(response, "text", "") or "")
    if not text:
        logger.info("Whisper returned an empty transcription for %s", safe_name)
    return text


async def _transcribe_with_gemini(
    data: bytes,
    detected_format: str,
    language: str | None,
) -> str:
    client = _get_gemini_client()
    if client is None:
        raise STTConfigurationError(
            "No speech-to-text provider is configured. Add OPENAI_API_KEY or GOOGLE_API_KEY to backend/.env."
        )

    from google.genai import types

    prompt = _TRANSCRIPTION_PROMPT
    if language:
        prompt += f" The speech is in {language}."
    mime_type = _GEMINI_MIME_TYPES.get(detected_format, "audio/webm")
    model = settings.gemini_stt_model or "gemini-3.5-flash-lite"

    response = await client.aio.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=data, mime_type=mime_type),
            prompt,
        ],
    )
    return _clean_transcript(getattr(response, "text", "") or "")


async def transcribe_audio(
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
    language: str | None = None,
) -> str:
    """Transcribe raw audio bytes into text using OpenAI Whisper, then Gemini as a fallback."""
    if not settings.voice_enabled:
        raise STTConfigurationError("Voice input is currently disabled in system settings.")

    safe_name, detected_format = validate_audio(data, filename, content_type)

    openai_client = _get_openai_client()
    if openai_client is not None:
        try:
            return await _transcribe_with_openai(data, safe_name, detected_format, language)
        except Exception as exc:
            mapped_error = _map_openai_error(exc)
            if isinstance(mapped_error, (STTRateLimitError, STTAuthenticationError)):
                _mark_openai_unavailable()
            gemini_client = _get_gemini_client()
            if gemini_client is None:
                logger.error("OpenAI speech-to-text failed (%s).", type(exc).__name__)
                raise mapped_error from exc
            logger.warning(
                "OpenAI speech-to-text failed (%s); retrying with Gemini.",
                type(exc).__name__,
            )

    try:
        return await _transcribe_with_gemini(data, detected_format, language)
    except (STTServiceError, STTConfigurationError):
        raise
    except Exception as exc:
        logger.error("Gemini speech-to-text failed: %s", type(exc).__name__)
        raise _map_gemini_error(exc) from exc

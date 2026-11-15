"""Vision understanding service for analyzing uploaded images."""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.vision.image_processor import (
    ImageProcessingError,
    ImageTooLargeError,
    ImageValidationError,
    UnsupportedImageFormatError,
    to_base64_data_url,
    validate_image,
)

logger = logging.getLogger(__name__)


class VisionServiceError(Exception):
    """Base error for vision service failures."""


class VisionConfigurationError(VisionServiceError):
    """Raised when vision models are not configured."""


class VisionAuthenticationError(VisionServiceError):
    """Raised when API credentials for vision model are rejected."""


class VisionRateLimitError(VisionServiceError):
    """Raised when vision model rate limits are hit."""


class VisionUnavailableError(VisionServiceError):
    """Raised when vision model is unreachable."""


def _get_openai_client():
    api_key = settings.openai_api_key.strip()
    if not api_key:
        return None
    try:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key)
    except ImportError:
        return None


def _get_gemini_client():
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
        return None


def _map_openai_error(error: Exception) -> VisionServiceError:
    status_code = getattr(error, "status_code", None)
    try:
        status_code = int(status_code)
    except (TypeError, ValueError):
        status_code = None

    if status_code in {401, 403}:
        return VisionAuthenticationError("API key rejected by the vision model provider.")
    if status_code == 429:
        return VisionRateLimitError("Vision model rate limit reached. Please try again later.")
    if status_code in {408, 500, 502, 503, 504} or isinstance(error, (TimeoutError, ConnectionError)):
        return VisionUnavailableError("The vision service could not be reached. Check connection and retry.")
    return VisionServiceError(f"Image analysis failed: {type(error).__name__}")


async def analyze_image(
    image_data: bytes,
    prompt: str = "Describe what is shown in this image in detail.",
    filename: str | None = None,
    content_type: str | None = None,
) -> str:
    """Analyze an image using the vision model and return detailed visual description and insights."""
    if not settings.image_input_enabled:
        raise VisionConfigurationError("Image input is currently disabled in system settings.")

    safe_name, detected_format, mime_type = validate_image(image_data, filename, content_type)
    openai_client = _get_openai_client()

    system_guidance = (
        "You are MNEMORA's visual perception engine. Describe and analyze images accurately, "
        "extracting text/OCR, diagram components, architectures, UI elements, and error messages. "
        "Do not invent facts not visible in the image. Express appropriate uncertainty for ambiguous elements. "
        "Do not make sensitive personal inferences about people in the image."
    )

    # 1. Try OpenAI vision if configured
    if openai_client:
        model = settings.openai_vision_model or "gpt-4o-mini"
        data_url = to_base64_data_url(image_data, mime_type)
        try:
            response = await openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_guidance},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt or "Describe what is in this image."},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                max_tokens=1500,
            )
            content = response.choices[0].message.content or ""
            return content.strip()
        except Exception as exc:
            logger.warning("OpenAI vision call failed (%s), checking Gemini fallback.", type(exc).__name__)
            if not _get_gemini_client():
                raise _map_openai_error(exc) from exc

    # 2. Try Gemini fallback if available
    gemini_client = _get_gemini_client()
    if gemini_client:
        try:
            from google.genai import types

            response = await gemini_client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=[
                    types.Part.from_bytes(data=image_data, mime_type=mime_type),
                    f"{system_guidance}\n\nUser Question: {prompt or 'Describe this image in detail.'}",
                ],
            )
            text = (getattr(response, "text", "") or "").strip()
            return text
        except Exception as exc:
            logger.error("Gemini vision analysis failed: %s", type(exc).__name__)
            raise VisionServiceError(f"Image analysis failed with Gemini: {type(exc).__name__}") from exc

    raise VisionConfigurationError(
        "No vision provider configured. Set OPENAI_API_KEY or GOOGLE_API_KEY in backend/.env."
    )

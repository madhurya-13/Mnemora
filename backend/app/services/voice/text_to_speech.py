"""Text-to-speech service with OpenAI and Google Gemini support."""

from __future__ import annotations

import io
import logging
import re
import time
import wave
from dataclasses import dataclass
from typing import Literal

from app.config import settings

logger = logging.getLogger(__name__)

_OPENAI_COOLDOWN_SECONDS = 120
_openai_unavailable_until = 0.0

SUPPORTED_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
TTSVoice = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
MAX_CHUNK_CHARS = 3800

# Map the voice ids exposed by the API onto Gemini's prebuilt voices so the
# browser picker behaves consistently no matter which provider is active.
_GEMINI_VOICE_MAP = {
    "alloy": "Puck",
    "echo": "Charon",
    "fable": "Orus",
    "onyx": "Fenrir",
    "nova": "Kore",
    "shimmer": "Aoede",
}
_GEMINI_VOICES = ("Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr")
_DEFAULT_SAMPLE_RATE = 24000


@dataclass(frozen=True)
class SpeechAudio:
    """Synthesized speech plus the metadata needed to serve it correctly."""

    data: bytes
    media_type: str
    extension: str


class TTSServiceError(Exception):
    """Base error for text-to-speech service failures."""


class TTSConfigurationError(TTSServiceError):
    """Raised when TTS is not configured."""


class TTSAuthenticationError(TTSServiceError):
    """Raised when API credentials are rejected."""


class TTSRateLimitError(TTSServiceError):
    """Raised when rate limits are exceeded."""


class TTSUnavailableError(TTSServiceError):
    """Raised when TTS service is unreachable."""


class TTSValidationError(TTSServiceError):
    """Raised when input text or parameters are invalid."""


def _get_openai_client():
    """Return an OpenAI client, or None when no key is configured or the SDK is missing."""
    api_key = settings.openai_api_key.strip()
    if not api_key or time.monotonic() < _openai_unavailable_until:
        return None
    try:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key)
    except ImportError:
        logger.warning("The openai package is not installed; skipping OpenAI text-to-speech.")
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
        logger.warning("The google-genai package is not installed; skipping Gemini text-to-speech.")
        return None


def _map_openai_error(error: Exception) -> TTSServiceError:
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
        return TTSAuthenticationError("OpenAI rejected the configured API key.")
    if status_code == 429:
        if "quota" in error_text or "credit" in error_text or "billing" in error_text:
            return TTSRateLimitError(
                "OpenAI text-to-speech has no remaining quota or credits. "
                "Add billing to the OpenAI project, or configure GOOGLE_API_KEY for the Gemini fallback."
            )
        return TTSRateLimitError("OpenAI rate limit reached for text-to-speech. Please try again later.")
    if status_code in {408, 500, 502, 503, 504} or isinstance(error, (TimeoutError, ConnectionError)):
        return TTSUnavailableError("The text-to-speech service could not be reached. Check connection and retry.")
    return TTSServiceError(f"Speech synthesis failed: {type(error).__name__}")


def _map_gemini_error(error: Exception) -> TTSServiceError:
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None

    if code in {401, 403}:
        return TTSAuthenticationError("Google rejected the configured API key.")
    if code == 429:
        return TTSRateLimitError(
            "Gemini's free-tier quota or rate limit was reached for speech. Try again later."
        )
    if code in {408, 500, 502, 503, 504} or isinstance(error, (TimeoutError, ConnectionError)):
        return TTSUnavailableError("The Gemini speech service could not be reached. Check connection and retry.")
    return TTSServiceError(f"Speech synthesis failed with Gemini: {type(error).__name__}")


def split_text_into_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split long text into sentence-bounded chunks that respect TTS character limits."""
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    # Split by paragraphs or sentence ends
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for sentence in sentences:
        if not sentence:
            continue
        sentence_len = len(sentence) + 1
        if sentence_len > max_chars:
            # Hard break if single sentence exceeds max_chars
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_len = 0
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i : i + max_chars])
        elif current_len + sentence_len > max_chars:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_len = sentence_len
        else:
            current_chunk.append(sentence)
            current_len += sentence_len

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def _gemini_voice_name(selected_voice: str) -> str:
    mapped = _GEMINI_VOICE_MAP.get(selected_voice)
    if mapped:
        return mapped
    if selected_voice.capitalize() in _GEMINI_VOICES:
        return selected_voice.capitalize()
    return settings.gemini_tts_voice or "Kore"


def _audio_descriptor(data: bytes) -> tuple[str, str]:
    """Return (media_type, extension) for supported synthesized audio containers."""
    if data[:4] == b"RIFF":
        return "audio/wav", "wav"
    if data[:4] == b"OggS":
        return "audio/ogg", "ogg"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "audio/mpeg", "mp3"
    return "audio/wav", "wav"


def _sample_rate_from_mime(mime_type: str) -> int:
    match = re.search(r"rate=(\d+)", mime_type or "", re.IGNORECASE)
    return int(match.group(1)) if match else _DEFAULT_SAMPLE_RATE


def _pcm_to_wav(pcm: bytes, sample_rate: int = _DEFAULT_SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container for browser playback."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


def _normalise_gemini_audio(data: bytes, mime_type: str) -> bytes:
    """Gemini may return WAV, MP3, Ogg, or raw PCM depending on the model."""
    if data[:4] in {b"RIFF", b"OggS"} or data[:3] == b"ID3":
        return data
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return data
    lowered = (mime_type or "").lower()
    if "pcm" in lowered or "l16" in lowered or "wav" in lowered or "audio/raw" in lowered:
        return _pcm_to_wav(data, _sample_rate_from_mime(mime_type))
    # Unknown container: wrap as PCM so the browser still has a chance to play it.
    return _pcm_to_wav(data)


def _merge_wav_chunks(chunks: list[bytes]) -> bytes:
    """Join multiple WAV files into one playable WAV file."""
    if len(chunks) == 1:
        return chunks[0]

    frames: list[bytes] = []
    channels = 1
    sample_width = 2
    frame_rate = _DEFAULT_SAMPLE_RATE
    with wave.open(io.BytesIO(chunks[0]), "rb") as first:
        channels = first.getnchannels()
        sample_width = first.getsampwidth()
        frame_rate = first.getframerate()
        frames.append(first.readframes(first.getnframes()))

    for chunk in chunks[1:]:
        try:
            with wave.open(io.BytesIO(chunk), "rb") as wav_file:
                if (
                    wav_file.getnchannels() != channels
                    or wav_file.getsampwidth() != sample_width
                    or wav_file.getframerate() != frame_rate
                ):
                    # Skip incompatible chunks rather than producing corrupt audio.
                    continue
                frames.append(wav_file.readframes(wav_file.getnframes()))
        except (wave.Error, EOFError):
            continue

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as merged:
        merged.setnchannels(channels)
        merged.setsampwidth(sample_width)
        merged.setframerate(frame_rate)
        merged.writeframes(b"".join(frames))
    return buffer.getvalue()


async def _synthesize_with_openai(
    chunks: list[str],
    voice: str,
    response_format: str,
) -> bytes:
    client = _get_openai_client()
    if client is None:
        raise TTSConfigurationError("OpenAI text-to-speech is not configured.")

    model = settings.openai_tts_model or "tts-1"
    output_buffer = io.BytesIO()
    for chunk in chunks:
        response = await client.audio.speech.create(
            model=model,
            voice=voice,
            input=chunk,
            response_format=response_format,
        )
        # Response is HttpxBinaryResponseContent in the OpenAI SDK; `.content` holds the bytes.
        output_buffer.write(response.content)
    return output_buffer.getvalue()


async def _synthesize_with_gemini(chunks: list[str], voice: str) -> bytes:
    client = _get_gemini_client()
    if client is None:
        raise TTSConfigurationError(
            "No text-to-speech provider is configured. Add OPENAI_API_KEY or GOOGLE_API_KEY to backend/.env."
        )

    from google.genai import types

    model = settings.gemini_tts_model or "gemini-3.8-flash-tts"
    voice_name = _gemini_voice_name(voice)
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
    )

    audio_chunks: list[bytes] = []
    for chunk in chunks:
        response = await client.aio.models.generate_content(
            model=model,
            contents=chunk,
            config=config,
        )
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                if inline is None or not getattr(inline, "data", None):
                    continue
                audio_chunks.append(
                    _normalise_gemini_audio(inline.data, getattr(inline, "mime_type", "") or "")
                )

    if not audio_chunks:
        raise TTSServiceError("Gemini returned no audio for the supplied text.")

    if all(chunk[:4] == b"RIFF" for chunk in audio_chunks):
        return _merge_wav_chunks(audio_chunks)
    return b"".join(audio_chunks)


async def synthesize_speech(
    text: str,
    voice: str | None = None,
    response_format: str = "mp3",
) -> SpeechAudio:
    """Convert text into spoken audio, preferring OpenAI and falling back to Gemini."""
    if not settings.tts_enabled:
        raise TTSConfigurationError("Text-to-speech is currently disabled in system settings.")

    text_to_speak = text.strip()
    if not text_to_speak:
        raise TTSValidationError("Cannot generate speech for empty text.")

    selected_voice = (voice or settings.openai_tts_voice or "alloy").strip().lower()
    if selected_voice not in SUPPORTED_VOICES:
        raise TTSValidationError(
            f"Unsupported voice '{selected_voice}'. Choose one of: {', '.join(SUPPORTED_VOICES)}."
        )

    chunks = split_text_into_chunks(text_to_speak)
    if not chunks:
        raise TTSValidationError("No speakable text found.")

    openai_client = _get_openai_client()
    if openai_client is not None:
        try:
            audio_bytes = await _synthesize_with_openai(chunks, selected_voice, response_format)
            return SpeechAudio(audio_bytes, "audio/mpeg", "mp3")
        except Exception as exc:
            mapped_error = _map_openai_error(exc)
            if isinstance(mapped_error, (TTSRateLimitError, TTSAuthenticationError)):
                _mark_openai_unavailable()
            if _get_gemini_client() is None:
                logger.error("OpenAI text-to-speech failed (%s).", type(exc).__name__)
                raise mapped_error from exc
            logger.warning(
                "OpenAI text-to-speech failed (%s); retrying with Gemini.",
                type(exc).__name__,
            )

    try:
        audio_bytes = await _synthesize_with_gemini(chunks, selected_voice)
    except (TTSServiceError, TTSConfigurationError):
        raise
    except Exception as exc:
        logger.error("Gemini text-to-speech failed: %s", type(exc).__name__)
        raise _map_gemini_error(exc) from exc

    media_type, extension = _audio_descriptor(audio_bytes)
    return SpeechAudio(audio_bytes, media_type, extension)

"""Voice processing API endpoints: Speech-to-Text, Text-to-Speech, and Settings."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.config import settings
from app.models.user import User
from app.schemas.voice import (
    TTSRequest,
    TranscriptionResponse,
    VoiceSettingsResponse,
    VoiceSettingsUpdate,
)
from app.services.session_service import get_current_user
from app.services.voice.preferences import get_preferences, update_preferences
from app.services.voice.audio_processor import (
    AudioProcessingError,
    AudioTooLargeError,
    AudioValidationError,
    UnsupportedAudioFormatError,
)
from app.services.voice.speech_to_text import (
    STTAuthenticationError,
    STTConfigurationError,
    STTRateLimitError,
    STTServiceError,
    STTUnavailableError,
    transcribe_audio,
)
from app.services.voice.text_to_speech import (
    SUPPORTED_VOICES,
    TTSAuthenticationError,
    TTSConfigurationError,
    TTSRateLimitError,
    TTSServiceError,
    TTSUnavailableError,
    TTSValidationError,
    synthesize_speech,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


def _settings_payload(user: User) -> VoiceSettingsResponse:
    prefs = get_preferences(user.user_id)
    openai_configured = bool(settings.openai_api_key.strip())
    google_configured = bool(settings.google_api_key.strip())
    stt_provider = "openai" if openai_configured else ("gemini" if google_configured else "none")
    tts_provider = "openai" if openai_configured else ("gemini" if google_configured else "none")
    return VoiceSettingsResponse(
        voice_enabled=bool(prefs["voice_enabled"]),
        tts_enabled=bool(prefs["tts_enabled"]),
        image_input_enabled=bool(prefs["image_input_enabled"]),
        default_voice=str(prefs["default_voice"]),
        available_voices=list(SUPPORTED_VOICES),
        stt_provider=stt_provider,
        tts_provider=tts_provider,
        openai_stt_model=settings.openai_stt_model,
        openai_tts_model=settings.openai_tts_model,
        openai_vision_model=settings.openai_vision_model,
        gemini_stt_model=settings.gemini_stt_model,
        gemini_tts_model=settings.gemini_tts_model,
        gemini_tts_voice=settings.gemini_tts_voice,
        max_audio_upload_mb=settings.max_audio_upload_mb,
        max_image_upload_mb=settings.max_image_upload_mb,
    )


def _handle_voice_error(error: Exception) -> None:
    if isinstance(error, AudioValidationError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    if isinstance(error, UnsupportedAudioFormatError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    if isinstance(error, AudioTooLargeError):
        raise HTTPException(status_code=413, detail=str(error)) from error
    if isinstance(error, TTSValidationError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    if isinstance(error, (STTAuthenticationError, TTSAuthenticationError)):
        raise HTTPException(status_code=502, detail=str(error)) from error
    if isinstance(error, (STTRateLimitError, TTSRateLimitError)):
        raise HTTPException(status_code=429, detail=str(error)) from error
    if isinstance(error, (STTUnavailableError, TTSUnavailableError)):
        raise HTTPException(status_code=503, detail=str(error)) from error
    if isinstance(error, (STTConfigurationError, TTSConfigurationError)):
        raise HTTPException(status_code=503, detail=str(error)) from error
    if isinstance(error, (STTServiceError, TTSServiceError, AudioProcessingError)):
        raise HTTPException(status_code=502, detail=str(error)) from error
    logger.exception("Unexpected voice processing error: %s", type(error).__name__)
    raise HTTPException(status_code=500, detail="Voice processing encountered an internal error.") from error


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio_endpoint(
    audio: UploadFile = File(..., description="Audio file to transcribe (mic recording or file)."),
    user: User = Depends(get_current_user),
) -> TranscriptionResponse:
    """Transcribe real-time microphone recording or uploaded audio snippet."""
    if not get_preferences(user.user_id)["voice_enabled"]:
        raise HTTPException(status_code=503, detail="Voice input is currently disabled.")
    try:
        content = await audio.read()
        text = await transcribe_audio(
            content,
            filename=audio.filename,
            content_type=audio.content_type,
        )
        return TranscriptionResponse(
            text=text,
            filename=audio.filename,
            detected_format=audio.filename.split(".")[-1] if audio.filename and "." in audio.filename else "audio",
        )
    except Exception as exc:
        _handle_voice_error(exc)


@router.post("/transcribe-upload", response_model=TranscriptionResponse)
async def transcribe_upload_endpoint(
    file: UploadFile = File(..., description="Audio file upload (MP3, WAV, M4A, WebM, OGG, FLAC)."),
    user: User = Depends(get_current_user),
) -> TranscriptionResponse:
    """Transcribe uploaded audio file from disk or drag-and-drop."""
    if not get_preferences(user.user_id)["voice_enabled"]:
        raise HTTPException(status_code=503, detail="Voice input is currently disabled.")
    try:
        content = await file.read()
        text = await transcribe_audio(
            content,
            filename=file.filename,
            content_type=file.content_type,
        )
        return TranscriptionResponse(
            text=text,
            filename=file.filename,
            detected_format=file.filename.split(".")[-1] if file.filename and "." in file.filename else "audio",
        )
    except Exception as exc:
        _handle_voice_error(exc)


@router.post("/speak")
async def speak_text_endpoint(
    payload: TTSRequest,
    user: User = Depends(get_current_user),
) -> Response:
    """Convert assistant text into browser-compatible MP3 speech audio."""
    prefs = get_preferences(user.user_id)
    if not prefs["tts_enabled"]:
        raise HTTPException(status_code=503, detail="Text-to-speech is currently disabled.")
    try:
        speech = await synthesize_speech(
            text=payload.text,
            voice=payload.voice or str(prefs["default_voice"]),
        )
        return Response(
            content=speech.data,
            media_type=speech.media_type,
            headers={
                "Content-Disposition": f"inline; filename=speech.{speech.extension}",
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
            },
        )
    except Exception as exc:
        _handle_voice_error(exc)


@router.get("/settings", response_model=VoiceSettingsResponse)
async def get_voice_settings(
    user: User = Depends(get_current_user),
) -> VoiceSettingsResponse:
    """Retrieve voice, audio, and vision settings for the current guest."""
    return _settings_payload(user)


@router.put("/settings", response_model=VoiceSettingsResponse)
async def update_voice_settings(
    update: VoiceSettingsUpdate,
    user: User = Depends(get_current_user),
) -> VoiceSettingsResponse:
    """Update this guest's voice preferences. Environment feature flags are not changed."""
    try:
        update_preferences(user.user_id, update.model_dump(exclude_unset=True))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _settings_payload(user)

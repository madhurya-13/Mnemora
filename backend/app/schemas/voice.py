"""Schemas for voice, audio transcription, text-to-speech, and settings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptionResponse(BaseModel):
    text: str = Field(description="Transcribed text from audio input.")
    filename: str | None = Field(default=None, description="Sanitized original filename.")
    detected_format: str | None = Field(default=None, description="Detected audio container or codec.")


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="Text to convert into speech.")
    voice: str | None = Field(default="alloy", description="OpenAI TTS voice name.")


class VoiceSettingsResponse(BaseModel):
    voice_enabled: bool
    tts_enabled: bool
    image_input_enabled: bool
    default_voice: str
    available_voices: list[str]
    stt_provider: str = "none"
    tts_provider: str = "none"
    openai_stt_model: str
    openai_tts_model: str
    openai_vision_model: str
    gemini_stt_model: str = ""
    gemini_tts_model: str = ""
    gemini_tts_voice: str = ""
    max_audio_upload_mb: int
    max_image_upload_mb: int


class VoiceSettingsUpdate(BaseModel):
    voice_enabled: bool | None = None
    tts_enabled: bool | None = None
    image_input_enabled: bool | None = None
    default_voice: str | None = None

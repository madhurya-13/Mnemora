"""Per-guest voice preferences. Server feature flags stay in the environment."""

from __future__ import annotations

from uuid import UUID

from app.config import settings
from app.services.voice.text_to_speech import SUPPORTED_VOICES

_preferences: dict[UUID, dict[str, object]] = {}


def get_preferences(user_id: UUID) -> dict[str, object]:
    """Return effective voice settings for one guest.

    Environment flags that disable a capability always win. A guest cannot
    turn a disabled server feature back on, and cannot change another guest's voice.
    """
    stored = _preferences.get(user_id, {})
    voice = str(stored.get("default_voice") or settings.openai_tts_voice or "alloy").lower()
    if voice not in SUPPORTED_VOICES:
        voice = "alloy"
    return {
        "voice_enabled": bool(settings.voice_enabled and stored.get("voice_enabled", True)),
        "tts_enabled": bool(settings.tts_enabled and stored.get("tts_enabled", True)),
        "image_input_enabled": bool(settings.image_input_enabled and stored.get("image_input_enabled", True)),
        "default_voice": voice,
    }


def update_preferences(user_id: UUID, update: dict[str, object]) -> dict[str, object]:
    """Store optional guest preferences without mutating process-wide settings."""
    current = dict(_preferences.get(user_id, {}))
    if "voice_enabled" in update and update["voice_enabled"] is not None:
        current["voice_enabled"] = bool(update["voice_enabled"])
    if "tts_enabled" in update and update["tts_enabled"] is not None:
        current["tts_enabled"] = bool(update["tts_enabled"])
    if "image_input_enabled" in update and update["image_input_enabled"] is not None:
        current["image_input_enabled"] = bool(update["image_input_enabled"])
    if "default_voice" in update and update["default_voice"] is not None:
        voice = str(update["default_voice"]).strip().lower()
        if voice not in SUPPORTED_VOICES:
            raise ValueError(
                f"Unsupported voice '{voice}'. Choose one of: {', '.join(SUPPORTED_VOICES)}."
            )
        current["default_voice"] = voice
    _preferences[user_id] = current
    return get_preferences(user_id)


def clear_preferences() -> None:
    """Drop in-memory preferences. Used by tests."""
    _preferences.clear()

"""Voice processing services for speech-to-text, text-to-speech, and audio processing."""

from app.services.voice.audio_processor import (
    AudioProcessingError,
    AudioTooLargeError,
    AudioValidationError,
    UnsupportedAudioFormatError,
    detect_audio_format,
    sanitize_filename,
    temporary_audio_file,
    validate_audio,
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
    SpeechAudio,
    TTSAuthenticationError,
    TTSConfigurationError,
    TTSRateLimitError,
    TTSServiceError,
    TTSUnavailableError,
    TTSValidationError,
    synthesize_speech,
)

__all__ = [
    "AudioProcessingError",
    "AudioTooLargeError",
    "AudioValidationError",
    "UnsupportedAudioFormatError",
    "detect_audio_format",
    "sanitize_filename",
    "temporary_audio_file",
    "validate_audio",
    "STTAuthenticationError",
    "STTConfigurationError",
    "STTRateLimitError",
    "STTServiceError",
    "STTUnavailableError",
    "transcribe_audio",
    "SUPPORTED_VOICES",
    "SpeechAudio",
    "TTSAuthenticationError",
    "TTSConfigurationError",
    "TTSRateLimitError",
    "TTSServiceError",
    "TTSUnavailableError",
    "TTSValidationError",
    "synthesize_speech",
]

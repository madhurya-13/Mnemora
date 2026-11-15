"""Audio validation, format inspection, and safe temporary handling."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from collections.abc import Generator
from pathlib import Path

from app.config import settings

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".flac", ".mp4", ".mpeg"}
SUPPORTED_MIME_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mp3",
    "audio/mpeg",
    "audio/m4a",
    "audio/mp4",
    "audio/x-m4a",
    "audio/webm",
    "audio/ogg",
    "audio/x-flac",
    "audio/flac",
}


class AudioProcessingError(Exception):
    """Base error for audio processing failures."""


class AudioValidationError(AudioProcessingError):
    """Raised when audio content fails validation."""


class AudioTooLargeError(AudioProcessingError):
    """Raised when audio exceeds configured size limits."""


class UnsupportedAudioFormatError(AudioProcessingError):
    """Raised when audio format or magic bytes are unsupported."""


def sanitize_filename(filename: str | None, default_ext: str = ".webm") -> str:
    """Sanitize filename to prevent directory traversal and remove unsafe chars."""
    if not filename:
        return f"recording{default_ext}"
    base = Path(filename).name
    cleaned = re.sub(r"[^\w\-.]", "_", base).strip("._")
    ext = Path(cleaned).suffix.lower()
    if not ext or ext not in SUPPORTED_AUDIO_EXTENSIONS:
        return f"{cleaned or 'audio'}{default_ext}"
    return cleaned


def detect_audio_format(data: bytes) -> str | None:
    """Inspect magic numbers/file signatures to verify valid audio content."""
    if len(data) < 4:
        return None
    # WAV: RIFF....WAVE
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WAVE":
        return "wav"
    # WebM / Matroska: 0x1A 0x45 0xDF 0xA3
    if data[:4] == b"\x1a\x45\xdf\xa3" or data.find(b"\x1a\x45\xdf\xa3", 0, 1024) >= 0:
        return "webm"
    # Ogg: OggS
    if data[:4] == b"OggS":
        return "ogg"
    # FLAC: fLaC
    if data[:4] == b"fLaC":
        return "flac"
    # MP3 with ID3 tag: ID3
    if data[:3] == b"ID3":
        return "mp3"
    # Raw MP3 frame sync: 0xFF followed by 0xE0-0xFF
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "mp3"
    # M4A / MP4: offset 4 contains 'ftyp'
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "m4a"
    # Some browser-generated ISO-BMFF recordings include a short leading box
    # before the ftyp box. Only accept the signature in the initial container
    # header, never based on a filename or client-provided MIME type.
    if data.find(b"ftyp", 4, 64) >= 0:
        return "m4a"
    return None


def validate_audio(
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> tuple[str, str]:
    """Validate audio data size and format. Returns sanitized filename and detected format."""
    if not data or len(data) == 0:
        raise AudioValidationError("Audio data is empty.")

    max_bytes = settings.max_audio_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise AudioTooLargeError(
            f"Audio file size ({len(data) / (1024 * 1024):.1f} MB) exceeds maximum allowed size ({settings.max_audio_upload_mb} MB)."
        )

    detected_format = detect_audio_format(data)
    if not detected_format:
        raise UnsupportedAudioFormatError(
            "Unsupported or corrupted audio format. Supported formats: WAV, MP3, M4A, WebM, OGG, FLAC."
        )

    safe_name = sanitize_filename(filename, default_ext=f".{detected_format}")
    return safe_name, detected_format


@contextlib.contextmanager
def temporary_audio_file(data: bytes, suffix: str = ".webm") -> Generator[Path, None, None]:
    """Safely write audio bytes to a temporary file and guarantee cleanup."""
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    fd, temp_path_str = tempfile.mkstemp(prefix="mnemora_audio_", suffix=suffix)
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        yield temp_path
    finally:
        with contextlib.suppress(OSError):
            if temp_path.exists():
                temp_path.unlink()

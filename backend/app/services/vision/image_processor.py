"""Image validation, format detection, and base64 encoding."""

from __future__ import annotations

import base64
import contextlib
import os
import re
import tempfile
from collections.abc import Generator
from pathlib import Path

from app.config import settings

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
SUPPORTED_IMAGE_MIMES = {
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


class ImageProcessingError(Exception):
    """Base error for image processing failures."""


class ImageValidationError(ImageProcessingError):
    """Raised when image content fails validation."""


class ImageTooLargeError(ImageProcessingError):
    """Raised when image exceeds configured size limit."""


class UnsupportedImageFormatError(ImageProcessingError):
    """Raised when image format is unsupported."""


def sanitize_filename(filename: str | None, default_ext: str = ".png") -> str:
    """Sanitize filename to prevent directory traversal."""
    if not filename:
        return f"image{default_ext}"
    base = Path(filename).name
    cleaned = re.sub(r"[^\w\-.]", "_", base).strip("._")
    ext = Path(cleaned).suffix.lower()
    if not ext or ext not in SUPPORTED_IMAGE_EXTENSIONS:
        return f"{cleaned or 'image'}{default_ext}"
    return cleaned


def detect_image_format(data: bytes) -> str | None:
    """Inspect magic numbers/file signatures to verify image content."""
    if len(data) < 8:
        return None
    # JPEG: 0xFF 0xD8 0xFF
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    # PNG: 0x89 0x50 0x4E 0x47 0x0D 0x0A 0x1A 0x0A
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    # GIF: GIF87a or GIF89a
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    # WebP: RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def validate_image(
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> tuple[str, str, str]:
    """Validate image size and format.

    Returns:
        (sanitized_filename, detected_format, mime_type)
    """
    if not data or len(data) == 0:
        raise ImageValidationError("Image file is empty.")

    max_bytes = settings.max_image_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ImageTooLargeError(
            f"Image file size ({len(data) / (1024 * 1024):.1f} MB) exceeds maximum allowed size ({settings.max_image_upload_mb} MB)."
        )

    detected_format = detect_image_format(data)
    if not detected_format:
        raise UnsupportedImageFormatError(
            "Unsupported or corrupted image format. Supported formats: JPEG, PNG, WebP, GIF."
        )

    mime_type = f"image/{'jpeg' if detected_format == 'jpg' else detected_format}"
    safe_name = sanitize_filename(filename, default_ext=f".{detected_format}")
    return safe_name, detected_format, mime_type


def to_base64_data_url(data: bytes, mime_type: str) -> str:
    """Encode image bytes into a data URL for vision model input."""
    b64_str = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{b64_str}"


@contextlib.contextmanager
def temporary_image_file(data: bytes, suffix: str = ".png") -> Generator[Path, None, None]:
    """Safely write image bytes to a temporary file and guarantee cleanup."""
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    fd, temp_path_str = tempfile.mkstemp(prefix="mnemora_img_", suffix=suffix)
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        yield temp_path
    finally:
        with contextlib.suppress(OSError):
            if temp_path.exists():
                temp_path.unlink()

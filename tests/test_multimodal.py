"""Automated unit and integration tests for Multimodal features (Image understanding, Multimodal memory integration)."""

import asyncio
from typing import Any
from uuid import UUID
import httpx
import pytest

from app.api import chat as chat_api
from app.config import settings
from app.main import app
from app.schemas.chat import ChatMessage, ChatResponse
from app.services import vision, voice
from app.services.vision import image_processor, vision_service
from app.services.vision.image_processor import (
    ImageTooLargeError,
    ImageValidationError,
    UnsupportedImageFormatError,
    detect_image_format,
    validate_image,
)

_test_cookies = httpx.Cookies()


def run_request(
    method: str,
    path: str,
    *,
    cookie_jar: httpx.Cookies | None = None,
    **kwargs: Any,
) -> httpx.Response:
    jar = cookie_jar if cookie_jar is not None else _test_cookies

    async def perform() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies=jar) as client:
            response = await client.request(method, path, **kwargs)
            jar.update(response.cookies)
            return response

    return asyncio.run(perform())


@pytest.fixture(autouse=True)
def clean_cookies():
    _test_cookies.clear()
    yield
    _test_cookies.clear()


# Minimal valid 1x1 PNG bytes
def make_mock_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


# Minimal valid JPEG bytes
def make_mock_jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\xff\xd9"


# Minimal valid WAV bytes
def make_mock_wav_bytes() -> bytes:
    header = bytearray(b"RIFF")
    header.extend((36).to_bytes(4, "little"))
    header.extend(b"WAVEfmt ")
    header.extend((16).to_bytes(4, "little"))
    header.extend((1).to_bytes(2, "little"))
    header.extend((1).to_bytes(2, "little"))
    header.extend((16000).to_bytes(4, "little"))
    header.extend((32000).to_bytes(4, "little"))
    header.extend((2).to_bytes(2, "little"))
    header.extend((16).to_bytes(2, "little"))
    header.extend(b"data")
    header.extend((0).to_bytes(4, "little"))
    return bytes(header)


def test_image_format_detection():
    png = make_mock_png_bytes()
    assert detect_image_format(png) == "png"

    jpeg = make_mock_jpeg_bytes()
    assert detect_image_format(jpeg) == "jpeg"

    assert detect_image_format(b"not an image file") is None


def test_image_validation_rejects_empty():
    with pytest.raises(ImageValidationError):
        validate_image(b"")


def test_image_validation_rejects_unsupported():
    with pytest.raises(UnsupportedImageFormatError):
        validate_image(b"not an image file at all", filename="doc.pdf")


def test_image_validation_rejects_oversized(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "max_image_upload_mb", 1)
    large_bytes = b"0" * (2 * 1024 * 1024)
    with pytest.raises(ImageTooLargeError):
        validate_image(large_bytes, filename="huge.png")


def test_chat_message_with_image_success(monkeypatch: pytest.MonkeyPatch):
    # Mock vision service
    async def mock_analyze_image(data: bytes, prompt: str = "", **kwargs) -> str:
        return "Diagram shows a FastAPI backend and a Next.js frontend communicating via REST."

    monkeypatch.setattr(chat_api, "analyze_image", mock_analyze_image)

    # Mock assistant reply
    async def fake_respond(conv_id: str, message: str, history: list[ChatMessage], memories: list[str] | None = None) -> ChatResponse:
        assert "FastAPI backend" in message or "Diagram" in message
        return ChatResponse(conversation_id=UUID(conv_id), response="I see your architecture diagram with FastAPI and Next.js.")

    monkeypatch.setattr(chat_api, "respond", fake_respond)

    # Create conversation first
    conv = run_request("POST", "/api/v1/conversations", json={"title": "Architecture Chat"}).json()
    conv_id = conv["conversation_id"]

    png = make_mock_png_bytes()
    resp = run_request(
        "POST",
        f"/api/v1/chat/{conv_id}/message-with-image",
        data={"message": "Explain this architecture diagram."},
        files={"image": ("arch.png", png, "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_id"] == conv_id
    assert "architecture diagram" in data["response"]

    # Verify conversation history persisted
    detail = run_request("GET", f"/api/v1/conversations/{conv_id}").json()
    assert len(detail["messages"]) == 2
    assert "[Attached image: arch.png]" in detail["messages"][0]["content"]
    assert detail["messages"][1]["content"] == "I see your architecture diagram with FastAPI and Next.js."


def test_chat_message_with_image_new_conversation(monkeypatch: pytest.MonkeyPatch):
    async def mock_analyze_image(data: bytes, prompt: str = "", **kwargs) -> str:
        return "Screenshot showing a database connection error 503."

    monkeypatch.setattr(chat_api, "analyze_image", mock_analyze_image)

    async def fake_respond(conv_id: str, message: str, history: list[ChatMessage], memories: list[str] | None = None) -> ChatResponse:
        return ChatResponse(conversation_id=UUID(conv_id), response="The error indicates database connection failure.")

    monkeypatch.setattr(chat_api, "respond", fake_respond)

    png = make_mock_png_bytes()
    resp = run_request(
        "POST",
        "/api/v1/chat/new/message-with-image",
        data={"message": "What is this error?"},
        files={"image": ("error.png", png, "image/png")},
    )
    assert resp.status_code == 200
    new_conv_id = resp.json()["conversation_id"]
    assert new_conv_id is not None

    detail = run_request("GET", f"/api/v1/conversations/{new_conv_id}").json()
    assert len(detail["messages"]) == 2


def test_chat_message_with_image_rejects_corrupted_file():
    conv = run_request("POST", "/api/v1/conversations", json={}).json()
    conv_id = conv["conversation_id"]

    resp = run_request(
        "POST",
        f"/api/v1/chat/{conv_id}/message-with-image",
        data={"message": "Analyze this file"},
        files={"image": ("corrupted.png", b"not-a-png-header", "image/png")},
    )
    assert resp.status_code == 400


def test_chat_message_with_image_enforces_user_isolation(monkeypatch: pytest.MonkeyPatch):
    # User A creates a conversation
    conv_a = run_request("POST", "/api/v1/conversations", json={}).json()
    conv_a_id = conv_a["conversation_id"]

    # Stranger (User B) tries to post an image to User A's conversation
    stranger = httpx.Cookies()
    png = make_mock_png_bytes()
    denied = run_request(
        "POST",
        f"/api/v1/chat/{conv_a_id}/message-with-image",
        cookie_jar=stranger,
        data={"message": "Malicious inject"},
        files={"image": ("test.png", png, "image/png")},
    )
    assert denied.status_code == 404


def test_chat_message_with_audio_success(monkeypatch: pytest.MonkeyPatch):
    async def mock_transcribe(*args, **kwargs) -> str:
        return "What are the latest updates to our project?"

    monkeypatch.setattr(chat_api, "transcribe_audio", mock_transcribe)

    async def fake_respond(conv_id: str, message: str, history: list[ChatMessage], memories: list[str] | None = None) -> ChatResponse:
        assert message == "What are the latest updates to our project?"
        return ChatResponse(conversation_id=UUID(conv_id), response="The project was recently updated with voice support.")

    monkeypatch.setattr(chat_api, "respond", fake_respond)

    conv = run_request("POST", "/api/v1/conversations", json={}).json()
    conv_id = conv["conversation_id"]

    wav = make_mock_wav_bytes()
    resp = run_request(
        "POST",
        f"/api/v1/chat/{conv_id}/message-with-audio",
        files={"audio": ("speech.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.json()["response"] == "The project was recently updated with voice support."

    # Verify transcript saved as user message
    detail = run_request("GET", f"/api/v1/conversations/{conv_id}").json()
    assert detail["messages"][0]["content"] == "What are the latest updates to our project?"
    assert detail["messages"][1]["content"] == "The project was recently updated with voice support."


def test_multimodal_memory_retrieval_integration(monkeypatch: pytest.MonkeyPatch):
    """Test that voice and image inputs query Milestone 5 memory retrieval."""
    retrieval_calls: list[str] = []

    async def mock_retrieve_context(db, user_id, query: str):
        retrieval_calls.append(query)
        if "FastAPI" in query or "architecture" in query:
            return ["RELEVANT USER CONTEXT:\nProjects:\n- MNEMORA is built with FastAPI and Next.js."]
        return []

    monkeypatch.setattr(chat_api, "retrieve_context", mock_retrieve_context)

    async def mock_analyze_image(data: bytes, prompt: str = "", **kwargs) -> str:
        return "Architecture diagram showing FastAPI backend connecting to SQLite and ChromaDB."

    monkeypatch.setattr(chat_api, "analyze_image", mock_analyze_image)

    captured_memories: list[list[str] | None] = []

    async def fake_respond(conv_id: str, message: str, history: list[ChatMessage], memories: list[str] | None = None) -> ChatResponse:
        captured_memories.append(memories)
        return ChatResponse(conversation_id=UUID(conv_id), response="Identified architecture and matched existing project memories.")

    monkeypatch.setattr(chat_api, "respond", fake_respond)

    png = make_mock_png_bytes()
    resp = run_request(
        "POST",
        "/api/v1/chat/new/message-with-image",
        data={"message": "Does this match our current backend setup?"},
        files={"image": ("diagram.png", png, "image/png")},
    )
    assert resp.status_code == 200
    assert len(retrieval_calls) > 0
    # Memory was retrieved and passed to assistant
    assert len(captured_memories) == 1
    assert captured_memories[0] is not None
    assert "MNEMORA is built with FastAPI" in captured_memories[0][0]

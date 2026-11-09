import asyncio
import sys
import types
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from app.agents import assistant
from app.api import chat as chat_api
from app.config import Settings
from app.main import app
from app.schemas.chat import ChatMessage, ChatResponse
from app.services.conversation_store import conversation_store
from app.services.llm_service import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMUnavailableError,
    get_genai_client,
    generate,
    stream,
)


def run_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def perform() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(perform())


@pytest.fixture(autouse=True)
def clean_conversations():
    conversation_store.clear_all()
    yield
    conversation_store.clear_all()


def test_chat_validation_rejects_blank_and_oversized_messages() -> None:
    blank = run_request("POST", "/api/v1/chat", json={"message": "   "})
    too_long = run_request("POST", "/api/v1/chat", json={"message": "x" * 8001})
    assert blank.status_code == 422
    assert too_long.status_code == 422
    assert blank.json()["error"]["code"] == "invalid_request"


def test_chat_generates_an_id_when_missing_and_rejects_unknown_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_respond(conversation_id: str, message: str, history: list[ChatMessage]) -> ChatResponse:
        return ChatResponse(conversation_id=conversation_id, response=f"Echo: {message}")

    monkeypatch.setattr(chat_api, "respond", fake_respond)
    response = run_request("POST", "/api/v1/chat", json={"message": "Hello"})
    assert response.status_code == 200
    assert response.json()["conversation_id"].startswith("conv_")
    assert response.json()["response"] == "Echo: Hello"
    unknown = run_request("POST", "/api/v1/chat", json={"conversation_id": "missing", "message": "Hello"})
    assert unknown.status_code == 404


def test_conversation_context_is_limited_and_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, list[tuple[str, str]]]] = []

    async def fake_respond(conversation_id: str, message: str, history: list[ChatMessage]) -> ChatResponse:
        calls.append((conversation_id, message, [(item.role, item.content) for item in history]))
        knows_name = any(item.role == "user" and "Alex" in item.content for item in history)
        answer = "Your name is Alex." if message == "What is my name?" and knows_name else "I don't know your name yet."
        if message == "My name is Alex.":
            answer = "Nice to meet you, Alex."
        return ChatResponse(conversation_id=conversation_id, response=answer)

    monkeypatch.setattr(chat_api, "respond", fake_respond)
    first = run_request("POST", "/api/v1/chat/conversations", json={}).json()["conversation_id"]
    second = run_request("POST", "/api/v1/chat/conversations", json={}).json()["conversation_id"]
    run_request("POST", "/api/v1/chat", json={"conversation_id": first, "message": "My name is Alex."})
    answer_a = run_request("POST", "/api/v1/chat", json={"conversation_id": first, "message": "What is my name?"})
    answer_b = run_request("POST", "/api/v1/chat", json={"conversation_id": second, "message": "What is my name?"})
    assert answer_a.json()["response"] == "Your name is Alex."
    assert answer_b.json()["response"] == "I don't know your name yet."
    assert [item[0] for item in calls] == [first, first, second]
    assert calls[1][2] == [("user", "My name is Alex."), ("assistant", "Nice to meet you, Alex.")]
    assert calls[2][2] == []


def test_assistant_limits_model_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assistant.settings, "chat_max_history_messages", 2)
    now = datetime.now(timezone.utc)
    history = [
        ChatMessage(role="user", content="old", created_at=now),
        ChatMessage(role="assistant", content="older reply", created_at=now),
        ChatMessage(role="user", content="recent", created_at=now),
    ]
    built = assistant.build_model_messages(history, "current")
    assert built[0][0] == "system"
    assert built[1:] == [
        ("assistant", "older reply"),
        ("user", "recent"),
        ("human", "current"),
    ]


def test_stream_endpoint_returns_real_sse_frames_and_stores_complete_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(history: list[ChatMessage], message: str):
        yield "Hello "
        yield "from a stream."

    monkeypatch.setattr(chat_api, "stream_response", fake_stream)
    created = run_request("POST", "/api/v1/chat/conversations", json={}).json()
    response = run_request(
        "POST",
        "/api/v1/chat/stream",
        json={"conversation_id": created["conversation_id"], "message": "Say hello"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: token\ndata: {"text": "Hello "}' in response.text
    assert 'event: done\n' in response.text
    detail = run_request("GET", f"/api/v1/chat/conversations/{created['conversation_id']}").json()
    assert detail["messages"][-1]["content"] == "Hello from a stream."


def test_llm_missing_key_fails_without_constructing_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_api.settings, "google_api_key", "")
    response = run_request("GET", "/api/v1/chat/health")
    assert response.json() == {"status": "not_configured", "configured": False, "model": "gemini-3.5-flash-lite"}
    with pytest.raises(LLMConfigurationError, match="GOOGLE_API_KEY"):
        from app.services import llm_service

        llm_service.get_genai_client.cache_clear()
        llm_service.get_genai_client()


def test_chat_maps_rate_limit_to_retryable_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_respond(conversation_id: str, message: str, history: list[ChatMessage]) -> ChatResponse:
        raise LLMRateLimitError("The AI service is rate limited. Please wait and try again.")

    monkeypatch.setattr(chat_api, "respond", fake_respond)
    created = run_request("POST", "/api/v1/chat/conversations", json={}).json()
    response = run_request(
        "POST",
        "/api/v1/chat",
        json={"conversation_id": created["conversation_id"], "message": "Try this"},
    )
    assert response.status_code == 429
    assert response.json()["detail"].startswith("The AI service is rate limited")


def test_conversation_can_be_renamed_cleared_and_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_respond(conversation_id: str, message: str, history: list[ChatMessage]) -> ChatResponse:
        return ChatResponse(conversation_id=conversation_id, response="Mock reply")

    monkeypatch.setattr(chat_api, "respond", fake_respond)
    created = run_request("POST", "/api/v1/chat/conversations", json={}).json()
    conversation_id = created["conversation_id"]
    run_request("POST", "/api/v1/chat", json={"conversation_id": conversation_id, "message": "Hello"})
    renamed = run_request("PATCH", f"/api/v1/chat/conversations/{conversation_id}", json={"title": "Planning"})
    assert renamed.json()["title"] == "Planning"
    cleared = run_request("DELETE", f"/api/v1/chat/conversations/{conversation_id}/messages")
    assert cleared.json()["messages"] == []
    deleted = run_request("DELETE", f"/api/v1/chat/conversations/{conversation_id}")
    assert deleted.status_code == 204
    assert run_request("GET", f"/api/v1/chat/conversations/{conversation_id}").status_code == 404


def test_stream_error_event_does_not_commit_a_partial_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken_stream(history: list[ChatMessage], message: str):
        yield "partial"
        raise LLMUnavailableError("The AI service is temporarily unavailable. Please try again.")

    monkeypatch.setattr(chat_api, "stream_response", broken_stream)
    created = run_request("POST", "/api/v1/chat/conversations", json={}).json()
    conversation_id = created["conversation_id"]
    response = run_request("POST", "/api/v1/chat/stream", json={"conversation_id": conversation_id, "message": "Hello"})
    assert 'event: token\ndata: {"text": "partial"}' in response.text
    assert 'event: error\n' in response.text
    detail = run_request("GET", f"/api/v1/chat/conversations/{conversation_id}").json()
    assert detail["messages"] == []


def test_llm_authentication_failures_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    class AuthenticationError(Exception):
        code = 401

    class FakeModels:
        async def generate_content(self, **kwargs: Any) -> Any:
            assert kwargs["contents"][-1]["role"] == "user"
            raise AuthenticationError("authorization header contains secret material")

    fake_genai = types.ModuleType("google.genai")
    fake_types = types.ModuleType("google.genai.types")
    fake_types.GenerateContentConfig = lambda **kwargs: kwargs
    fake_genai.types = fake_types
    fake_google = types.ModuleType("google")
    fake_google.__path__ = []
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setattr("app.services.llm_service.get_genai_client", lambda: types.SimpleNamespace(
        aio=types.SimpleNamespace(models=FakeModels())
    ))

    async def invoke() -> None:
        await generate([("system", "system"), ("human", "hello")])

    with pytest.raises(LLMAuthenticationError, match="configured API key") as captured:
        asyncio.run(invoke())
    assert "secret material" not in str(captured.value)


def test_model_configuration_is_environment_driven_and_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("GEMINI_TEMPERATURE", "0.25")
    monkeypatch.setenv("GEMINI_MAX_TOKENS", "777")
    parsed = Settings(_env_file=None)
    assert parsed.gemini_model == "gemini-test-model"
    assert parsed.gemini_temperature == 0.25
    assert parsed.gemini_max_tokens == 777

    captured: dict[str, object] = {}

    class FakeChatClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake_genai = types.ModuleType("google.genai")
    fake_genai.__path__ = []
    fake_types = types.ModuleType("google.genai.types")

    class FakeHttpOptions:
        def __init__(self, **kwargs: object) -> None:
            self.values = kwargs

    class FakeGenerationConfig:
        def __init__(self, **kwargs: object) -> None:
            self.values = kwargs

    fake_types.HttpOptions = FakeHttpOptions
    fake_types.GenerateContentConfig = FakeGenerationConfig
    fake_genai.types = fake_types
    fake_genai.Client = FakeChatClient
    fake_google = types.ModuleType("google")
    fake_google.__path__ = []
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setattr(chat_api.settings, "google_api_key", "unit-test-key")
    monkeypatch.setattr(chat_api.settings, "gemini_model", "gemini-3.5-flash-lite")
    get_genai_client.cache_clear()
    client = get_genai_client()
    assert isinstance(client, FakeChatClient)
    assert captured["api_key"] == "unit-test-key"
    assert captured["http_options"].values == {"timeout": 60000}
    get_genai_client.cache_clear()


def test_authentication_error_returns_safe_api_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_respond(conversation_id: str, message: str, history: list[ChatMessage]) -> ChatResponse:
        from app.services.llm_service import LLMAuthenticationError

        raise LLMAuthenticationError("Google rejected the configured API key.")

    monkeypatch.setattr(chat_api, "respond", fake_respond)
    created = run_request("POST", "/api/v1/chat/conversations", json={}).json()
    response = run_request(
        "POST",
        "/api/v1/chat",
        json={"conversation_id": created["conversation_id"], "message": "Hello"},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Google rejected the configured API key. Check backend/.env."
    assert "api key" in response.json()["detail"].lower()


def test_llm_service_supports_async_generation_and_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModels:
        async def generate_content(self, **kwargs: Any) -> Any:
            assert kwargs["contents"][-1] == {"role": "user", "parts": [{"text": "hello"}]}
            return type("FakeResponse", (), {"text": "A mocked response."})()

        async def generate_content_stream(self, **kwargs: Any):
            async def chunks():
                yield type("FakeChunk", (), {"text": "A mocked "})()
                yield type("FakeChunk", (), {"text": "stream."})()

            return chunks()

    fake_genai = types.ModuleType("google.genai")
    fake_types = types.ModuleType("google.genai.types")
    fake_types.GenerateContentConfig = lambda **kwargs: kwargs
    fake_genai.types = fake_types
    fake_google = types.ModuleType("google")
    fake_google.__path__ = []
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setattr("app.services.llm_service.get_genai_client", lambda: types.SimpleNamespace(
        aio=types.SimpleNamespace(models=FakeModels())
    ))
    messages = [("system", "system prompt"), ("human", "hello")]

    async def exercise() -> tuple[str, list[str]]:
        answer = await generate(messages)
        chunks = [chunk async for chunk in stream(messages)]
        return answer, chunks

    answer, chunks = asyncio.run(exercise())
    assert answer == "A mocked response."
    assert chunks == ["A mocked ", "stream."]

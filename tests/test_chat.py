import asyncio
import sys
import types
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.agents import assistant
from app.api import chat as chat_api
from app.config import Settings
from app.database.base import Base
from app.database.db import make_engine
from app.main import app
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.chat import ChatMessage, ChatResponse
from app.services.llm_service import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMUnavailableError,
    get_genai_client,
    generate,
    stream,
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
def clean_guest_cookie():
    _test_cookies.clear()
    yield
    _test_cookies.clear()


def make_mock_reply(monkeypatch: pytest.MonkeyPatch, recorder: list | None = None) -> None:
    async def fake_respond(conversation_id: str, message: str, history: list[ChatMessage]) -> ChatResponse:
        if recorder is not None:
            recorder.append((conversation_id, message, [(item.role, item.content) for item in history]))
        return ChatResponse(conversation_id=UUID(conversation_id), response=f"Echo: {message}")

    monkeypatch.setattr(chat_api, "respond", fake_respond)


def test_guest_session_cookie_is_httponly_and_only_hash_is_persisted(temporary_database) -> None:
    response = run_request("GET", "/api/v1/conversations")
    assert response.status_code == 200
    cookie = response.cookies.get("mnemora_session")
    assert cookie and len(cookie) > 30
    assert "httponly" in response.headers["set-cookie"].lower()

    with temporary_database["factory"]() as db:
        user = db.scalar(select(User))
        assert user is not None
        assert user.guest_session_hash != cookie
        assert len(user.guest_session_hash) == 64


def test_create_chat_autotitles_and_persists_both_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    make_mock_reply(monkeypatch)
    created = run_request("POST", "/api/v1/conversations", json={"title": "New chat"})
    assert created.status_code == 201
    conversation_id = created.json()["conversation_id"]

    response = run_request("POST", "/api/v1/chat", json={
        "conversation_id": conversation_id,
        "message": "What is a database index?",
    })
    assert response.status_code == 200
    assert response.json()["conversation_id"] == conversation_id

    detail = run_request("GET", f"/api/v1/conversations/{conversation_id}").json()
    assert detail["title"] == "What is a database index?"
    assert detail["last_message_at"]
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant"]
    assert [item["status"] for item in detail["messages"]] == ["completed", "completed"]
    assert detail["messages"][1]["content"] == "Echo: What is a database index?"


def test_independent_histories_context_order_and_context_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, list[tuple[str, str]]]] = []
    make_mock_reply(monkeypatch, calls)
    first = run_request("POST", "/api/v1/conversations", json={}).json()["conversation_id"]
    second = run_request("POST", "/api/v1/conversations", json={}).json()["conversation_id"]
    run_request("POST", "/api/v1/chat", json={"conversation_id": first, "message": "one"})
    run_request("POST", "/api/v1/chat", json={"conversation_id": first, "message": "two"})
    run_request("POST", "/api/v1/chat", json={"conversation_id": second, "message": "separate"})

    assert calls[1][2] == [("user", "one"), ("assistant", "Echo: one")]
    assert calls[2][2] == []

    monkeypatch.setattr(assistant.settings, "chat_max_history_messages", 2)
    run_request("POST", "/api/v1/chat", json={"conversation_id": first, "message": "three"})
    assert calls[-1][2] == [("user", "two"), ("assistant", "Echo: two")]
    assert assistant.build_model_messages([], "current")[0][0] == "system"


def test_conversation_and_messages_survive_database_engine_restart(temporary_database, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, list[tuple[str, str]]]] = []
    make_mock_reply(monkeypatch, calls)
    created = run_request("POST", "/api/v1/chat", json={"message": "My favorite color is blue."})
    conversation_id = created.json()["conversation_id"]
    assert created.status_code == 200

    temporary_database["engine"].dispose()
    new_engine = make_engine(temporary_database["database_url"])
    temporary_database["engine"] = new_engine
    temporary_database["factory"] = sessionmaker(
        bind=new_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    restored = run_request("GET", f"/api/v1/conversations/{conversation_id}")
    assert restored.status_code == 200
    assert len(restored.json()["messages"]) == 2

    continued = run_request("POST", "/api/v1/chat", json={
        "conversation_id": conversation_id,
        "message": "What color did I mention?",
    })
    assert continued.status_code == 200
    assert calls[-1][2] == [
        ("user", "My favorite color is blue."),
        ("assistant", "Echo: My favorite color is blue."),
    ]


def test_conversation_pagination_activity_archive_and_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    make_mock_reply(monkeypatch)
    ids = [run_request("POST", "/api/v1/conversations", json={"title": f"Chat {i}"}).json()["conversation_id"] for i in range(3)]
    page = run_request("GET", "/api/v1/conversations?archived=false&limit=2&offset=0").json()
    assert page["total"] == 3 and len(page["items"]) == 2
    page2 = run_request("GET", "/api/v1/conversations?archived=false&limit=2&offset=2").json()
    assert len(page2["items"]) == 1

    archived = run_request("PATCH", f"/api/v1/conversations/{ids[0]}", json={"is_archived": True})
    assert archived.status_code == 200 and archived.json()["is_archived"] is True
    assert run_request("GET", "/api/v1/conversations?archived=false").json()["total"] == 2
    assert run_request("GET", "/api/v1/conversations?archived=true").json()["items"][0]["conversation_id"] == ids[0]
    restored = run_request("PATCH", f"/api/v1/conversations/{ids[0]}", json={"title": "Renamed", "is_archived": False})
    assert restored.json()["title"] == "Renamed" and not restored.json()["is_archived"]


def test_message_pagination_is_chronological_and_owner_scoped(temporary_database, monkeypatch: pytest.MonkeyPatch) -> None:
    make_mock_reply(monkeypatch)
    conversation_id = run_request("POST", "/api/v1/conversations", json={}).json()["conversation_id"]
    for index in range(3):
        run_request("POST", "/api/v1/chat", json={"conversation_id": conversation_id, "message": f"message {index}"})
    first = run_request("GET", f"/api/v1/conversations/{conversation_id}/messages?limit=2&offset=0").json()
    second = run_request("GET", f"/api/v1/conversations/{conversation_id}/messages?limit=2&offset=2").json()
    assert [message["content"] for message in first["items"]] == ["message 0", "Echo: message 0"]
    assert [message["content"] for message in second["items"][:2]] == ["message 1", "Echo: message 1"]

    stranger = httpx.Cookies()
    stranger_response = run_request("GET", "/api/v1/conversations", cookie_jar=stranger)
    assert stranger_response.status_code == 200
    assert run_request("GET", f"/api/v1/conversations/{conversation_id}", cookie_jar=stranger).status_code == 404
    denied = run_request("DELETE", f"/api/v1/conversations/{conversation_id}", cookie_jar=stranger)
    assert denied.status_code == 404
    assert run_request("POST", "/api/v1/chat", cookie_jar=stranger, json={
        "conversation_id": conversation_id, "message": "inject into another owner's conversation"
    }).status_code == 404


def test_delete_cascades_messages_and_database_rejects_orphan_rows(temporary_database) -> None:
    created = run_request("POST", "/api/v1/conversations", json={}).json()
    conversation_id = UUID(created["conversation_id"])
    with temporary_database["factory"]() as db:
        guest = db.scalar(select(User))
        assert guest is not None
        MessageRepository(db).save_message(conversation_id, "user", "persist me")
        db.commit()
        with pytest.raises(IntegrityError):
            MessageRepository(db).save_message(UUID(int=123), "user", "orphan")
        db.rollback()

    deleted = run_request("DELETE", f"/api/v1/conversations/{conversation_id}")
    assert deleted.status_code == 204
    with temporary_database["factory"]() as db:
        count = db.scalar(select(func.count(Message.message_id)).where(Message.conversation_id == conversation_id))
        assert count == 0


def test_successful_stream_persists_complete_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    run_request("GET", "/api/v1/conversations")
    async def fake_stream(history: list[ChatMessage], message: str):
        assert history == []
        yield "Hello "
        yield "from Gemini."

    monkeypatch.setattr(chat_api, "stream_response", fake_stream)
    response = run_request("POST", "/api/v1/chat/stream", json={"message": "Say hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: token\ndata: {"text": "Hello "}' in response.text
    assert "event: done" in response.text
    conversation_id = response.text.split('"conversation_id": "', 1)[1].split('"', 1)[0]
    detail = run_request("GET", f"/api/v1/conversations/{conversation_id}").json()
    assert [message["content"] for message in detail["messages"]] == ["Say hello", "Hello from Gemini."]
    assert [message["status"] for message in detail["messages"]] == ["completed", "completed"]


def test_stream_failure_keeps_user_message_failed_without_partial_assistant(monkeypatch: pytest.MonkeyPatch) -> None:
    run_request("GET", "/api/v1/conversations")
    async def broken_stream(history: list[ChatMessage], message: str):
        yield "partial output"
        raise LLMUnavailableError("The Gemini service is temporarily unavailable.")

    monkeypatch.setattr(chat_api, "stream_response", broken_stream)
    response = run_request("POST", "/api/v1/chat/stream", json={"message": "Try a stream"})
    assert 'event: token\ndata: {"text": "partial output"}' in response.text
    assert "event: error" in response.text
    conversation_id = response.text.split('"conversation_id": "', 1)[1].split('"', 1)[0]
    detail = run_request("GET", f"/api/v1/conversations/{conversation_id}").json()
    assert [(message["role"], message["status"], message["content"]) for message in detail["messages"]] == [
        ("user", "failed", "Try a stream")
    ]


def test_nonstream_failure_records_failed_user_message(monkeypatch: pytest.MonkeyPatch) -> None:
    run_request("GET", "/api/v1/conversations")
    async def fail_response(conversation_id: str, message: str, history: list[ChatMessage]) -> ChatResponse:
        raise LLMRateLimitError("Gemini free-tier quota reached.")

    monkeypatch.setattr(chat_api, "respond", fail_response)
    response = run_request("POST", "/api/v1/chat", json={"message": "Rate limited"})
    assert response.status_code == 429
    conversations = run_request("GET", "/api/v1/conversations").json()["items"]
    detail = run_request("GET", f"/api/v1/conversations/{conversations[0]['conversation_id']}").json()
    assert [(message["role"], message["status"]) for message in detail["messages"]] == [("user", "failed")]


def test_context_builder_preserves_system_prompt_and_recent_chronological_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assistant.settings, "chat_max_history_messages", 2)
    monkeypatch.setattr(assistant.settings, "assistant_system_prompt", "Keep the user's saved preferences in mind.")
    now = datetime.now(timezone.utc)
    history = [
        ChatMessage(message_id=UUID(int=1), role="user", content="old", created_at=now, status="completed"),
        ChatMessage(message_id=UUID(int=2), role="assistant", content="old reply", created_at=now, status="completed"),
        ChatMessage(message_id=UUID(int=3), role="user", content="recent", created_at=now, status="completed"),
    ]
    built = assistant.build_model_messages(history, "current")
    assert built == [
        ("system", "Keep the user's saved preferences in mind."),
        ("assistant", "old reply"),
        ("user", "recent"),
        ("human", "current"),
    ]


def test_chat_rejects_unknown_and_other_users_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    make_mock_reply(monkeypatch)
    owner_id = run_request("POST", "/api/v1/conversations", json={}).json()["conversation_id"]
    stranger = httpx.Cookies()
    run_request("GET", "/api/v1/conversations", cookie_jar=stranger)
    assert run_request("GET", "/api/v1/conversations/00000000-0000-0000-0000-000000000001").status_code == 404
    assert run_request("POST", "/api/v1/chat", cookie_jar=stranger, json={
        "conversation_id": owner_id, "message": "not yours"
    }).status_code == 404
    assert run_request("DELETE", f"/api/v1/conversations/{owner_id}", cookie_jar=stranger).status_code == 404


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

    fake_types.HttpOptions = FakeHttpOptions
    fake_genai.types = fake_types
    fake_genai.Client = FakeChatClient
    fake_google = types.ModuleType("google")
    fake_google.__path__ = []
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setattr(chat_api.settings, "google_api_key", "unit-test-key")
    get_genai_client.cache_clear()
    client = get_genai_client()
    assert isinstance(client, FakeChatClient)
    assert captured["api_key"] == "unit-test-key"
    assert captured["http_options"].values == {"timeout": 60000}
    get_genai_client.cache_clear()


def test_llm_service_supports_async_generation_streaming_and_sanitized_auth_errors(monkeypatch: pytest.MonkeyPatch) -> None:
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

    async def exercise() -> tuple[str, list[str]]:
        answer = await generate([("system", "system prompt"), ("human", "hello")])
        chunks = [chunk async for chunk in stream([("system", "system prompt"), ("human", "hello")])]
        return answer, chunks

    answer, chunks = asyncio.run(exercise())
    assert answer == "A mocked response."
    assert chunks == ["A mocked ", "stream."]

    class Unauthorized(Exception):
        code = 401

    class UnauthorizedModels:
        async def generate_content(self, **kwargs: Any) -> Any:
            raise Unauthorized("secret header content")

    monkeypatch.setattr("app.services.llm_service.get_genai_client", lambda: types.SimpleNamespace(
        aio=types.SimpleNamespace(models=UnauthorizedModels())
    ))
    with pytest.raises(LLMAuthenticationError) as captured:
        asyncio.run(generate([("system", "system"), ("human", "hello")]))
    assert "secret header content" not in str(captured.value)

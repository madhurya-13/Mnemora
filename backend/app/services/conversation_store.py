"""Thread-safe in-memory conversation storage for the current backend process."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.schemas.chat import ChatMessage, ConversationDetail, ConversationSummary


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _Conversation:
    conversation_id: str
    title: str = "New chat"
    messages: list[ChatMessage] = field(default_factory=list)
    updated_at: datetime = field(default_factory=_now)


class InMemoryConversationStore:
    """Storage interface that can be replaced by a persistent repository later."""

    def __init__(self) -> None:
        self._conversations: dict[str, _Conversation] = {}
        self._guard = RLock()
        self._turn_locks: dict[str, asyncio.Lock] = {}

    def create(self, title: str = "New chat") -> ConversationDetail:
        with self._guard:
            conversation_id = f"conv_{uuid4().hex}"
            record = _Conversation(conversation_id=conversation_id, title=title.strip() or "New chat")
            self._conversations[conversation_id] = record
            return self._detail(record)

    def get(self, conversation_id: str) -> ConversationDetail | None:
        with self._guard:
            record = self._conversations.get(conversation_id)
            return self._detail(record) if record else None

    def get_history(self, conversation_id: str) -> list[ChatMessage] | None:
        with self._guard:
            record = self._conversations.get(conversation_id)
            return list(record.messages) if record else None

    def list(self) -> list[ConversationSummary]:
        with self._guard:
            records = sorted(self._conversations.values(), key=lambda item: item.updated_at, reverse=True)
            return [self._summary(record) for record in records]

    def append_turn(self, conversation_id: str, user_text: str, assistant_text: str) -> ConversationDetail | None:
        with self._guard:
            record = self._conversations.get(conversation_id)
            if record is None:
                return None
            now = _now()
            if not record.messages and record.title == "New chat":
                record.title = user_text.strip().replace("\n", " ")[:48] or "New chat"
            record.messages.extend([
                ChatMessage(role="user", content=user_text, created_at=now),
                ChatMessage(role="assistant", content=assistant_text, created_at=_now()),
            ])
            record.updated_at = _now()
            return self._detail(record)

    def clear(self, conversation_id: str) -> bool:
        with self._guard:
            record = self._conversations.get(conversation_id)
            if record is None:
                return False
            record.messages.clear()
            record.title = "New chat"
            record.updated_at = _now()
            return True

    def remove_last_turn(self, conversation_id: str, expected_user_text: str) -> bool:
        """Remove the last completed user/assistant pair before regenerating it."""
        with self._guard:
            record = self._conversations.get(conversation_id)
            if (
                record is None
                or len(record.messages) < 2
                or record.messages[-2].role != "user"
                or record.messages[-2].content != expected_user_text
                or record.messages[-1].role != "assistant"
            ):
                return False
            del record.messages[-2:]
            record.updated_at = _now()
            if not record.messages:
                record.title = "New chat"
            return True

    def rename(self, conversation_id: str, title: str) -> ConversationSummary | None:
        with self._guard:
            record = self._conversations.get(conversation_id)
            if record is None:
                return None
            record.title = title.strip()
            record.updated_at = _now()
            return self._summary(record)

    def delete(self, conversation_id: str) -> bool:
        with self._guard:
            self._turn_locks.pop(conversation_id, None)
            return self._conversations.pop(conversation_id, None) is not None

    def turn_lock(self, conversation_id: str) -> asyncio.Lock:
        with self._guard:
            return self._turn_locks.setdefault(conversation_id, asyncio.Lock())

    def clear_all(self) -> None:
        """Clear all conversations; useful for tests and administrative resets."""
        with self._guard:
            self._conversations.clear()
            self._turn_locks.clear()

    @staticmethod
    def _summary(record: _Conversation) -> ConversationSummary:
        return ConversationSummary(
            conversation_id=record.conversation_id,
            title=record.title,
            updated_at=record.updated_at,
            message_count=len(record.messages),
        )

    @classmethod
    def _detail(cls, record: _Conversation) -> ConversationDetail:
        summary = cls._summary(record)
        return ConversationDetail(**summary.model_dump(), messages=list(record.messages))


conversation_store = InMemoryConversationStore()

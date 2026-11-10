"""SQLAlchemy message persistence and chronological retrieval."""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.message import Message


class MessageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
        *,
        status: str = "completed",
        token_count: int | None = None,
    ) -> Message:
        message = Message(
            message_id=uuid4(), conversation_id=conversation_id, role=role,
            content=content, status=status, token_count=token_count,
        )
        self.db.add(message)
        self.db.flush()
        return message

    def get_messages(self, conversation_id: UUID, *, limit: int = 100, offset: int = 0) -> list[Message]:
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.message_id.asc())
            .limit(min(max(limit, 1), 500))
            .offset(max(offset, 0))
        )
        return list(self.db.scalars(statement))

    def count_messages(self, conversation_id: UUID) -> int:
        return int(self.db.scalar(
            select(func.count(Message.message_id)).where(Message.conversation_id == conversation_id)
        ) or 0)

    def get_latest_messages(self, conversation_id: UUID, limit: int) -> list[Message]:
        if limit <= 0:
            return []
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.status == "completed")
            .order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(limit)
        )
        return list(reversed(list(self.db.scalars(statement))))

    def delete_messages(self, conversation_id: UUID) -> int:
        messages = list(self.db.scalars(select(Message).where(Message.conversation_id == conversation_id)))
        count = len(messages)
        for message in messages:
            self.db.delete(message)
        self.db.flush()
        return count

    def update_message_status(self, message_id: UUID, status: str) -> Message | None:
        message = self.db.get(Message, message_id)
        if message is None:
            return None
        message.status = status
        self.db.flush()
        return message

    def get_last_completed_turn(self, conversation_id: UUID) -> tuple[Message, Message] | None:
        recent = list(self.db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.status == "completed")
            .order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(2)
        ))
        if len(recent) != 2:
            return None
        assistant, user = recent
        if assistant.role != "assistant" or user.role != "user":
            return None
        return assistant, user

    def delete_turn(self, assistant: Message, user: Message) -> None:
        self.db.delete(assistant)
        self.db.delete(user)
        self.db.flush()

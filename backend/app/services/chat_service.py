"""Persistent chat turn orchestration, isolated from HTTP route definitions."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.message import Message
from app.models.memory import MemoryExtractionJob
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.chat import ChatMessage
from app.services.conversation_service import ConversationNotFoundError


@dataclass(frozen=True)
class PreparedTurn:
    conversation_id: UUID
    user_message_id: UUID
    history: list[ChatMessage]


class ChatTurnInProgressError(RuntimeError):
    pass


def _conversation_title(message: str) -> str:
    compact = " ".join(message.split())
    return compact[:117] + "…" if len(compact) > 118 else compact or "New chat"


def prepare_turn(
    db: Session,
    user_id: UUID,
    conversation_id: UUID | None,
    text: str,
    *,
    regenerate: bool = False,
) -> PreparedTurn:
    """Load context and durably save the pending user message before generation."""
    conversations = ConversationRepository(db)
    messages = MessageRepository(db)
    try:
        conversation = conversations.get(user_id, conversation_id) if conversation_id else None
        if conversation_id is not None and conversation is None:
            raise ConversationNotFoundError
        if conversation is None:
            conversation = conversations.create(user_id)

        if regenerate:
            previous_turn = messages.get_last_completed_turn(conversation.conversation_id)
            if previous_turn is not None:
                previous_assistant, previous_user = previous_turn
                if previous_user.content == text:
                    messages.delete_turn(previous_assistant, previous_user)

        history_rows = messages.get_latest_messages(
            conversation.conversation_id, settings.chat_max_history_messages
        )
        history = [ChatMessage.model_validate(row) for row in history_rows]
        if conversation.last_message_at is None:
            conversations.update_title(conversation, _conversation_title(text))

        user_message = messages.save_message(
            conversation.conversation_id,
            "user",
            text,
            status="pending",
        )
        now = datetime.now(timezone.utc)
        previous_timestamp = db.scalar(
            select(Message.created_at)
            .where(Message.conversation_id == conversation.conversation_id, Message.message_id != user_message.message_id)
            .order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(1)
        )
        if previous_timestamp is not None:
            if previous_timestamp.tzinfo is None:
                previous_timestamp = previous_timestamp.replace(tzinfo=timezone.utc)
            user_message.created_at = max(now, previous_timestamp + timedelta(microseconds=1))
        conversations.update_last_message_at(conversation, now)
        db.commit()
        return PreparedTurn(
            conversation_id=conversation.conversation_id,
            user_message_id=user_message.message_id,
            history=history,
        )
    except Exception:
        db.rollback()
        raise


def complete_turn(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
    user_message_id: UUID,
    response_text: str,
) -> Message:
    """Mark the pending user message complete and persist the assistant response."""
    conversations = ConversationRepository(db)
    messages = MessageRepository(db)
    try:
        conversation = conversations.get(user_id, conversation_id)
        user_message = db.get(Message, user_message_id)
        if conversation is None or user_message is None or user_message.conversation_id != conversation_id:
            raise ConversationNotFoundError
        if user_message.role != "user" or user_message.status != "pending":
            raise RuntimeError("The chat turn is no longer pending.")
        messages.update_message_status(user_message_id, "completed")
        assistant = messages.save_message(conversation_id, "assistant", response_text, status="completed")
        assistant.created_at = max(
            datetime.now(timezone.utc),
            user_message.created_at + timedelta(microseconds=1),
        )
        conversations.update_last_message_at(conversation, datetime.now(timezone.utc))
        db.add(MemoryExtractionJob(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant.message_id,
            status="pending",
        ))
        db.commit()
        return assistant
    except Exception:
        db.rollback()
        raise


def fail_turn(db: Session, user_id: UUID, conversation_id: UUID, user_message_id: UUID) -> None:
    """Keep the user input durable and mark it failed when generation stops."""
    conversations = ConversationRepository(db)
    messages = MessageRepository(db)
    try:
        conversation = conversations.get(user_id, conversation_id)
        user_message = db.get(Message, user_message_id)
        if conversation is None or user_message is None or user_message.conversation_id != conversation_id:
            return
        if user_message.role == "user" and user_message.status == "pending":
            messages.update_message_status(user_message_id, "failed")
            conversations.update_last_message_at(conversation, datetime.now(timezone.utc))
        db.commit()
    except Exception:
        db.rollback()
        raise

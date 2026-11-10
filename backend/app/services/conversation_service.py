"""Conversation-level application logic above the SQLAlchemy repositories."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.message import Message
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.chat import ChatMessage, ConversationDetail, ConversationList, ConversationSummary, MessageList


class ConversationNotFoundError(LookupError):
    """The conversation does not exist for the current owner."""


def summary_schema(conversation: Conversation, message_count: int) -> ConversationSummary:
    return ConversationSummary(
        conversation_id=conversation.conversation_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at,
        is_archived=conversation.is_archived,
        message_count=message_count,
    )


def message_schema(message: Message) -> ChatMessage:
    return ChatMessage.model_validate(message)


def _owned_conversation(db: Session, user_id: UUID, conversation_id: UUID) -> Conversation:
    conversation = ConversationRepository(db).get(user_id, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError
    return conversation


def create_conversation(db: Session, user_id: UUID, title: str = "New chat") -> ConversationDetail:
    conversations = ConversationRepository(db)
    messages = MessageRepository(db)
    try:
        conversation = conversations.create(user_id, title)
        db.commit()
        return ConversationDetail(**summary_schema(conversation, 0).model_dump(), messages=[])
    except Exception:
        db.rollback()
        raise


def list_conversations(
    db: Session,
    user_id: UUID,
    *,
    archived: bool | None,
    limit: int,
    offset: int,
) -> ConversationList:
    repo = ConversationRepository(db)
    rows = repo.list_for_user(user_id, archived=archived, limit=limit, offset=offset)
    items = [summary_schema(conversation, count) for conversation, count in rows]
    return ConversationList(items=items, total=repo.count_for_user(user_id, archived), limit=min(max(limit, 1), 100), offset=max(offset, 0))


def get_conversation(db: Session, user_id: UUID, conversation_id: UUID) -> ConversationDetail:
    conversation = _owned_conversation(db, user_id, conversation_id)
    repo = MessageRepository(db)
    messages = repo.get_messages(conversation_id, limit=500)
    return ConversationDetail(
        **summary_schema(conversation, repo.count_messages(conversation_id)).model_dump(),
        messages=[message_schema(message) for message in messages],
    )


def get_messages(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
    *,
    limit: int,
    offset: int,
) -> MessageList:
    _owned_conversation(db, user_id, conversation_id)
    repo = MessageRepository(db)
    total = repo.count_messages(conversation_id)
    rows = repo.get_messages(conversation_id, limit=limit, offset=offset)
    return MessageList(items=[message_schema(row) for row in rows], total=total, limit=min(max(limit, 1), 500), offset=max(offset, 0))


def update_conversation(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
    *,
    title: str | None = None,
    is_archived: bool | None = None,
) -> ConversationSummary:
    conversations = ConversationRepository(db)
    try:
        conversation = _owned_conversation(db, user_id, conversation_id)
        if title is not None:
            conversations.update_title(conversation, title)
        if is_archived is not None:
            conversations.archive(conversation, is_archived)
        db.commit()
        count = MessageRepository(db).count_messages(conversation_id)
        return summary_schema(conversation, count)
    except Exception:
        db.rollback()
        raise


def clear_conversation(db: Session, user_id: UUID, conversation_id: UUID) -> ConversationDetail:
    conversations = ConversationRepository(db)
    messages = MessageRepository(db)
    try:
        conversation = _owned_conversation(db, user_id, conversation_id)
        messages.delete_messages(conversation_id)
        conversations.update_title(conversation, "New chat")
        conversation.last_message_at = None
        db.commit()
        return ConversationDetail(**summary_schema(conversation, 0).model_dump(), messages=[])
    except Exception:
        db.rollback()
        raise


def delete_conversation(db: Session, user_id: UUID, conversation_id: UUID) -> None:
    conversations = ConversationRepository(db)
    try:
        conversation = _owned_conversation(db, user_id, conversation_id)
        conversations.delete_conversation(conversation)
        db.commit()
    except Exception:
        db.rollback()
        raise

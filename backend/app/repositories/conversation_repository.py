"""Owner-scoped SQLAlchemy access to conversations."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.message import Message


class ConversationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: UUID, title: str = "New chat") -> Conversation:
        conversation = Conversation(conversation_id=uuid4(), user_id=user_id, title=title)
        self.db.add(conversation)
        self.db.flush()
        return conversation

    def get(self, user_id: UUID, conversation_id: UUID) -> Conversation | None:
        return self.db.scalar(select(Conversation).where(
            Conversation.conversation_id == conversation_id,
            Conversation.user_id == user_id,
        ))

    def list_for_user(
        self,
        user_id: UUID,
        *,
        archived: bool | None = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[tuple[Conversation, int]]:
        statement = (
            select(Conversation, func.count(Message.message_id))
            .outerjoin(Message, Message.conversation_id == Conversation.conversation_id)
            .where(Conversation.user_id == user_id)
            .group_by(Conversation.conversation_id)
        )
        if archived is not None:
            statement = statement.where(Conversation.is_archived.is_(archived))
        statement = statement.order_by(
            Conversation.last_message_at.desc().nullslast(),
            Conversation.updated_at.desc(),
            Conversation.conversation_id.desc(),
        ).limit(min(max(limit, 1), 100)).offset(max(offset, 0))
        return [(conversation, count) for conversation, count in self.db.execute(statement)]

    def count_for_user(self, user_id: UUID, archived: bool | None = False) -> int:
        statement = select(func.count(Conversation.conversation_id)).where(Conversation.user_id == user_id)
        if archived is not None:
            statement = statement.where(Conversation.is_archived.is_(archived))
        return int(self.db.scalar(statement) or 0)

    def update_title(self, conversation: Conversation, title: str) -> Conversation:
        conversation.title = title
        self.db.flush()
        return conversation

    def update_last_message_at(self, conversation: Conversation, timestamp: datetime) -> None:
        conversation.last_message_at = timestamp
        conversation.updated_at = timestamp
        self.db.flush()

    def archive(self, conversation: Conversation, archived: bool) -> Conversation:
        conversation.is_archived = archived
        self.db.flush()
        return conversation

    def delete_conversation(self, conversation: Conversation) -> None:
        self.db.delete(conversation)

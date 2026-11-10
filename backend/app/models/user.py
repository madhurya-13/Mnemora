"""Guest and future authenticated user identity."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.database.base import Base, UTCDateTime


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("guest_session_hash", name="uq_users_guest_session_hash"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(80), nullable=False, default="Guest")
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True)
    guest_session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

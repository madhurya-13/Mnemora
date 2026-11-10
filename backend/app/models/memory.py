"""Long-term memory metadata and durable background operation records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.database.base import Base, UTCDateTime


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint("importance >= 0 AND importance <= 1", name="ck_memories_importance"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memories_confidence"),
        CheckConstraint("approval_status IN ('pending', 'approved', 'rejected')", name="ck_memories_approval_status"),
        CheckConstraint("memory_type IN ('stable', 'temporary')", name="ck_memories_type"),
        CheckConstraint("vector_sync_status IN ('not_required', 'pending', 'synced', 'failed')", name="ck_memories_vector_sync"),
        Index("ix_memories_user_approval", "user_id", "approval_status"),
        Index("ix_memories_user_category", "user_id", "category"),
        Index("ix_memories_updated", "user_id", "updated_at"),
    )

    memory_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    importance: Mapped[float] = mapped_column(nullable=False, default=0.7)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.8)
    memory_type: Mapped[str] = mapped_column(String(16), nullable=False, default="stable")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="user")
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.conversation_id", ondelete="SET NULL"), nullable=True
    )
    source_message_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    similar_memory_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    vector_sync_status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_required")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class MemoryVectorOutbox(Base):
    """Durable vector-index work; relational metadata remains the source of truth."""

    __tablename__ = "memory_vector_outbox"
    __table_args__ = (Index("ix_memory_vector_outbox_created", "created_at"),)

    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))


class MemoryExtractionJob(Base):
    """Persistent post-response extraction work with bounded automatic retries."""

    __tablename__ = "memory_extraction_jobs"
    __table_args__ = (
        UniqueConstraint("assistant_message_id", name="uq_memory_extraction_assistant_message"),
        CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="ck_memory_jobs_status"),
        Index("ix_memory_jobs_status_created", "status", "created_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.conversation_id", ondelete="SET NULL"), nullable=True
    )
    user_message_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assistant_message_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class MemoryHistory(Base):
    __tablename__ = "memory_history"
    __table_args__ = (Index("ix_memory_history_owner_created", "user_id", "memory_id", "created_at"),)

    history_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("memories.memory_id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    importance: Mapped[float] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    memory_type: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False)
    change_reason: Mapped[str] = mapped_column(String(80), nullable=False, default="user_update")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))


class MemoryConflict(Base):
    __tablename__ = "memory_conflicts"
    __table_args__ = (
        CheckConstraint("status IN ('unresolved', 'resolved_kept', 'resolved_updated')", name="ck_memory_conflict_status"),
        Index("ix_memory_conflicts_owner_status", "user_id", "status", "created_at"),
    )

    conflict_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    existing_memory_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("memories.memory_id", ondelete="CASCADE"), nullable=False)
    new_memory_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("memories.memory_id", ondelete="CASCADE"), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unresolved")
    summary: Mapped[str] = mapped_column(String(240), nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class MemoryRetrievalEvent(Base):
    __tablename__ = "memory_retrieval_events"
    __table_args__ = (Index("ix_memory_retrieval_owner_created", "user_id", "created_at"),)

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    intent: Mapped[str] = mapped_column(String(60), nullable=False)
    query_type: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))


class MemoryRetrievalItem(Base):
    __tablename__ = "memory_retrieval_items"
    __table_args__ = (
        UniqueConstraint("event_id", "memory_id", name="uq_memory_retrieval_item"),
        Index("ix_memory_retrieval_item_memory", "memory_id", "selected"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("memory_retrieval_events.event_id", ondelete="CASCADE"), nullable=False)
    memory_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("memories.memory_id", ondelete="CASCADE"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    semantic_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    keyword_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    recency_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    category_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    usage_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)

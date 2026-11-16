"""Adaptive-learning records: preferences, patterns, feedback and processing jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.database.base import Base, UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AdaptiveSettings(Base):
    """Per-user controls for learning, personalization and review requirements."""

    __tablename__ = "adaptive_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_adaptive_settings_user"),
        CheckConstraint(
            "preference_confidence_threshold >= 0 AND preference_confidence_threshold <= 1",
            name="ck_adaptive_confidence_threshold",
        ),
        CheckConstraint("preference_evidence_threshold >= 2", name="ck_adaptive_evidence_threshold"),
        CheckConstraint("pattern_evidence_threshold >= 2", name="ck_adaptive_pattern_threshold"),
    )

    settings_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    preference_learning_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_candidate_generation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pattern_detection_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    personalization_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    memory_decay_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_user_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preference_confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    preference_evidence_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    pattern_evidence_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class UserPreference(Base):
    """A preference candidate supported by repeated, inspectable evidence."""

    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_key", name="uq_user_preference_key"),
        CheckConstraint(
            "status IN ('candidate', 'confirmed', 'rejected', 'disabled')",
            name="ck_user_preference_status",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_user_preference_confidence"),
        Index("ix_user_preferences_owner_status", "user_id", "status", "last_observed_at"),
    )

    preference_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(160), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supporting_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class MemoryPattern(Base):
    """A recurring topic or workflow supported by multiple distinct conversations."""

    __tablename__ = "memory_patterns"
    __table_args__ = (
        UniqueConstraint("user_id", "pattern_type", "normalized_key", name="uq_memory_pattern_key"),
        CheckConstraint(
            "status IN ('candidate', 'confirmed', 'dismissed')",
            name="ck_memory_pattern_status",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_pattern_confidence"),
        Index("ix_memory_patterns_owner_status", "user_id", "status", "last_observed_at"),
    )

    pattern_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    pattern_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    supporting_conversation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    supporting_message_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class MemoryFeedback(Base):
    """Immutable user feedback linked to a response, memory or preference."""

    __tablename__ = "memory_feedback"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "target_type", "target_id", "feedback_type",
            name="uq_memory_feedback_event",
        ),
        CheckConstraint(
            "target_type IN ('response', 'memory', 'preference')",
            name="ck_memory_feedback_target",
        ),
        Index("ix_memory_feedback_owner_created", "user_id", "created_at"),
        Index("ix_memory_feedback_target", "target_type", "target_id"),
    )

    feedback_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(40), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    preference_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.conversation_id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)


class AdaptiveProcessingJob(Base):
    """Durable, idempotent post-chat adaptive evaluation work."""

    __tablename__ = "adaptive_processing_jobs"
    __table_args__ = (
        UniqueConstraint("assistant_message_id", name="uq_adaptive_job_assistant_message"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_adaptive_jobs_status",
        ),
        Index("ix_adaptive_jobs_status_created", "status", "created_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.conversation_id", ondelete="SET NULL"), nullable=True
    )
    user_message_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assistant_message_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )

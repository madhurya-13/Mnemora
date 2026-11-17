"""Persistent, user-scoped knowledge graph built on the relational database.

The graph is an enrichment layer: ``memories`` remains the authoritative record of
user information and every graph fact keeps references back to its evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.database.base import Base, UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GraphEntity(Base):
    """A named entity that belongs to exactly one user."""

    __tablename__ = "graph_entities"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "normalized_name", name="uq_graph_entity_identity"),
        CheckConstraint(
            "status IN ('active', 'pending_review', 'archived', 'merged')",
            name="ck_graph_entity_status",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_graph_entity_confidence"),
        Index("ix_graph_entities_owner_type", "user_id", "entity_type", "status"),
        Index("ix_graph_entities_owner_updated", "user_id", "updated_at"),
        Index("ix_graph_entities_owner_name", "user_id", "normalized_name"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    source_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending_review")
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class GraphRelationship(Base):
    """A directed, temporally bounded edge between two entities of one user."""

    __tablename__ = "graph_relationships"
    __table_args__ = (
        CheckConstraint("source_entity_id <> target_entity_id", name="ck_graph_relationship_distinct"),
        CheckConstraint(
            "status IN ('active', 'pending_review', 'historical', 'rejected', 'archived')",
            name="ck_graph_relationship_status",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_graph_relationship_confidence"),
        Index("ix_graph_relationships_owner_source", "user_id", "source_entity_id", "status"),
        Index("ix_graph_relationships_owner_target", "user_id", "target_entity_id", "status"),
        Index("ix_graph_relationships_owner_type", "user_id", "relationship_type", "status"),
        Index("ix_graph_relationships_owner_updated", "user_id", "updated_at"),
    )

    relationship_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    evidence_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_review")
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class GraphHistory(Base):
    """Immutable audit trail for every graph mutation, including rebuilds."""

    __tablename__ = "graph_history"
    __table_args__ = (
        Index("ix_graph_history_owner_created", "user_id", "created_at"),
        Index("ix_graph_history_entity", "entity_id", "created_at"),
        Index("ix_graph_history_relationship", "relationship_id", "created_at"),
    )

    history_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    relationship_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)


class GraphMergeRecord(Base):
    """Snapshot of a user-assisted entity merge so it can be undone."""

    __tablename__ = "graph_merge_records"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'undone')", name="ck_graph_merge_status"),
        Index("ix_graph_merges_owner_created", "user_id", "created_at"),
    )

    merge_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    primary_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    merged_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    performed_by: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    undone_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class GraphSyncRecord(Base):
    """Durable, idempotent unit of graph construction work."""

    __tablename__ = "graph_sync_records"
    __table_args__ = (
        UniqueConstraint("user_id", "source_type", "source_id", name="uq_graph_sync_source"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_graph_sync_status",
        ),
        Index("ix_graph_sync_status_created", "status", "created_at"),
        Index("ix_graph_sync_owner_created", "user_id", "created_at"),
    )

    sync_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )

"""Add retrieval audit, conflict workflow and memory history."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_retrieval_intelligence"
down_revision: Union[str, None] = "0002_long_term_memories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_history",
        sa.Column("history_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("memory_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("memory_type", sa.String(16), nullable=False),
        sa.Column("approval_status", sa.String(16), nullable=False),
        sa.Column("change_reason", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.memory_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("history_id"),
    )
    op.create_index("ix_memory_history_owner_created", "memory_history", ["user_id", "memory_id", "created_at"])

    op.create_table(
        "memory_conflicts",
        sa.Column("conflict_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("existing_memory_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("new_memory_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("conflict_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("summary", sa.String(240), nullable=False),
        sa.Column("resolution", sa.String(24), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('unresolved', 'resolved_kept', 'resolved_updated')", name="ck_memory_conflict_status"),
        sa.ForeignKeyConstraint(["existing_memory_id"], ["memories.memory_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["new_memory_id"], ["memories.memory_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conflict_id"),
    )
    op.create_index("ix_memory_conflicts_owner_status", "memory_conflicts", ["user_id", "status", "created_at"])

    op.create_table(
        "memory_retrieval_events",
        sa.Column("event_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("intent", sa.String(60), nullable=False),
        sa.Column("query_type", sa.String(32), nullable=False),
        sa.Column("category", sa.String(40), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_memory_retrieval_owner_created", "memory_retrieval_events", ["user_id", "created_at"])

    op.create_table(
        "memory_retrieval_items",
        sa.Column("item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("memory_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        *[sa.Column(name, sa.Float(), nullable=False) for name in (
            "semantic_score", "keyword_score", "importance_score", "confidence_score",
            "recency_score", "category_score", "usage_score", "final_score",
        )],
        sa.ForeignKeyConstraint(["event_id"], ["memory_retrieval_events.event_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.memory_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id"),
        sa.UniqueConstraint("event_id", "memory_id", name="uq_memory_retrieval_item"),
    )
    op.create_index("ix_memory_retrieval_item_memory", "memory_retrieval_items", ["memory_id", "selected"])


def downgrade() -> None:
    op.drop_index("ix_memory_retrieval_item_memory", table_name="memory_retrieval_items")
    op.drop_table("memory_retrieval_items")
    op.drop_index("ix_memory_retrieval_owner_created", table_name="memory_retrieval_events")
    op.drop_table("memory_retrieval_events")
    op.drop_index("ix_memory_conflicts_owner_status", table_name="memory_conflicts")
    op.drop_table("memory_conflicts")
    op.drop_index("ix_memory_history_owner_created", table_name="memory_history")
    op.drop_table("memory_history")

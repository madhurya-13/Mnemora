"""Add relational memories and durable vector/extraction work queues."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_long_term_memories"
down_revision: Union[str, None] = "0001_persistent_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("memory_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("memory_type", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_conversation_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source_message_ids", sa.JSON(), nullable=False),
        sa.Column("approval_status", sa.String(length=16), nullable=False),
        sa.Column("similar_memory_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("vector_sync_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("importance >= 0 AND importance <= 1", name="ck_memories_importance"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memories_confidence"),
        sa.CheckConstraint("approval_status IN ('pending', 'approved', 'rejected')", name="ck_memories_approval_status"),
        sa.CheckConstraint("memory_type IN ('stable', 'temporary')", name="ck_memories_type"),
        sa.CheckConstraint("vector_sync_status IN ('not_required', 'pending', 'synced', 'failed')", name="ck_memories_vector_sync"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_conversation_id"], ["conversations.conversation_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("memory_id"),
    )
    op.create_index("ix_memories_user_approval", "memories", ["user_id", "approval_status"], unique=False)
    op.create_index("ix_memories_user_category", "memories", ["user_id", "category"], unique=False)
    op.create_index("ix_memories_updated", "memories", ["user_id", "updated_at"], unique=False)

    op.create_table(
        "memory_vector_outbox",
        sa.Column("operation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("memory_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index("ix_memory_vector_outbox_created", "memory_vector_outbox", ["created_at"], unique=False)

    op.create_table(
        "memory_extraction_jobs",
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("user_message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="ck_memory_jobs_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("assistant_message_id", name="uq_memory_extraction_assistant_message"),
    )
    op.create_index("ix_memory_jobs_status_created", "memory_extraction_jobs", ["status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_memory_jobs_status_created", table_name="memory_extraction_jobs")
    op.drop_table("memory_extraction_jobs")
    op.drop_index("ix_memory_vector_outbox_created", table_name="memory_vector_outbox")
    op.drop_table("memory_vector_outbox")
    op.drop_index("ix_memories_updated", table_name="memories")
    op.drop_index("ix_memories_user_category", table_name="memories")
    op.drop_index("ix_memories_user_approval", table_name="memories")
    op.drop_table("memories")

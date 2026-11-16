"""Add adaptive preferences, patterns, feedback, jobs and memory lifecycle."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_adaptive_memory"
down_revision: Union[str, None] = "0003_retrieval_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("lifecycle_status", sa.String(24), nullable=False, server_default="active"),
    )
    op.add_column(
        "memories",
        sa.Column("utility_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column("memories", sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memories", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memories", sa.Column("superseded_by", sa.Uuid(as_uuid=True), nullable=True))

    op.add_column(
        "memory_history",
        sa.Column("change_type", sa.String(40), nullable=False, server_default="user_update"),
    )
    op.add_column("memory_history", sa.Column("source_conversation_id", sa.Uuid(as_uuid=True), nullable=True))

    op.create_table(
        "adaptive_settings",
        sa.Column("settings_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("preference_learning_enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_candidate_generation", sa.Boolean(), nullable=False),
        sa.Column("pattern_detection_enabled", sa.Boolean(), nullable=False),
        sa.Column("personalization_enabled", sa.Boolean(), nullable=False),
        sa.Column("memory_decay_enabled", sa.Boolean(), nullable=False),
        sa.Column("require_user_review", sa.Boolean(), nullable=False),
        sa.Column("preference_confidence_threshold", sa.Float(), nullable=False),
        sa.Column("preference_evidence_threshold", sa.Integer(), nullable=False),
        sa.Column("pattern_evidence_threshold", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "preference_confidence_threshold >= 0 AND preference_confidence_threshold <= 1",
            name="ck_adaptive_confidence_threshold",
        ),
        sa.CheckConstraint("preference_evidence_threshold >= 2", name="ck_adaptive_evidence_threshold"),
        sa.CheckConstraint("pattern_evidence_threshold >= 2", name="ck_adaptive_pattern_threshold"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("settings_id"),
        sa.UniqueConstraint("user_id", name="uq_adaptive_settings_user"),
    )

    op.create_table(
        "user_preferences",
        sa.Column("preference_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("normalized_key", sa.String(160), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("supporting_memory_ids", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('candidate', 'confirmed', 'rejected', 'disabled')",
            name="ck_user_preference_status",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_user_preference_confidence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("preference_id"),
        sa.UniqueConstraint("user_id", "normalized_key", name="uq_user_preference_key"),
    )
    op.create_index(
        "ix_user_preferences_owner_status", "user_preferences",
        ["user_id", "status", "last_observed_at"],
    )

    op.create_table(
        "memory_patterns",
        sa.Column("pattern_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("pattern_type", sa.String(40), nullable=False),
        sa.Column("description", sa.String(400), nullable=False),
        sa.Column("normalized_key", sa.String(160), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("supporting_conversation_ids", sa.JSON(), nullable=False),
        sa.Column("supporting_message_ids", sa.JSON(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('candidate', 'confirmed', 'dismissed')",
            name="ck_memory_pattern_status",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_pattern_confidence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("pattern_id"),
        sa.UniqueConstraint("user_id", "pattern_type", "normalized_key", name="uq_memory_pattern_key"),
    )
    op.create_index(
        "ix_memory_patterns_owner_status", "memory_patterns",
        ["user_id", "status", "last_observed_at"],
    )

    op.create_table(
        "memory_feedback",
        sa.Column("feedback_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("feedback_type", sa.String(40), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("memory_ids", sa.JSON(), nullable=False),
        sa.Column("preference_ids", sa.JSON(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("message_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('response', 'memory', 'preference')",
            name="ck_memory_feedback_target",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("feedback_id"),
        sa.UniqueConstraint(
            "user_id", "target_type", "target_id", "feedback_type",
            name="uq_memory_feedback_event",
        ),
    )
    op.create_index("ix_memory_feedback_owner_created", "memory_feedback", ["user_id", "created_at"])
    op.create_index("ix_memory_feedback_target", "memory_feedback", ["target_type", "target_id"])

    op.create_table(
        "adaptive_processing_jobs",
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("user_message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_adaptive_jobs_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("assistant_message_id", name="uq_adaptive_job_assistant_message"),
    )
    op.create_index("ix_adaptive_jobs_status_created", "adaptive_processing_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_adaptive_jobs_status_created", table_name="adaptive_processing_jobs")
    op.drop_table("adaptive_processing_jobs")
    op.drop_index("ix_memory_feedback_target", table_name="memory_feedback")
    op.drop_index("ix_memory_feedback_owner_created", table_name="memory_feedback")
    op.drop_table("memory_feedback")
    op.drop_index("ix_memory_patterns_owner_status", table_name="memory_patterns")
    op.drop_table("memory_patterns")
    op.drop_index("ix_user_preferences_owner_status", table_name="user_preferences")
    op.drop_table("user_preferences")
    op.drop_table("adaptive_settings")

    with op.batch_alter_table("memory_history") as batch:
        batch.drop_column("source_conversation_id")
        batch.drop_column("change_type")
    with op.batch_alter_table("memories") as batch:
        batch.drop_column("superseded_by")
        batch.drop_column("archived_at")
        batch.drop_column("last_evaluated_at")
        batch.drop_column("utility_score")
        batch.drop_column("lifecycle_status")

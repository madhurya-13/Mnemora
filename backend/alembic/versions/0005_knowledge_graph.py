"""Add the user-scoped knowledge graph: entities, relationships, audit and jobs.

This revision is additive only. Existing conversations, messages, memories,
preferences and retrieval tables are untouched.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_knowledge_graph"
down_revision: Union[str, None] = "0004_adaptive_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_entities",
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("entity_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_memory_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("merged_into_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'pending_review', 'archived', 'merged')",
            name="ck_graph_entity_status",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_graph_entity_confidence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint("user_id", "entity_type", "normalized_name", name="uq_graph_entity_identity"),
    )
    op.create_index(
        "ix_graph_entities_owner_type", "graph_entities", ["user_id", "entity_type", "status"], unique=False
    )
    op.create_index("ix_graph_entities_owner_updated", "graph_entities", ["user_id", "updated_at"], unique=False)
    op.create_index("ix_graph_entities_owner_name", "graph_entities", ["user_id", "normalized_name"], unique=False)

    op.create_table(
        "graph_relationships",
        sa.Column("relationship_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_memory_ids", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("superseded_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_entity_id <> target_entity_id", name="ck_graph_relationship_distinct"),
        sa.CheckConstraint(
            "status IN ('active', 'pending_review', 'historical', 'rejected', 'archived')",
            name="ck_graph_relationship_status",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_graph_relationship_confidence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_entity_id"], ["graph_entities.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_entity_id"], ["graph_entities.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("relationship_id"),
    )
    op.create_index(
        "ix_graph_relationships_owner_source",
        "graph_relationships",
        ["user_id", "source_entity_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_graph_relationships_owner_target",
        "graph_relationships",
        ["user_id", "target_entity_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_graph_relationships_owner_type",
        "graph_relationships",
        ["user_id", "relationship_type", "status"],
        unique=False,
    )
    op.create_index(
        "ix_graph_relationships_owner_updated", "graph_relationships", ["user_id", "updated_at"], unique=False
    )

    op.create_table(
        "graph_history",
        sa.Column("history_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("relationship_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("actor", sa.String(length=20), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("history_id"),
    )
    op.create_index("ix_graph_history_owner_created", "graph_history", ["user_id", "created_at"], unique=False)
    op.create_index("ix_graph_history_entity", "graph_history", ["entity_id", "created_at"], unique=False)
    op.create_index(
        "ix_graph_history_relationship", "graph_history", ["relationship_id", "created_at"], unique=False
    )

    op.create_table(
        "graph_merge_records",
        sa.Column("merge_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("primary_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("merged_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("performed_by", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'undone')", name="ck_graph_merge_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("merge_id"),
    )
    op.create_index("ix_graph_merges_owner_created", "graph_merge_records", ["user_id", "created_at"], unique=False)

    op.create_table(
        "graph_sync_records",
        sa.Column("sync_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_graph_sync_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("sync_id"),
        sa.UniqueConstraint("user_id", "source_type", "source_id", name="uq_graph_sync_source"),
    )
    op.create_index("ix_graph_sync_status_created", "graph_sync_records", ["status", "created_at"], unique=False)
    op.create_index("ix_graph_sync_owner_created", "graph_sync_records", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_graph_sync_owner_created", table_name="graph_sync_records")
    op.drop_index("ix_graph_sync_status_created", table_name="graph_sync_records")
    op.drop_table("graph_sync_records")
    op.drop_index("ix_graph_merges_owner_created", table_name="graph_merge_records")
    op.drop_table("graph_merge_records")
    op.drop_index("ix_graph_history_relationship", table_name="graph_history")
    op.drop_index("ix_graph_history_entity", table_name="graph_history")
    op.drop_index("ix_graph_history_owner_created", table_name="graph_history")
    op.drop_table("graph_history")
    op.drop_index("ix_graph_relationships_owner_updated", table_name="graph_relationships")
    op.drop_index("ix_graph_relationships_owner_type", table_name="graph_relationships")
    op.drop_index("ix_graph_relationships_owner_target", table_name="graph_relationships")
    op.drop_index("ix_graph_relationships_owner_source", table_name="graph_relationships")
    op.drop_table("graph_relationships")
    op.drop_index("ix_graph_entities_owner_name", table_name="graph_entities")
    op.drop_index("ix_graph_entities_owner_updated", table_name="graph_entities")
    op.drop_index("ix_graph_entities_owner_type", table_name="graph_entities")
    op.drop_table("graph_entities")

"""Add agentic automation: plans, tasks, executions, approvals and workflows.

Additive migration. Existing conversations, messages, memories, adaptive
tables and knowledge-graph tables are untouched.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_agentic_automation"
down_revision: Union[str, None] = "0005_knowledge_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _status_check(name: str, column: str, values: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({values})", name=name)


def upgrade() -> None:
    op.create_table(
        "agent_plans",
        sa.Column("plan_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("estimated_complexity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("clarifications", sa.JSON(), nullable=False),
        sa.Column("clarification_answers", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _status_check(
            "ck_agent_plan_status",
            "status",
            "'draft', 'needs_clarification', 'approved', 'running', 'completed', "
            "'partially_completed', 'failed', 'cancelled', 'archived'",
        ),
        _status_check("ck_agent_plan_priority", "priority", "'low', 'normal', 'high', 'urgent'"),
        _status_check(
            "ck_agent_plan_complexity", "estimated_complexity", "'low', 'moderate', 'high'"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_index("ix_agent_plans_owner_updated", "agent_plans", ["user_id", "updated_at"], unique=False)
    op.create_index("ix_agent_plans_owner_status", "agent_plans", ["user_id", "status"], unique=False)

    op.create_table(
        "agent_tasks",
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("plan_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("assigned_tool", sa.String(length=60), nullable=True),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("expected_output", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("approval_policy", sa.String(length=20), nullable=False),
        sa.Column("execution_attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("verification_status", sa.String(length=24), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _status_check(
            "ck_agent_task_status",
            "status",
            "'pending', 'ready', 'awaiting_approval', 'running', 'completed', "
            "'failed', 'skipped', 'cancelled'",
        ),
        _status_check(
            "ck_agent_task_verification",
            "verification_status",
            "'pending', 'verified', 'partially_verified', 'failed', 'not_verifiable'",
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["agent_plans.plan_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
        sa.UniqueConstraint("plan_id", "sequence", name="uq_agent_task_sequence"),
    )
    op.create_index("ix_agent_tasks_plan_sequence", "agent_tasks", ["plan_id", "sequence"], unique=False)
    op.create_index("ix_agent_tasks_owner_status", "agent_tasks", ["user_id", "status"], unique=False)

    op.create_table(
        "agent_executions",
        sa.Column("execution_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("plan_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_task_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("learning", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("pause_requested", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _status_check(
            "ck_agent_execution_status",
            "status",
            "'created', 'planning', 'awaiting_approval', 'executing', 'paused', "
            "'completed', 'partially_completed', 'failed', 'cancelled'",
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["agent_plans.plan_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("execution_id"),
    )
    op.create_index(
        "ix_agent_executions_owner_created", "agent_executions", ["user_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_agent_executions_owner_status", "agent_executions", ["user_id", "status"], unique=False
    )
    op.create_index("ix_agent_executions_plan", "agent_executions", ["plan_id", "created_at"], unique=False)

    op.create_table(
        "tool_invocations",
        sa.Column("invocation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("execution_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("tool_name", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _status_check(
            "ck_tool_invocation_status",
            "status",
            "'success', 'failed', 'timeout', 'rejected', 'denied'",
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.execution_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("invocation_id"),
    )
    op.create_index(
        "ix_tool_invocations_execution", "tool_invocations", ["execution_id", "created_at"], unique=False
    )
    op.create_index("ix_tool_invocations_task", "tool_invocations", ["task_id"], unique=False)
    op.create_index(
        "ix_tool_invocations_owner_tool", "tool_invocations", ["user_id", "tool_name"], unique=False
    )

    op.create_table(
        "agent_approvals",
        sa.Column("approval_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("execution_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(length=60), nullable=False),
        sa.Column("action_summary", sa.String(length=500), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("expected_impact", sa.String(length=500), nullable=False),
        sa.Column("data_involved", sa.JSON(), nullable=False),
        sa.Column("reversible", sa.Boolean(), nullable=False),
        sa.Column("parameters_hash", sa.String(length=64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _status_check(
            "ck_agent_approval_status",
            "status",
            "'pending', 'approved', 'rejected', 'expired', 'consumed'",
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.execution_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index(
        "ix_agent_approvals_owner_status",
        "agent_approvals",
        ["user_id", "status", "created_at"],
        unique=False,
    )
    op.create_index("ix_agent_approvals_execution", "agent_approvals", ["execution_id"], unique=False)

    op.create_table(
        "execution_events",
        sa.Column("event_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("execution_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.execution_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("execution_id", "sequence", name="uq_execution_event_sequence"),
    )
    op.create_index(
        "ix_execution_events_execution", "execution_events", ["execution_id", "sequence"], unique=False
    )
    op.create_index(
        "ix_execution_events_owner_created", "execution_events", ["user_id", "created_at"], unique=False
    )

    op.create_table(
        "task_verifications",
        sa.Column("verification_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("execution_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("verification_type", sa.String(length=40), nullable=False),
        sa.Column("expected_result", sa.String(length=500), nullable=False),
        sa.Column("observed_result", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        _status_check(
            "ck_task_verification_status",
            "status",
            "'verified', 'partially_verified', 'failed', 'not_verifiable'",
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.execution_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("verification_id"),
    )
    op.create_index(
        "ix_task_verifications_execution", "task_verifications", ["execution_id", "verified_at"], unique=False
    )
    op.create_index("ix_task_verifications_task", "task_verifications", ["task_id"], unique=False)

    op.create_table(
        "workflow_templates",
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("objective_template", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _status_check("ck_workflow_template_status", "status", "'suggested', 'active', 'archived'"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workflow_id"),
        sa.UniqueConstraint("user_id", "name", name="uq_workflow_template_name"),
    )
    op.create_index(
        "ix_workflow_templates_owner_status", "workflow_templates", ["user_id", "status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_templates_owner_status", table_name="workflow_templates")
    op.drop_table("workflow_templates")
    op.drop_index("ix_task_verifications_task", table_name="task_verifications")
    op.drop_index("ix_task_verifications_execution", table_name="task_verifications")
    op.drop_table("task_verifications")
    op.drop_index("ix_execution_events_owner_created", table_name="execution_events")
    op.drop_index("ix_execution_events_execution", table_name="execution_events")
    op.drop_table("execution_events")
    op.drop_index("ix_agent_approvals_execution", table_name="agent_approvals")
    op.drop_index("ix_agent_approvals_owner_status", table_name="agent_approvals")
    op.drop_table("agent_approvals")
    op.drop_index("ix_tool_invocations_owner_tool", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_task", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_execution", table_name="tool_invocations")
    op.drop_table("tool_invocations")
    op.drop_index("ix_agent_executions_plan", table_name="agent_executions")
    op.drop_index("ix_agent_executions_owner_status", table_name="agent_executions")
    op.drop_index("ix_agent_executions_owner_created", table_name="agent_executions")
    op.drop_table("agent_executions")
    op.drop_index("ix_agent_tasks_owner_status", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_plan_sequence", table_name="agent_tasks")
    op.drop_table("agent_tasks")
    op.drop_index("ix_agent_plans_owner_status", table_name="agent_plans")
    op.drop_index("ix_agent_plans_owner_updated", table_name="agent_plans")
    op.drop_table("agent_plans")

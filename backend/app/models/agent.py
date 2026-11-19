"""Persistent agent plans, tasks, executions, approvals and workflow templates.

Agent state is stored relationally so an application restart never erases an
execution. Plans reference memories only through evidence identifiers; the
memory system remains authoritative and approvals stay user-controlled.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
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


PLAN_STATUSES = (
    "draft",
    "needs_clarification",
    "approved",
    "running",
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
    "archived",
)
TASK_STATUSES = (
    "pending",
    "ready",
    "awaiting_approval",
    "running",
    "completed",
    "failed",
    "skipped",
    "cancelled",
)
EXECUTION_STATUSES = (
    "created",
    "planning",
    "awaiting_approval",
    "executing",
    "paused",
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
)
APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired", "consumed")
INVOCATION_STATUSES = ("success", "failed", "timeout", "rejected", "denied")
VERIFICATION_STATUSES = ("verified", "partially_verified", "failed", "not_verifiable")
WORKFLOW_STATUSES = ("suggested", "active", "archived")


def _in_check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    rendered = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({rendered})", name=name)


class AgentPlan(Base):
    """A structured, user-owned execution plan."""

    __tablename__ = "agent_plans"
    __table_args__ = (
        _in_check("status", PLAN_STATUSES, "ck_agent_plan_status"),
        _in_check("priority", ("low", "normal", "high", "urgent"), "ck_agent_plan_priority"),
        _in_check("estimated_complexity", ("low", "moderate", "high"), "ck_agent_plan_complexity"),
        Index("ix_agent_plans_owner_updated", "user_id", "updated_at"),
        Index("ix_agent_plans_owner_status", "user_id", "status"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intent: Mapped[str] = mapped_column(String(40), nullable=False, default="generic")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    estimated_complexity: Mapped[str] = mapped_column(String(16), nullable=False, default="moderate")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    clarifications: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    clarification_answers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AgentTask(Base):
    """One step of a plan with explicit dependencies and expected output."""

    __tablename__ = "agent_tasks"
    __table_args__ = (
        _in_check("status", TASK_STATUSES, "ck_agent_task_status"),
        _in_check(
            "verification_status",
            (*VERIFICATION_STATUSES, "pending"),
            "ck_agent_task_verification",
        ),
        UniqueConstraint("plan_id", "sequence", name="uq_agent_task_sequence"),
        Index("ix_agent_tasks_plan_sequence", "plan_id", "sequence"),
        Index("ix_agent_tasks_owner_status", "user_id", "status"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_plans.plan_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    assigned_tool: Mapped[str | None] = mapped_column(String(60), nullable=True)
    dependencies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    input: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected_output: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    execution_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AgentExecution(Base):
    """Persistent run state for one plan."""

    __tablename__ = "agent_executions"
    __table_args__ = (
        _in_check("status", EXECUTION_STATUSES, "ck_agent_execution_status"),
        Index("ix_agent_executions_owner_created", "user_id", "created_at"),
        Index("ix_agent_executions_owner_status", "user_id", "status"),
        Index("ix_agent_executions_plan", "plan_id", "created_at"),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_plans.plan_id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="created")
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    learning: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pause_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class ToolInvocation(Base):
    """Every tool call, its redacted arguments and its bounded outcome."""

    __tablename__ = "tool_invocations"
    __table_args__ = (
        _in_check("status", INVOCATION_STATUSES, "ck_tool_invocation_status"),
        Index("ix_tool_invocations_execution", "execution_id", "created_at"),
        Index("ix_tool_invocations_task", "task_id"),
        Index("ix_tool_invocations_owner_tool", "user_id", "tool_name"),
    )

    invocation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_executions.execution_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_tasks.task_id", ondelete="CASCADE"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)


class AgentApproval(Base):
    """A single-use approval request bound to exact task parameters."""

    __tablename__ = "agent_approvals"
    __table_args__ = (
        _in_check("status", APPROVAL_STATUSES, "ck_agent_approval_status"),
        Index("ix_agent_approvals_owner_status", "user_id", "status", "created_at"),
        Index("ix_agent_approvals_execution", "execution_id"),
    )

    approval_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_executions.execution_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    action_summary: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    expected_impact: Mapped[str] = mapped_column(String(500), nullable=False)
    data_involved: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    parameters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)


class ExecutionEvent(Base):
    """Append-only execution timeline used by the monitoring UI."""

    __tablename__ = "execution_events"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence", name="uq_execution_event_sequence"),
        Index("ix_execution_events_execution", "execution_id", "sequence"),
        Index("ix_execution_events_owner_created", "user_id", "created_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_executions.execution_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)


class TaskVerification(Base):
    """Outcome of checking that a task produced its expected output."""

    __tablename__ = "task_verifications"
    __table_args__ = (
        _in_check("status", VERIFICATION_STATUSES, "ck_task_verification_status"),
        Index("ix_task_verifications_execution", "execution_id", "verified_at"),
        Index("ix_task_verifications_task", "task_id"),
    )

    verification_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_executions.execution_id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    verification_type: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_result: Mapped[str] = mapped_column(String(500), nullable=False)
    observed_result: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    verified_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)


class WorkflowTemplate(Base):
    """A reusable, validated sequence of task definitions."""

    __tablename__ = "workflow_templates"
    __table_args__ = (
        _in_check("status", WORKFLOW_STATUSES, "ck_workflow_template_status"),
        UniqueConstraint("user_id", "name", name="uq_workflow_template_name"),
        Index("ix_workflow_templates_owner_status", "user_id", "status"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    objective_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intent: Mapped[str] = mapped_column(String(40), nullable=False, default="generic")
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utcnow, onupdate=_utcnow
    )

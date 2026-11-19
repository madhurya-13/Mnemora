"""Validated request and response models for the agent control center API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TaskType = Literal[
    "retrieve_memory",
    "retrieve_preferences",
    "retrieve_graph",
    "analyze_project",
    "analyze_document",
    "analyze_memories",
    "research",
    "calculate",
    "generate_report",
    "propose_memory",
]
Priority = Literal["low", "normal", "high", "urgent"]
PlanStatus = Literal[
    "draft",
    "needs_clarification",
    "approved",
    "running",
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
    "archived",
]
ExecutionStatus = Literal[
    "created",
    "planning",
    "awaiting_approval",
    "executing",
    "paused",
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
]
TaskStatus = Literal[
    "pending", "ready", "awaiting_approval", "running", "completed", "failed", "skipped", "cancelled"
]
VerificationStatus = Literal["pending", "verified", "partially_verified", "failed", "not_verifiable"]
ApprovalStatus = Literal["pending", "approved", "rejected", "expired", "consumed"]
WorkflowStatus = Literal["suggested", "active", "archived"]


class AgentDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)


class PlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=3, max_length=2000)
    title: str | None = Field(default=None, max_length=200)
    priority: Priority | None = None
    documents: list[AgentDocument] = Field(default_factory=list, max_length=3)

    @field_validator("objective")
    @classmethod
    def objective_not_blank(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("Objective cannot be blank.")
        return cleaned


class PlanTaskEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    task_type: TaskType
    expected_output: str = Field(default="", max_length=500)
    input: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[int] = Field(default_factory=list, max_length=20)


class PlanUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: Priority | None = None
    tasks: list[PlanTaskEdit] | None = Field(default=None, min_length=1, max_length=40)


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    answer: str = Field(min_length=1, max_length=1000)


class PlanApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[ClarificationAnswer] = Field(default_factory=list, max_length=10)


class ExecutePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


class WorkflowStepInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    task_type: TaskType
    expected_output: str = Field(default="", max_length=500)
    input: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[int] = Field(default_factory=list, max_length=20)


class WorkflowCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    objective_template: str = Field(default="", max_length=2000)
    intent: str = Field(default="generic", max_length=40)
    steps: list[WorkflowStepInput] = Field(min_length=1, max_length=40)
    status: WorkflowStatus = "active"


class WorkflowUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    objective_template: str | None = Field(default=None, max_length=2000)
    intent: str | None = Field(default=None, max_length=40)
    steps: list[WorkflowStepInput] | None = Field(default=None, min_length=1, max_length=40)
    status: WorkflowStatus | None = None


class WorkflowDuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)


class WorkflowExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str | None = Field(default=None, min_length=3, max_length=2000)


class ApprovalResponse(BaseModel):
    approval_id: UUID
    execution_id: UUID
    task_id: UUID
    tool_name: str
    action_summary: str
    reason: str
    expected_impact: str
    data_involved: list[str]
    reversible: bool
    parameters: dict[str, Any]
    parameters_hash: str
    status: ApprovalStatus
    decision_note: str | None = None
    expires_at: datetime | None = None
    decided_at: datetime | None = None
    created_at: datetime | None = None
    expired: bool = False


class VerificationResponse(BaseModel):
    verification_id: UUID
    execution_id: UUID
    task_id: UUID
    verification_type: str
    expected_result: str
    observed_result: str
    status: VerificationStatus
    evidence: list[str]
    verified_at: datetime | None = None


class TaskResponse(BaseModel):
    task_id: UUID
    plan_id: UUID
    sequence: int
    title: str
    description: str
    task_type: str
    assigned_tool: str | None = None
    dependencies: list[int]
    input: dict[str, Any]
    expected_output: str
    status: TaskStatus
    approval_required: bool
    approval_policy: str
    execution_attempts: int
    max_attempts: int
    result: dict[str, Any] | None = None
    error: str | None = None
    verification_status: VerificationStatus
    verified_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    approval: ApprovalResponse | None = None
    verifications: list[VerificationResponse] = Field(default_factory=list)


class PlanResponse(BaseModel):
    plan_id: UUID
    workflow_id: UUID | None = None
    title: str
    objective: str
    description: str
    intent: str
    priority: str
    estimated_complexity: str
    status: PlanStatus
    source: str
    context: dict[str, Any]
    clarifications: list[dict[str, Any]]
    clarification_answers: list[dict[str, Any]]
    warnings: list[str]
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    task_count: int
    completed_count: int
    progress: int
    tasks: list[TaskResponse] = Field(default_factory=list)


class ExecutionResponse(BaseModel):
    execution_id: UUID
    plan_id: UUID
    workflow_id: UUID | None = None
    status: ExecutionStatus
    progress: int
    progress_definition: str
    current_task_id: UUID | None = None
    error: str | None = None
    cancel_requested: bool
    learning: dict[str, Any]
    context: dict[str, Any]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    plan_title: str | None = None
    plan_status: str | None = None
    plan: PlanResponse | None = None
    task_counts: dict[str, int]
    tasks: list[TaskResponse] = Field(default_factory=list)
    current_task: TaskResponse | None = None


class EventResponse(BaseModel):
    event_id: UUID
    execution_id: UUID
    task_id: UUID | None = None
    event_type: str
    message: str
    payload: dict[str, Any]
    sequence: int
    created_at: datetime | None = None


class InvocationResponse(BaseModel):
    invocation_id: UUID
    tool_name: str
    status: str
    attempts: int
    duration_ms: int
    error: str | None = None
    task_id: UUID | None = None
    created_at: datetime | None = None
    arguments_preview: dict[str, Any]
    output_preview: dict[str, Any]


class ToolResponse(BaseModel):
    tool_name: str
    description: str
    category: str
    permission: str
    side_effects: bool
    approval_required: bool
    enabled: bool
    disabled_reason: str | None = None
    timeout_seconds: float
    max_attempts: int
    fallback: str | None = None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    stats: dict[str, Any]


class WorkflowResponse(BaseModel):
    workflow_id: UUID
    name: str
    description: str
    objective_template: str
    intent: str
    steps: list[dict[str, Any]]
    status: WorkflowStatus
    source: str
    success_count: int
    failure_count: int
    last_executed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_execution: dict[str, Any] | None = None
    available: bool
    missing_tools: list[str]
    editable: bool


class AnalyticsResponse(BaseModel):
    total_executions: int
    active_executions: int
    completed_executions: int
    failed_executions: int
    cancelled_executions: int
    terminal_executions: int
    success_rate_percent: int | None
    success_rate_definition: str
    total_plans: int
    plans_waiting_for_approval: int
    pending_approvals: int
    workflow_count: int
    suggested_workflows: int
    verified_tasks: int
    partially_verified_tasks: int
    failed_verifications: int
    tool_usage: list[dict[str, Any]]
    recent_tasks: list[dict[str, Any]]
    recent_events: list[EventResponse]


class PlanPage(BaseModel):
    items: list[PlanResponse]
    total: int


class ExecutionPage(BaseModel):
    items: list[ExecutionResponse]
    total: int


class ApprovalPage(BaseModel):
    items: list[ApprovalResponse]
    total: int


class VerificationPage(BaseModel):
    items: list[VerificationResponse]
    total: int


class EventPage(BaseModel):
    items: list[EventResponse]
    total: int

"""Provider-free internal contracts shared by the agent modules.

The agent deliberately does not depend on an LLM for planning, tool selection or
verification. Plans come from deterministic templates, tools are allowlisted and
results are verified against stored evidence, so no module here needs to trust
free-form model output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

PERMISSION_READ_ONLY = "read_only"
PERMISSION_REVERSIBLE = "reversible"
PERMISSION_SENSITIVE = "sensitive"
PERMISSIONS = (PERMISSION_READ_ONLY, PERMISSION_REVERSIBLE, PERMISSION_SENSITIVE)

TASK_TYPES = (
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
)


@dataclass(slots=True)
class AgentContext:
    """Structured, evidence-backed context assembled before planning."""

    memories: list[dict[str, Any]] = field(default_factory=list)
    preferences: list[dict[str, Any]] = field(default_factory=list)
    graph_entities: list[dict[str, Any]] = field(default_factory=list)
    graph_paths: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    prior_executions: list[dict[str, Any]] = field(default_factory=list)
    workflows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def evidence_ids(self) -> list[str]:
        return [str(item.get("memory_id")) for item in self.memories if item.get("memory_id")]

    def retrieval_summary(self) -> str:
        return (
            f"{len(self.memories)} approved memories, {len(self.preferences)} preferences, "
            f"{len(self.graph_entities)} graph entities, {len(self.prior_executions)} prior executions"
        )


@dataclass(slots=True)
class PlannedTask:
    title: str
    description: str
    task_type: str
    assigned_tool: str
    expected_output: str
    input: dict[str, Any] = field(default_factory=dict)
    dependencies: list[int] = field(default_factory=list)
    approval_required: bool = False
    task_id: UUID | None = None


@dataclass(slots=True)
class PlannedPlan:
    title: str
    objective: str
    description: str
    intent: str
    priority: str
    estimated_complexity: str
    tasks: list[PlannedTask]
    clarifications: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    context_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolContext:
    db: Session
    user_id: UUID
    execution_id: UUID | None = None
    task_id: UUID | None = None
    task_input: dict[str, Any] = field(default_factory=dict)
    upstream_results: list[dict[str, Any]] = field(default_factory=list)
    plan_objective: str = ""


@dataclass(slots=True)
class ToolResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None
    sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VerificationOutcome:
    verification_type: str
    expected_result: str
    observed_result: str
    status: str
    evidence: list[str] = field(default_factory=list)


class AgentError(RuntimeError):
    """Base class for safe, user-facing agent failures."""


class AgentDisabledError(AgentError):
    pass


class AgentNotFoundError(LookupError):
    pass


class AgentConflictError(AgentError):
    pass


class AgentValidationError(AgentError):
    pass


class AgentRateLimitError(AgentError):
    pass


class ToolNotAllowedError(AgentError):
    pass

"""Progress and milestone summaries computed from persisted plan/task rows."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.agents.agent_schemas import ToolContext, ToolResult
from app.agents.execution_state import progress_percent
from app.agents.tools.base_tool import ToolSpec
from app.agents.tools.registry import registry
from app.models.agent import AgentExecution, AgentPlan, AgentTask


class ProgressSummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["plan", "execution"] = "plan"


def progress_summary(context: ToolContext, payload: ProgressSummaryInput) -> ToolResult:
    execution = None
    if context.execution_id is not None:
        execution = context.db.get(AgentExecution, context.execution_id)
    if execution is None:
        return ToolResult(
            ok=False,
            summary="No execution context was available for a progress summary.",
            error="execution_not_found",
            error_kind="permanent",
        )
    plan = context.db.get(AgentPlan, execution.plan_id)
    if plan is None or plan.user_id != context.user_id:
        return ToolResult(
            ok=False,
            summary="The plan behind this execution was not found for the current user.",
            error="plan_not_found",
            error_kind="permanent",
        )
    tasks = list(
        context.db.scalars(
            select(AgentTask).where(AgentTask.plan_id == plan.plan_id).order_by(AgentTask.sequence)
        ).all()
    )
    completed = [task for task in tasks if task.status == "completed"]
    failed = [task for task in tasks if task.status == "failed"]
    pending = [task for task in tasks if task.status in {"pending", "ready"}]
    awaiting = [task for task in tasks if task.status == "awaiting_approval"]
    verified = [task for task in tasks if task.verification_status == "verified"]
    partial = [task for task in tasks if task.verification_status == "partially_verified"]

    def compact(task: AgentTask) -> dict:
        return {
            "task_id": str(task.task_id),
            "title": task.title,
            "status": task.status,
            "verification_status": task.verification_status,
        }

    return ToolResult(
        ok=True,
        summary=(
            f"Plan '{plan.title}' has {len(completed)}/{len(tasks)} completed task(s), "
            f"{len(failed)} failed, {len(awaiting)} awaiting approval. "
            f"{len(verified)} verified and {len(partial)} partially verified."
        ),
        data={
            "plan_id": str(plan.plan_id),
            "execution_id": str(execution.execution_id),
            "plan_status": plan.status,
            "execution_status": execution.status,
            "progress_percent": progress_percent(len(tasks), len(completed)),
            "progress_definition": "completed tasks ÷ all plan tasks, using persisted task rows only",
            "total": len(tasks),
            "completed": [compact(task) for task in completed],
            "pending": [compact(task) for task in pending],
            "awaiting_approval": [compact(task) for task in awaiting],
            "failed": [compact(task) for task in failed],
            "verified": len(verified),
            "partially_verified": len(partial),
        },
        evidence=[str(task.task_id) for task in completed],
    )


registry.register(
    ToolSpec(
        name="progress_summary",
        description="Summarise real plan progress, failures and verification counts from the database.",
        category="planning",
        permission="read_only",
        input_model=ProgressSummaryInput,
        handler=progress_summary,
    )
)

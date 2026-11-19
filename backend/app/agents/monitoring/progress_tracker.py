"""Progress calculated only from persisted task rows.

There is deliberately no time-based estimate and no predicted completion
percentage. ``progress`` is: completed tasks / all tasks in the plan, rounded to
the nearest integer and floored at zero.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.execution_state import progress_percent, utcnow
from app.models.agent import AgentExecution, AgentTask


def tasks_for_execution(db: Session, execution: AgentExecution) -> list[AgentTask]:
    return list(
        db.scalars(
            select(AgentTask)
            .where(AgentTask.plan_id == execution.plan_id)
            .order_by(AgentTask.sequence)
        ).all()
    )


def completed_count(tasks: list[AgentTask]) -> int:
    return sum(1 for task in tasks if task.status == "completed")


def recompute(db: Session, execution: AgentExecution, *, commit: bool = True) -> int:
    """Persist the honest progress value for the execution."""
    tasks = tasks_for_execution(db, execution)
    execution.progress = progress_percent(len(tasks), completed_count(tasks))
    execution.last_heartbeat_at = utcnow()
    if commit:
        db.commit()
        db.refresh(execution)
    return execution.progress


def snapshot(db: Session, execution: AgentExecution) -> dict:
    tasks = tasks_for_execution(db, execution)
    return {
        "execution_id": str(execution.execution_id),
        "plan_id": str(execution.plan_id),
        "status": execution.status,
        "progress_percent": progress_percent(len(tasks), completed_count(tasks)),
        "progress_definition": (
            "completed tasks ÷ total tasks in the plan, computed from persisted task states"
        ),
        "total_tasks": len(tasks),
        "completed_tasks": completed_count(tasks),
        "failed_tasks": sum(1 for task in tasks if task.status == "failed"),
        "awaiting_approval": sum(1 for task in tasks if task.status == "awaiting_approval"),
        "pending_tasks": sum(1 for task in tasks if task.status in {"pending", "ready"}),
        "current_task_id": str(execution.current_task_id) if execution.current_task_id else None,
    }

"""Facade that keeps execution status, progress and the event log consistent."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents import execution_state as state
from app.agents.monitoring import event_manager, progress_tracker
from app.models.agent import AgentExecution, AgentPlan, AgentTask


def log(
    db: Session,
    execution: AgentExecution,
    event_type: str,
    message: str,
    *,
    task: AgentTask | None = None,
    payload: dict | None = None,
) -> None:
    event_manager.append_event(
        db,
        execution.user_id,
        execution.execution_id,
        event_type,
        message,
        task_id=task.task_id if task is not None else None,
        payload=payload or {},
    )
    db.commit()


def touch(db: Session, execution: AgentExecution, *, commit: bool = True) -> int:
    return progress_tracker.recompute(db, execution, commit=commit)


def mark_started(db: Session, execution: AgentExecution) -> None:
    first_start = execution.started_at is None
    execution.status = state.EXECUTION_EXECUTING
    execution.started_at = execution.started_at or state.utcnow()
    execution.last_heartbeat_at = state.utcnow()
    db.commit()
    log(
        db,
        execution,
        "execution.started" if first_start else "execution.continuing",
        (
            "Execution started. Each task runs against an allowlisted tool."
            if first_start
            else "Execution continues from persisted task state."
        ),
        payload={"progress_definition": "completed tasks ÷ total tasks"},
    )


def finish(db: Session, execution: AgentExecution, tasks: list[AgentTask]) -> str:
    """Persist the derived terminal status. Never claims success without task rows."""
    status = state.execution_status_for(tasks)
    if execution.cancel_requested and status not in {
        state.EXECUTION_COMPLETED,
        state.EXECUTION_PARTIALLY_COMPLETED,
    }:
        status = state.EXECUTION_CANCELLED

    execution.status = status
    execution.current_task_id = None
    progress_tracker.recompute(db, execution, commit=False)

    plan = db.get(AgentPlan, execution.plan_id)
    if plan is not None:
        plan.status = state.plan_status_for(tasks)
        if status == state.EXECUTION_CANCELLED:
            plan.status = state.PLAN_CANCELLED
        elif status == state.EXECUTION_FAILED:
            plan.status = state.PLAN_FAILED
        elif status == state.EXECUTION_PARTIALLY_COMPLETED:
            plan.status = state.PLAN_PARTIALLY_COMPLETED
        elif status == state.EXECUTION_COMPLETED:
            plan.status = state.PLAN_COMPLETED

    failed = [task.title for task in tasks if task.status == "failed"]
    if status in {state.EXECUTION_FAILED, state.EXECUTION_PARTIALLY_COMPLETED} and failed:
        execution.error = ("Failed task(s): " + ", ".join(failed))[:300]
    if status in state.EXECUTION_TERMINAL:
        execution.finished_at = state.utcnow()
    db.commit()

    labels = {
        state.EXECUTION_COMPLETED: "Execution completed. Every task finished and was verified.",
        state.EXECUTION_PARTIALLY_COMPLETED: (
            "Execution partially completed. Completed results were preserved; some tasks failed."
        ),
        state.EXECUTION_FAILED: "Execution failed. No successful result is claimed.",
        state.EXECUTION_CANCELLED: "Execution cancelled. Completed results were preserved.",
    }
    log(
        db,
        execution,
        f"execution.{status}",
        labels.get(status, f"Execution is {status}."),
        payload={
            "progress_percent": execution.progress,
            "completed": sum(1 for task in tasks if task.status == "completed"),
            "failed": len(failed),
            "total": len(tasks),
        },
    )
    return status

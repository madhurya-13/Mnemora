"""Explicit execution states, terminal helpers and honest progress calculation."""

from __future__ import annotations

from datetime import datetime, timezone

PLAN_DRAFT = "draft"
PLAN_NEEDS_CLARIFICATION = "needs_clarification"
PLAN_APPROVED = "approved"
PLAN_RUNNING = "running"
PLAN_COMPLETED = "completed"
PLAN_PARTIALLY_COMPLETED = "partially_completed"
PLAN_FAILED = "failed"
PLAN_CANCELLED = "cancelled"
PLAN_ARCHIVED = "archived"

PLAN_TERMINAL = {
    PLAN_COMPLETED,
    PLAN_PARTIALLY_COMPLETED,
    PLAN_FAILED,
    PLAN_CANCELLED,
    PLAN_ARCHIVED,
}
PLAN_EDITABLE = {PLAN_DRAFT, PLAN_NEEDS_CLARIFICATION}

TASK_PENDING = "pending"
TASK_READY = "ready"
TASK_AWAITING_APPROVAL = "awaiting_approval"
TASK_RUNNING = "running"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"
TASK_SKIPPED = "skipped"
TASK_CANCELLED = "cancelled"

TASK_TERMINAL = {TASK_COMPLETED, TASK_FAILED, TASK_SKIPPED, TASK_CANCELLED}

EXECUTION_CREATED = "created"
EXECUTION_PLANNING = "planning"
EXECUTION_AWAITING_APPROVAL = "awaiting_approval"
EXECUTION_EXECUTING = "executing"
EXECUTION_PAUSED = "paused"
EXECUTION_COMPLETED = "completed"
EXECUTION_PARTIALLY_COMPLETED = "partially_completed"
EXECUTION_FAILED = "failed"
EXECUTION_CANCELLED = "cancelled"

EXECUTION_TERMINAL = {
    EXECUTION_COMPLETED,
    EXECUTION_PARTIALLY_COMPLETED,
    EXECUTION_FAILED,
    EXECUTION_CANCELLED,
}
EXECUTION_ACTIVE = {EXECUTION_CREATED, EXECUTION_PLANNING, EXECUTION_EXECUTING, EXECUTION_AWAITING_APPROVAL, EXECUTION_PAUSED}
# Statuses a pause may be requested from.
EXECUTION_PAUSABLE = {EXECUTION_EXECUTING}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def progress_percent(total: int, completed: int) -> int:
    """Progress is completed tasks divided by all tasks in the plan.

    Failed, skipped and cancelled tasks count as not completed, so the number can
    never overstate progress. No time-based estimate is used.
    """
    if total <= 0:
        return 0
    completed = max(0, min(completed, total))
    return round(100 * completed / total)


def execution_status_for(tasks: list) -> str:
    """Derive the execution outcome from persisted task states.

    Awaiting approval is checked first because a single blocked task stops the
    run loop; no percentage or time estimate is involved.
    """
    statuses = [task.status for task in tasks]
    if not statuses:
        return EXECUTION_FAILED
    if any(status == TASK_AWAITING_APPROVAL for status in statuses):
        return EXECUTION_AWAITING_APPROVAL
    if any(status in {TASK_PENDING, TASK_READY, TASK_RUNNING} for status in statuses):
        return EXECUTION_EXECUTING
    completed = statuses.count(TASK_COMPLETED)
    failed = statuses.count(TASK_FAILED)
    cancelled = statuses.count(TASK_CANCELLED)
    if completed and not failed and not cancelled:
        return EXECUTION_COMPLETED
    if completed:
        return EXECUTION_PARTIALLY_COMPLETED
    if cancelled:
        return EXECUTION_CANCELLED
    return EXECUTION_FAILED


def plan_status_for(tasks: list) -> str:
    statuses = [task.status for task in tasks]
    if not statuses:
        return PLAN_FAILED
    if any(status in {TASK_PENDING, TASK_READY, TASK_RUNNING, TASK_AWAITING_APPROVAL} for status in statuses):
        return PLAN_RUNNING
    completed = statuses.count(TASK_COMPLETED)
    failed = statuses.count(TASK_FAILED)
    cancelled = statuses.count(TASK_CANCELLED)
    if completed and not failed and not cancelled:
        return PLAN_COMPLETED
    if completed:
        return PLAN_PARTIALLY_COMPLETED
    if cancelled:
        return PLAN_CANCELLED
    return PLAN_FAILED

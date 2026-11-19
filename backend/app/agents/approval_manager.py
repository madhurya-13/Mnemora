"""Single-use, parameter-bound human approvals for sensitive agent actions."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import execution_state as state
from app.agents.agent_safety import redact_arguments
from app.agents.agent_schemas import AgentConflictError, AgentNotFoundError
from app.agents.tools.base_tool import ToolSpec
from app.config import settings
from app.models.agent import AgentApproval, AgentExecution, AgentTask


def parameters_hash(tool_name: str, parameters: dict) -> str:
    canonical = json.dumps(
        {"tool": tool_name, "parameters": parameters or {}}, sort_keys=True, default=str, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _data_involved(parameters: dict) -> list[str]:
    labels = []
    for key in ("query", "category", "mode", "project_name", "content", "documents"):
        if key in parameters:
            value = parameters[key]
            if key == "documents":
                labels.append(f"{len(value)} supplied document(s)")
            else:
                labels.append(f"{key}: {str(value)[:80]}")
    return labels or ["task input metadata"]


def request_approval(
    db: Session,
    user_id: UUID,
    execution: AgentExecution,
    task: AgentTask,
    spec: ToolSpec,
) -> AgentApproval:
    digest = parameters_hash(spec.name, task.input or {})
    existing = db.scalar(
        select(AgentApproval).where(
            AgentApproval.user_id == user_id,
            AgentApproval.task_id == task.task_id,
            AgentApproval.status == "pending",
            AgentApproval.parameters_hash == digest,
        )
    )
    if existing is not None:
        task.status = state.TASK_AWAITING_APPROVAL
        execution.status = state.EXECUTION_AWAITING_APPROVAL
        db.commit()
        return existing

    approval = AgentApproval(
        user_id=user_id,
        execution_id=execution.execution_id,
        task_id=task.task_id,
        tool_name=spec.name,
        action_summary=f"{task.title} ({spec.name})"[:500],
        reason=(task.description or spec.description)[:500],
        expected_impact=(
            f"Runs the '{spec.name}' tool. Permission: {spec.permission}. "
            + (
                "This action may change stored data."
                if spec.side_effects
                else "This action only reads data."
            )
        )[:500],
        data_involved=_data_involved(task.input or {}),
        reversible=spec.reversible,
        parameters_hash=digest,
        parameters=redact_arguments(task.input or {}),
        status="pending",
        expires_at=state.utcnow() + timedelta(minutes=settings.agent_approval_ttl_minutes),
    )
    db.add(approval)
    task.status = state.TASK_AWAITING_APPROVAL
    execution.status = state.EXECUTION_AWAITING_APPROVAL
    execution.current_task_id = task.task_id
    db.commit()
    db.refresh(approval)

    from app.agents.monitoring import event_manager

    event_manager.append_event(
        db,
        user_id,
        execution.execution_id,
        "approval.requested",
        f"Approval requested for '{task.title}' using {spec.name}.",
        task_id=task.task_id,
        payload={"approval_id": str(approval.approval_id), "permission": spec.permission},
    )
    db.commit()
    return approval


def approved_for_task(db: Session, user_id: UUID, task: AgentTask) -> AgentApproval | None:
    digest = parameters_hash(task.assigned_tool or "", task.input or {})
    return db.scalar(
        select(AgentApproval).where(
            AgentApproval.user_id == user_id,
            AgentApproval.task_id == task.task_id,
            AgentApproval.status == "approved",
            AgentApproval.parameters_hash == digest,
        )
    )


def consume_for_task(db: Session, user_id: UUID, task: AgentTask) -> bool:
    approval = approved_for_task(db, user_id, task)
    if approval is None:
        return False
    if approval.expires_at <= state.utcnow():
        approval.status = "expired"
        db.commit()
        return False
    approval.status = "consumed"
    approval.decided_at = approval.decided_at or state.utcnow()
    db.commit()
    return True


def list_approvals(
    db: Session, user_id: UUID, *, status_filter: str | None = None, limit: int = 50, offset: int = 0
) -> list[AgentApproval]:
    expire_stale(db, user_id)
    statement = select(AgentApproval).where(AgentApproval.user_id == user_id)
    if status_filter:
        statement = statement.where(AgentApproval.status == status_filter)
    statement = statement.order_by(AgentApproval.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(statement).all())


def get_approval(db: Session, user_id: UUID, approval_id: UUID) -> AgentApproval:
    approval = db.get(AgentApproval, approval_id)
    if approval is None or approval.user_id != user_id:
        raise AgentNotFoundError("Approval not found.")
    return approval


def decide(
    db: Session,
    user_id: UUID,
    approval_id: UUID,
    *,
    approve: bool,
    note: str | None = None,
) -> AgentApproval:
    approval = get_approval(db, user_id, approval_id)
    now = state.utcnow()
    if approval.status != "pending":
        raise AgentConflictError(f"This approval is already {approval.status}.")
    if approval.expires_at <= now:
        approval.status = "expired"
        task = db.get(AgentTask, approval.task_id)
        if task is not None and task.status == state.TASK_AWAITING_APPROVAL:
            others = db.scalar(
                select(AgentApproval).where(
                    AgentApproval.task_id == task.task_id,
                    AgentApproval.status == "pending",
                    AgentApproval.approval_id != approval.approval_id,
                )
            )
            if others is None:
                task.status = state.TASK_CANCELLED
                task.completed_at = now
                task.error = "Approval expired before a decision was made."
        db.commit()
        raise AgentConflictError("This approval expired and cannot be reused. Request a new one.")

    task = db.get(AgentTask, approval.task_id)
    if task is None or task.user_id != user_id:
        raise AgentNotFoundError("The approval's task no longer exists.")
    if parameters_hash(task.assigned_tool or "", task.input or {}) != approval.parameters_hash:
        raise AgentConflictError(
            "The task parameters changed after approval was requested; the approval no longer applies."
        )

    approval.status = "approved" if approve else "rejected"
    approval.decided_at = now
    approval.decision_note = (note or "")[:500] or None
    execution = db.get(AgentExecution, approval.execution_id)

    if not approve:
        task.status = state.TASK_CANCELLED
        task.completed_at = now
        task.error = "Action rejected by the user."
    db.commit()

    if execution is not None:
        from app.agents.monitoring import event_manager

        event_manager.append_event(
            db,
            user_id,
            execution.execution_id,
            "approval.approved" if approve else "approval.rejected",
            (
                f"Action approved: {approval.action_summary}"
                if approve
                else f"Action rejected and not executed: {approval.action_summary}"
            ),
            task_id=task.task_id,
            payload={"approval_id": str(approval.approval_id), "note": approval.decision_note},
        )
        db.commit()
    return approval


def expire_stale(db: Session, user_id: UUID | None = None) -> int:
    now = state.utcnow()
    statement = select(AgentApproval).where(
        AgentApproval.status == "pending", AgentApproval.expires_at <= now
    )
    if user_id is not None:
        statement = statement.where(AgentApproval.user_id == user_id)
    expired = list(db.scalars(statement).all())
    if not expired:
        return 0
    from app.agents.monitoring import event_manager

    for approval in expired:
        approval.status = "expired"
        task = db.get(AgentTask, approval.task_id)
        if task is not None and task.status == state.TASK_AWAITING_APPROVAL:
            others = db.scalar(
                select(AgentApproval).where(
                    AgentApproval.task_id == task.task_id,
                    AgentApproval.status == "pending",
                    AgentApproval.approval_id != approval.approval_id,
                )
            )
            if others is None:
                task.status = state.TASK_CANCELLED
                task.completed_at = now
                task.error = "Approval expired."
        event_manager.append_event(
            db,
            approval.user_id,
            approval.execution_id,
            "approval.expired",
            f"Approval expired and was not executed: {approval.action_summary}",
            task_id=approval.task_id,
        )
    db.commit()
    return len(expired)


def expire_for_execution(db: Session, user_id: UUID, execution_id: UUID) -> int:
    rows = list(
        db.scalars(
            select(AgentApproval).where(
                AgentApproval.user_id == user_id,
                AgentApproval.execution_id == execution_id,
                AgentApproval.status == "pending",
            )
        ).all()
    )
    for row in rows:
        row.status = "expired"
    if rows:
        db.commit()
    return len(rows)

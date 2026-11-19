"""Read-only projections of task and execution state for the API and UI."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import execution_state as state
from app.agents.monitoring import progress_tracker
from app.models.agent import (
    AgentApproval,
    AgentExecution,
    AgentPlan,
    AgentTask,
    ExecutionEvent,
    TaskVerification,
    ToolInvocation,
    WorkflowTemplate,
)


def task_payload(db: Session, task: AgentTask) -> dict:
    approval = db.scalar(
        select(AgentApproval)
        .where(AgentApproval.task_id == task.task_id)
        .order_by(AgentApproval.created_at.desc())
    )
    verifications = list(
        db.scalars(
            select(TaskVerification)
            .where(TaskVerification.task_id == task.task_id)
            .order_by(TaskVerification.verified_at.desc())
        ).all()
    )
    return {
        "task_id": str(task.task_id),
        "plan_id": str(task.plan_id),
        "sequence": task.sequence,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "assigned_tool": task.assigned_tool,
        "dependencies": list(task.dependencies or []),
        "input": task.input or {},
        "expected_output": task.expected_output,
        "status": task.status,
        "approval_required": task.approval_required,
        "approval_policy": task.approval_policy,
        "execution_attempts": task.execution_attempts,
        "max_attempts": task.max_attempts,
        "result": task.result,
        "error": task.error,
        "verification_status": task.verification_status,
        "verified_at": task.verified_at.isoformat() if task.verified_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "approval": approval_payload(approval) if approval is not None else None,
        "verifications": [verification_payload(item) for item in verifications],
    }


def approval_payload(approval: AgentApproval) -> dict:
    now = state.utcnow()
    return {
        "approval_id": str(approval.approval_id),
        "execution_id": str(approval.execution_id),
        "task_id": str(approval.task_id),
        "tool_name": approval.tool_name,
        "action_summary": approval.action_summary,
        "reason": approval.reason,
        "expected_impact": approval.expected_impact,
        "data_involved": list(approval.data_involved or []),
        "reversible": approval.reversible,
        "parameters": approval.parameters or {},
        "parameters_hash": approval.parameters_hash,
        "status": approval.status,
        "decision_note": approval.decision_note,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "expired": approval.status == "pending" and approval.expires_at <= now,
    }


def verification_payload(verification: TaskVerification) -> dict:
    return {
        "verification_id": str(verification.verification_id),
        "execution_id": str(verification.execution_id),
        "task_id": str(verification.task_id),
        "verification_type": verification.verification_type,
        "expected_result": verification.expected_result,
        "observed_result": verification.observed_result,
        "status": verification.status,
        "evidence": list(verification.evidence or []),
        "verified_at": verification.verified_at.isoformat() if verification.verified_at else None,
    }


def event_payload(event: ExecutionEvent) -> dict:
    return {
        "event_id": str(event.event_id),
        "execution_id": str(event.execution_id),
        "task_id": str(event.task_id) if event.task_id else None,
        "event_type": event.event_type,
        "message": event.message,
        "payload": event.payload or {},
        "sequence": event.sequence,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def execution_payload(db: Session, execution: AgentExecution, *, include_tasks: bool = True) -> dict:
    plan = db.get(AgentPlan, execution.plan_id)
    tasks = progress_tracker.tasks_for_execution(db, execution)
    payload = {
        "execution_id": str(execution.execution_id),
        "plan_id": str(execution.plan_id),
        "workflow_id": str(execution.workflow_id) if execution.workflow_id else None,
        "status": execution.status,
        "progress": execution.progress,
        "progress_definition": (
            "completed tasks ÷ total tasks in the plan, computed from persisted task states"
        ),
        "current_task_id": str(execution.current_task_id) if execution.current_task_id else None,
        "error": execution.error,
        "cancel_requested": execution.cancel_requested,
        "learning": execution.learning or {},
        "context": execution.context or {},
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
        "last_heartbeat_at": (
            execution.last_heartbeat_at.isoformat() if execution.last_heartbeat_at else None
        ),
        "created_at": execution.created_at.isoformat() if execution.created_at else None,
        "updated_at": execution.updated_at.isoformat() if execution.updated_at else None,
        "plan_title": plan.title if plan is not None else None,
        "plan_status": plan.status if plan is not None else None,
        "plan": plan_payload(db, plan) if plan is not None and include_tasks else None,
        "task_counts": {
            "total": len(tasks),
            "completed": sum(1 for task in tasks if task.status == "completed"),
            "failed": sum(1 for task in tasks if task.status == "failed"),
            "pending": sum(1 for task in tasks if task.status in {"pending", "ready"}),
            "awaiting_approval": sum(1 for task in tasks if task.status == "awaiting_approval"),
        },
    }
    if include_tasks:
        payload["tasks"] = [task_payload(db, task) for task in tasks]
        current = next(
            (task for task in tasks if task.task_id == execution.current_task_id), None
        )
        payload["current_task"] = task_payload(db, current) if current is not None else None
    return payload


def plan_payload(db: Session, plan: AgentPlan, *, include_tasks: bool = True) -> dict:
    tasks = list(
        db.scalars(
            select(AgentTask).where(AgentTask.plan_id == plan.plan_id).order_by(AgentTask.sequence)
        ).all()
    )
    payload = {
        "plan_id": str(plan.plan_id),
        "workflow_id": str(plan.workflow_id) if plan.workflow_id else None,
        "title": plan.title,
        "objective": plan.objective,
        "description": plan.description,
        "intent": plan.intent,
        "priority": plan.priority,
        "estimated_complexity": plan.estimated_complexity,
        "status": plan.status,
        "source": plan.source,
        "context": plan.context or {},
        "clarifications": list(plan.clarifications or []),
        "clarification_answers": list(plan.clarification_answers or []),
        "warnings": list(plan.warnings or []),
        "error": plan.error,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        "task_count": len(tasks),
        "completed_count": sum(1 for task in tasks if task.status == "completed"),
        "progress": state.progress_percent(
            len(tasks), sum(1 for task in tasks if task.status == "completed")
        ),
    }
    if include_tasks:
        payload["tasks"] = [task_payload(db, task) for task in tasks]
    return payload


def workflow_payload(template: WorkflowTemplate, *, last_execution: AgentExecution | None = None) -> dict:
    return {
        "workflow_id": str(template.workflow_id),
        "name": template.name,
        "description": template.description,
        "objective_template": template.objective_template,
        "intent": template.intent,
        "steps": list(template.steps or []),
        "status": template.status,
        "source": template.source,
        "success_count": template.success_count,
        "failure_count": template.failure_count,
        "last_executed_at": (
            template.last_executed_at.isoformat() if template.last_executed_at else None
        ),
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
        "last_execution": (
            {
                "execution_id": str(last_execution.execution_id),
                "status": last_execution.status,
                "progress": last_execution.progress,
                "created_at": (
                    last_execution.created_at.isoformat() if last_execution.created_at else None
                ),
            }
            if last_execution is not None
            else None
        ),
    }


def invocation_payload(invocation: ToolInvocation) -> dict:
    return {
        "invocation_id": str(invocation.invocation_id),
        "tool_name": invocation.tool_name,
        "status": invocation.status,
        "attempts": invocation.attempts,
        "duration_ms": invocation.duration_ms,
        "error": invocation.error,
        "task_id": str(invocation.task_id) if invocation.task_id else None,
        "created_at": invocation.created_at.isoformat() if invocation.created_at else None,
        "arguments_preview": invocation.arguments or {},
        "output_preview": invocation.output or {},
    }


def recent_tasks(db: Session, user_id: UUID, *, limit: int = 12) -> list[dict]:
    tasks = list(
        db.scalars(
            select(AgentTask)
            .where(AgentTask.user_id == user_id)
            .order_by(AgentTask.updated_at.desc())
            .limit(limit)
        ).all()
    )
    items = []
    for task in tasks:
        plan = db.get(AgentPlan, task.plan_id)
        items.append(
            {
                "task_id": str(task.task_id),
                "plan_id": str(task.plan_id),
                "plan_title": plan.title if plan is not None else None,
                "title": task.title,
                "status": task.status,
                "verification_status": task.verification_status,
                "assigned_tool": task.assigned_tool,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
        )
    return items

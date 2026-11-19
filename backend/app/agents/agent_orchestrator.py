"""Central agent lifecycle: plan, approve, execute, pause, resume, cancel, recover.

Execution is synchronous and database-backed. The loop re-reads persisted state
between tasks, so pause/cancel set by another request are observed at the next
task boundary, and a crashed process leaves a paused execution that a user can
resume rather than a silently re-run side-effecting action.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents import agent_memory, approval_manager, execution_monitor, task_executor
from app.agents import execution_state as state
from app.agents.agent_schemas import (
    AgentConflictError,
    AgentDisabledError,
    AgentNotFoundError,
    AgentRateLimitError,
    AgentValidationError,
    PlannedPlan,
    PlannedTask,
)
from app.agents.monitoring import event_manager, progress_tracker, task_monitor
from app.agents.task_planner import build_plan, detect_intent
from app.agents.tool_selector import TOOL_BY_TASK_TYPE, missing_required_arguments, select_tool
from app.agents.tools.registry import registry
from app.config import settings
from app.models.agent import (
    AgentApproval,
    AgentExecution,
    AgentPlan,
    AgentTask,
    TaskVerification,
    ToolInvocation,
    WorkflowTemplate,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Plan lifecycle
# --------------------------------------------------------------------------- #
def _validate_dependencies(tasks: list[PlannedTask]) -> None:
    total = len(tasks)
    for index, task in enumerate(tasks):
        for dependency in task.dependencies:
            if not isinstance(dependency, int):
                raise AgentValidationError("Task dependencies must be integer sequence indexes.")
            if dependency < 0 or dependency >= total:
                raise AgentValidationError("A task dependency points outside the plan.")
            if dependency >= index:
                raise AgentValidationError(
                    "A task cannot depend on itself or on a later task; plans must be acyclic."
                )


def _task_attempts(tool_name: str) -> int:
    spec = registry.get(tool_name)
    bounded = spec.attempts if spec is not None else 1
    return max(1, min(bounded, settings.agent_max_tool_retries + 1))


def _persist_plan(
    db: Session,
    user_id: UUID,
    planned: PlannedPlan,
    *,
    workflow_id: UUID | None = None,
    source: str = "user",
) -> AgentPlan:
    _validate_dependencies(planned.tasks)
    plan = AgentPlan(
        user_id=user_id,
        workflow_id=workflow_id,
        title=planned.title[:200],
        objective=planned.objective,
        description=planned.description,
        intent=planned.intent,
        priority=planned.priority,
        estimated_complexity=planned.estimated_complexity,
        status=(
            state.PLAN_NEEDS_CLARIFICATION if planned.clarifications else state.PLAN_DRAFT
        ),
        source=source,
        context=planned.context_summary,
        clarifications=planned.clarifications,
        clarification_answers=[],
        warnings=planned.warnings,
    )
    db.add(plan)
    db.flush()
    for sequence, item in enumerate(planned.tasks):
        spec = registry.get(item.assigned_tool)
        db.add(
            AgentTask(
                plan_id=plan.plan_id,
                user_id=user_id,
                sequence=sequence,
                title=item.title,
                description=item.description,
                task_type=item.task_type,
                assigned_tool=item.assigned_tool,
                dependencies=list(item.dependencies),
                input=item.input,
                expected_output=item.expected_output,
                status=state.TASK_PENDING,
                approval_required=item.approval_required,
                approval_policy="required" if item.approval_required else "auto",
                max_attempts=_task_attempts(item.assigned_tool),
            )
        )
    db.commit()
    db.refresh(plan)
    return plan


def create_plan(
    db: Session,
    user_id: UUID,
    objective: str,
    *,
    documents: list[dict] | None = None,
    title: str | None = None,
    priority: str | None = None,
) -> AgentPlan:
    _require_enabled()
    objective = " ".join((objective or "").split())
    if len(objective) < 3:
        raise AgentValidationError("Describe the objective in at least a few words.")
    intent = detect_intent(objective)
    context = agent_memory.build_context(db, user_id, objective, intent)
    planned = build_plan(objective, context, documents or [])
    if title:
        planned.title = title[:200]
    if priority:
        if priority not in {"low", "normal", "high", "urgent"}:
            raise AgentValidationError("Priority must be low, normal, high or urgent.")
        planned.priority = priority
    return _persist_plan(db, user_id, planned)


def get_plan(db: Session, user_id: UUID, plan_id: UUID) -> AgentPlan:
    plan = db.get(AgentPlan, plan_id)
    if plan is None or plan.user_id != user_id:
        raise AgentNotFoundError("Plan not found.")
    return plan


def list_plans(
    db: Session,
    user_id: UUID,
    *,
    status_filter: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[AgentPlan]:
    statement = select(AgentPlan).where(AgentPlan.user_id == user_id)
    if status_filter:
        statement = statement.where(AgentPlan.status == status_filter)
    statement = statement.order_by(AgentPlan.updated_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(statement).all())


def _has_active_execution(db: Session, plan_id: UUID) -> bool:
    return (
        db.scalar(
            select(AgentExecution.execution_id).where(
                AgentExecution.plan_id == plan_id,
                AgentExecution.status.in_(tuple(state.EXECUTION_ACTIVE)),
            )
        )
        is not None
    )


def update_plan(
    db: Session,
    user_id: UUID,
    plan_id: UUID,
    *,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    tasks: list[dict] | None = None,
) -> AgentPlan:
    plan = get_plan(db, user_id, plan_id)
    if plan.status in state.PLAN_TERMINAL:
        raise AgentConflictError("A finished plan cannot be edited.")
    if _has_active_execution(db, plan.plan_id):
        raise AgentConflictError("Pause or finish the active execution before editing this plan.")

    if title is not None:
        plan.title = title.strip()[:200] or plan.title
    if description is not None:
        plan.description = description.strip()
    if priority is not None:
        if priority not in {"low", "normal", "high", "urgent"}:
            raise AgentValidationError("Priority must be low, normal, high or urgent.")
        plan.priority = priority

    if tasks is not None:
        if not tasks:
            raise AgentValidationError("A plan needs at least one task.")
        if len(tasks) > settings.agent_max_tasks_per_plan:
            raise AgentValidationError(
                f"A plan can contain at most {settings.agent_max_tasks_per_plan} tasks."
            )
        planned_tasks: list[PlannedTask] = []
        for item in tasks:
            task_type = str(item.get("task_type", "")).strip()
            tool_name = TOOL_BY_TASK_TYPE.get(task_type)
            if tool_name is None:
                raise AgentValidationError(f"Task type '{task_type}' has no allowlisted tool.")
            spec = select_tool(task_type)
            payload = item.get("input") or {}
            if not isinstance(payload, dict):
                raise AgentValidationError("Task input must be an object of tool arguments.")
            missing = missing_required_arguments(spec, payload)
            if missing:
                label = str(item.get("title", "")).strip() or task_type
                raise AgentValidationError(
                    f"Task '{label}' is missing required input field(s): {', '.join(missing)}."
                )
            dependencies = item.get("dependencies") or []
            if not isinstance(dependencies, list):
                raise AgentValidationError("Task dependencies must be a list of sequence indexes.")
            planned_tasks.append(
                PlannedTask(
                    title=str(item.get("title", "")).strip()[:200] or "Untitled task",
                    description=str(item.get("description", "")).strip()[:1000],
                    task_type=task_type,
                    assigned_tool=tool_name,
                    expected_output=str(item.get("expected_output", "")).strip()[:500],
                    input=payload,
                    dependencies=[int(value) for value in dependencies],
                    approval_required=spec.requires_approval,
                )
            )
        _validate_dependencies(planned_tasks)
        db.query(AgentTask).filter(AgentTask.plan_id == plan.plan_id).delete(
            synchronize_session=False
        )
        for sequence, item in enumerate(planned_tasks):
            db.add(
                AgentTask(
                    plan_id=plan.plan_id,
                    user_id=user_id,
                    sequence=sequence,
                    title=item.title,
                    description=item.description,
                    task_type=item.task_type,
                    assigned_tool=item.assigned_tool,
                    dependencies=list(item.dependencies),
                    input=item.input,
                    expected_output=item.expected_output,
                    status=state.TASK_PENDING,
                    approval_required=item.approval_required,
                    approval_policy="required" if item.approval_required else "auto",
                    max_attempts=_task_attempts(item.assigned_tool),
                )
            )
        plan.status = state.PLAN_DRAFT
        plan.error = None
    plan.updated_at = state.utcnow()
    db.commit()
    db.refresh(plan)
    return plan


def approve_plan(
    db: Session,
    user_id: UUID,
    plan_id: UUID,
    *,
    answers: list[dict] | None = None,
) -> AgentPlan:
    plan = get_plan(db, user_id, plan_id)
    if plan.status in state.PLAN_TERMINAL:
        raise AgentConflictError("A finished plan cannot be approved.")
    if plan.status in {state.PLAN_RUNNING}:
        raise AgentConflictError("This plan is already running.")

    answered = {str(item.get("id")) for item in (answers or []) if item.get("id")}
    if answers:
        plan.clarification_answers = list(plan.clarification_answers or []) + [
            {"id": str(item.get("id")), "answer": str(item.get("answer", ""))[:1000]}
            for item in answers
            if item.get("id")
        ]
    remaining = [
        item for item in (plan.clarifications or []) if str(item.get("id")) not in answered
    ]
    if remaining:
        plan.clarifications = remaining
        plan.status = state.PLAN_NEEDS_CLARIFICATION
        db.commit()
        db.refresh(plan)
        return plan
    plan.clarifications = []
    plan.status = state.PLAN_APPROVED
    plan.error = None
    db.commit()
    db.refresh(plan)
    return plan


def archive_plan(db: Session, user_id: UUID, plan_id: UUID) -> AgentPlan:
    plan = get_plan(db, user_id, plan_id)
    if _has_active_execution(db, plan.plan_id):
        raise AgentConflictError("Finish or cancel the active execution before archiving.")
    plan.status = state.PLAN_ARCHIVED
    db.commit()
    db.refresh(plan)
    return plan


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
def _require_enabled() -> None:
    if not settings.agents_enabled:
        raise AgentDisabledError("Agent capabilities are disabled (AGENTS_ENABLED=false).")


def _enforce_limits(db: Session, user_id: UUID) -> None:
    active = db.scalar(
        select(func.count())
        .select_from(AgentExecution)
        .where(
            AgentExecution.user_id == user_id,
            AgentExecution.status.in_(tuple(state.EXECUTION_ACTIVE)),
        )
    ) or 0
    if active >= settings.agent_max_concurrent_executions:
        raise AgentRateLimitError(
            "Too many active executions. Pause or finish one before starting another."
        )
    since = state.utcnow() - timedelta(hours=1)
    recent = db.scalar(
        select(func.count())
        .select_from(AgentExecution)
        .where(AgentExecution.user_id == user_id, AgentExecution.created_at >= since)
    ) or 0
    if recent >= settings.agent_rate_limit_executions_per_hour:
        raise AgentRateLimitError("Hourly execution limit reached. Try again later.")


def get_execution(db: Session, user_id: UUID, execution_id: UUID) -> AgentExecution:
    execution = db.get(AgentExecution, execution_id)
    if execution is None or execution.user_id != user_id:
        raise AgentNotFoundError("Execution not found.")
    return execution


def list_executions(
    db: Session,
    user_id: UUID,
    *,
    status_filter: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[AgentExecution]:
    statement = select(AgentExecution).where(AgentExecution.user_id == user_id)
    if status_filter:
        statement = statement.where(AgentExecution.status == status_filter)
    statement = statement.order_by(AgentExecution.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(statement).all())


def _tasks(db: Session, execution: AgentExecution) -> list[AgentTask]:
    return progress_tracker.tasks_for_execution(db, execution)


def _runnable(tasks: list[AgentTask]) -> list[AgentTask]:
    by_sequence = {task.sequence: task for task in tasks}
    runnable = []
    for task in tasks:
        if task.status not in {state.TASK_PENDING, state.TASK_READY}:
            continue
        ready = True
        for dependency in task.dependencies or []:
            prerequisite = by_sequence.get(int(dependency))
            if prerequisite is None or prerequisite.status != state.TASK_COMPLETED:
                ready = False
                break
        if ready:
            runnable.append(task)
    return runnable


def _skip_blocked(db: Session, execution: AgentExecution, tasks: list[AgentTask]) -> int:
    by_sequence = {task.sequence: task for task in tasks}
    skipped = 0
    for task in tasks:
        if task.status not in {state.TASK_PENDING, state.TASK_READY}:
            continue
        blocked = [
            int(dependency)
            for dependency in task.dependencies or []
            if by_sequence.get(int(dependency)) is not None
            and by_sequence[int(dependency)].status
            in {state.TASK_FAILED, state.TASK_SKIPPED, state.TASK_CANCELLED}
        ]
        if blocked:
            task.status = state.TASK_SKIPPED
            task.error = "A prerequisite task did not complete; this step was not run."
            task.completed_at = state.utcnow()
            skipped += 1
            event_manager.append_event(
                db,
                execution.user_id,
                execution.execution_id,
                "task.skipped",
                f"Skipped '{task.title}' because prerequisite task(s) {blocked} did not complete.",
                task_id=task.task_id,
            )
    if skipped:
        db.commit()
    return skipped


def _cancel_open_tasks(db: Session, execution: AgentExecution) -> None:
    for task in _tasks(db, execution):
        if task.status in {
            state.TASK_PENDING,
            state.TASK_READY,
            state.TASK_AWAITING_APPROVAL,
            state.TASK_RUNNING,
        }:
            task.status = state.TASK_CANCELLED
            task.completed_at = state.utcnow()
            task.error = task.error or "Cancelled before execution."
    approval_manager.expire_for_execution(db, execution.user_id, execution.execution_id)
    execution.current_task_id = None
    db.commit()


def _finalize(db: Session, execution: AgentExecution) -> AgentExecution:
    tasks = _tasks(db, execution)
    status = execution_monitor.finish(db, execution, tasks)
    if status in state.EXECUTION_TERMINAL:
        try:
            execution.learning = agent_memory.learn_from_execution(
                db, execution.user_id, execution
            )
            db.commit()
        except Exception as error:  # learning must never corrupt the execution record
            logger.warning("Agent learning skipped (%s).", type(error).__name__)
        if execution.workflow_id is not None:
            template = db.get(WorkflowTemplate, execution.workflow_id)
            if template is not None and template.user_id == execution.user_id:
                if status in {state.EXECUTION_COMPLETED, state.EXECUTION_PARTIALLY_COMPLETED}:
                    template.success_count += 1
                else:
                    template.failure_count += 1
                template.last_executed_at = state.utcnow()
                db.commit()
    db.refresh(execution)
    return execution


def _run_loop(db: Session, execution: AgentExecution) -> AgentExecution:
    execution_monitor.mark_started(db, execution)
    deadline = time.monotonic() + settings.agent_max_execution_seconds
    guard = settings.agent_max_tasks_per_plan * 4 + 20
    iterations = 0
    stop_status: str | None = None

    while True:
        iterations += 1
        if iterations > guard:
            execution.status = state.EXECUTION_PAUSED
            execution.error = "Execution stopped by the loop guard; no further tasks were run."
            db.commit()
            event_manager.append_event(
                db,
                execution.user_id,
                execution.execution_id,
                "execution.loop_guard",
                "Execution stopped by the loop guard to prevent an unbounded run.",
            )
            db.commit()
            stop_status = state.EXECUTION_PAUSED
            break

        db.refresh(execution)

        if execution.cancel_requested:
            _cancel_open_tasks(db, execution)
            stop_status = state.EXECUTION_CANCELLED
            break
        if execution.pause_requested:
            execution.status = state.EXECUTION_PAUSED
            db.commit()
            event_manager.append_event(
                db,
                execution.user_id,
                execution.execution_id,
                "execution.paused",
                "Execution paused at a task boundary. Completed tasks were preserved.",
            )
            db.commit()
            stop_status = state.EXECUTION_PAUSED
            break
        if time.monotonic() > deadline:
            execution.status = state.EXECUTION_PAUSED
            execution.error = (
                "Execution time budget exhausted; completed tasks were preserved. Resume to continue."
            )[:300]
            db.commit()
            event_manager.append_event(
                db,
                execution.user_id,
                execution.execution_id,
                "execution.budget_exhausted",
                "Execution paused because the configured time budget was reached.",
            )
            db.commit()
            stop_status = state.EXECUTION_PAUSED
            break

        tasks = _tasks(db, execution)
        approved = [
            task
            for task in tasks
            if task.status == state.TASK_AWAITING_APPROVAL
            and approval_manager.approved_for_task(db, execution.user_id, task) is not None
        ]
        if approved:
            task_executor.execute_task(db, execution, approved[0])
            progress_tracker.recompute(db, execution)
            continue

        runnable = _runnable(tasks)
        if runnable:
            task = runnable[0]
            outcome = task_executor.execute_task(db, execution, task)
            progress_tracker.recompute(db, execution)
            if outcome.outcome == task_executor.AWAITING_APPROVAL:
                execution.status = state.EXECUTION_AWAITING_APPROVAL
                execution.current_task_id = task.task_id
                db.commit()
                stop_status = state.EXECUTION_AWAITING_APPROVAL
                break
            continue

        if any(task.status == state.TASK_AWAITING_APPROVAL for task in tasks):
            execution.status = state.EXECUTION_AWAITING_APPROVAL
            awaiting = next(
                task for task in tasks if task.status == state.TASK_AWAITING_APPROVAL
            )
            execution.current_task_id = awaiting.task_id
            db.commit()
            stop_status = state.EXECUTION_AWAITING_APPROVAL
            break

        if _skip_blocked(db, execution, tasks):
            progress_tracker.recompute(db, execution)
            continue
        break

    if stop_status not in {state.EXECUTION_PAUSED, state.EXECUTION_AWAITING_APPROVAL}:
        return _finalize(db, execution)
    db.refresh(execution)
    return execution


def _start(db: Session, user_id: UUID, plan: AgentPlan, *, workflow_id: UUID | None = None):
    if plan.status in {state.PLAN_NEEDS_CLARIFICATION, state.PLAN_DRAFT}:
        raise AgentConflictError("Approve the plan before starting execution.")
    if plan.status in state.PLAN_TERMINAL:
        raise AgentConflictError("This plan has already finished; create a new plan to run it again.")
    if _has_active_execution(db, plan.plan_id):
        raise AgentConflictError("This plan already has an active execution.")

    tasks = list(
        db.scalars(
            select(AgentTask).where(AgentTask.plan_id == plan.plan_id).order_by(AgentTask.sequence)
        ).all()
    )
    if not tasks:
        raise AgentConflictError("This plan has no tasks to execute.")

    _enforce_limits(db, user_id)
    plan.status = state.PLAN_RUNNING
    execution = AgentExecution(
        user_id=user_id,
        plan_id=plan.plan_id,
        workflow_id=workflow_id or plan.workflow_id,
        status=state.EXECUTION_CREATED,
        progress=0,
        context=plan.context or {},
        learning={},
        cancel_requested=False,
        pause_requested=False,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    event_manager.append_event(
        db,
        user_id,
        execution.execution_id,
        "execution.created",
        f"Execution created for plan '{plan.title}'.",
        payload={"task_count": len(tasks)},
    )
    db.commit()
    return _run_loop(db, execution)


def start_execution(db: Session, user_id: UUID, plan_id: UUID) -> AgentExecution:
    _require_enabled()
    plan = get_plan(db, user_id, plan_id)
    return _start(db, user_id, plan)


def resume_execution(db: Session, user_id: UUID, execution_id: UUID) -> AgentExecution:
    _require_enabled()
    execution = get_execution(db, user_id, execution_id)
    if execution.status in state.EXECUTION_TERMINAL:
        raise AgentConflictError("This execution has already finished.")
    if execution.status == state.EXECUTION_EXECUTING:
        raise AgentConflictError("This execution is already running.")
    if execution.status not in {state.EXECUTION_PAUSED, state.EXECUTION_AWAITING_APPROVAL}:
        raise AgentConflictError("Only a paused or awaiting-approval execution can be resumed.")

    if execution.status == state.EXECUTION_AWAITING_APPROVAL:
        pending = db.scalar(
            select(func.count())
            .select_from(AgentApproval)
            .where(
                AgentApproval.execution_id == execution.execution_id,
                AgentApproval.status == "pending",
            )
        ) or 0
        approved = db.scalar(
            select(func.count())
            .select_from(AgentApproval)
            .where(
                AgentApproval.execution_id == execution.execution_id,
                AgentApproval.status == "approved",
            )
        ) or 0
        if pending and not approved:
            raise AgentConflictError(
                "Approve or reject the pending action before resuming this execution."
            )

    execution.pause_requested = False
    execution.cancel_requested = False
    execution.error = None
    execution.status = state.EXECUTION_EXECUTING
    db.commit()
    event_manager.append_event(
        db,
        execution.user_id,
        execution.execution_id,
        "execution.resumed",
        "Execution resumed. Only tasks that are not already completed will run.",
    )
    db.commit()
    return _run_loop(db, execution)


def pause_execution(db: Session, user_id: UUID, execution_id: UUID) -> AgentExecution:
    execution = get_execution(db, user_id, execution_id)
    if execution.status in state.EXECUTION_TERMINAL:
        raise AgentConflictError("This execution has already finished.")
    if execution.status == state.EXECUTION_PAUSED:
        return execution
    execution.pause_requested = True
    if execution.status in {
        state.EXECUTION_CREATED,
        state.EXECUTION_PLANNING,
        state.EXECUTION_EXECUTING,
        state.EXECUTION_AWAITING_APPROVAL,
    }:
        execution.status = state.EXECUTION_PAUSED
    db.commit()
    event_manager.append_event(
        db,
        execution.user_id,
        execution.execution_id,
        "execution.pause_requested",
        "Pause requested. The current tool call is not interrupted; no new task will start.",
    )
    db.commit()
    db.refresh(execution)
    return execution


def cancel_execution(db: Session, user_id: UUID, execution_id: UUID) -> AgentExecution:
    execution = get_execution(db, user_id, execution_id)
    if execution.status in state.EXECUTION_TERMINAL:
        return execution
    execution.cancel_requested = True
    execution.pause_requested = False
    if execution.status in {
        state.EXECUTION_CREATED,
        state.EXECUTION_PLANNING,
        state.EXECUTION_PAUSED,
        state.EXECUTION_AWAITING_APPROVAL,
    }:
        _cancel_open_tasks(db, execution)
        event_manager.append_event(
            db,
            execution.user_id,
            execution.execution_id,
            "execution.cancel_requested",
            "Cancellation accepted. No further tasks will run.",
        )
        db.commit()
        return _finalize(db, execution)
    db.commit()
    event_manager.append_event(
        db,
        execution.user_id,
        execution.execution_id,
        "execution.cancel_requested",
        "Cancellation requested. The run loop stops after the current tool call.",
    )
    db.commit()
    return execution


# --------------------------------------------------------------------------- #
# Read models, analytics and startup recovery
# --------------------------------------------------------------------------- #
def list_approvals(
    db: Session, user_id: UUID, *, status_filter: str | None = None, limit: int = 50, offset: int = 0
) -> list[AgentApproval]:
    return approval_manager.list_approvals(
        db, user_id, status_filter=status_filter, limit=limit, offset=offset
    )


def decide_approval(
    db: Session,
    user_id: UUID,
    approval_id: UUID,
    *,
    approve: bool,
    note: str | None = None,
) -> AgentApproval:
    return approval_manager.decide(db, user_id, approval_id, approve=approve, note=note)


def list_verifications(
    db: Session, user_id: UUID, execution_id: UUID
) -> list[TaskVerification]:
    _ = get_execution(db, user_id, execution_id)
    return list(
        db.scalars(
            select(TaskVerification)
            .where(
                TaskVerification.user_id == user_id,
                TaskVerification.execution_id == execution_id,
            )
            .order_by(TaskVerification.verified_at)
        ).all()
    )


def list_tools(db: Session, user_id: UUID) -> list[dict]:
    aggregate: dict[str, dict] = {}
    rows = db.execute(
        select(ToolInvocation.tool_name, ToolInvocation.status, func.count().label("total"))
        .where(ToolInvocation.user_id == user_id)
        .group_by(ToolInvocation.tool_name, ToolInvocation.status)
    ).all()
    for tool_name, status, total in rows:
        entry = aggregate.setdefault(
            tool_name, {"success": 0, "failure": 0, "last_invoked_at": None}
        )
        if status == "success":
            entry["success"] += int(total)
        else:
            entry["failure"] += int(total)
    recent_rows = list(
        db.scalars(
            select(ToolInvocation)
            .where(ToolInvocation.user_id == user_id)
            .order_by(ToolInvocation.created_at.desc())
            .limit(200)
        ).all()
    )
    recent_by_tool: dict[str, list[dict]] = {}
    for invocation in recent_rows:
        bucket = recent_by_tool.setdefault(invocation.tool_name, [])
        if len(bucket) < 3:
            bucket.append(task_monitor.invocation_payload(invocation))

    tools = []
    for spec in registry.all():
        described = spec.describe()
        described["stats"] = {
            **aggregate.get(
                spec.name, {"success": 0, "failure": 0, "last_invoked_at": None}
            ),
            "recent_invocations": recent_by_tool.get(spec.name, []),
        }
        tools.append(described)
    return tools


def analytics(db: Session, user_id: UUID) -> dict:
    approval_manager.expire_stale(db, user_id)

    def count(model, *conditions) -> int:
        return int(
            db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
        )

    def execution_count(*statuses: str) -> int:
        return count(
            AgentExecution,
            AgentExecution.user_id == user_id,
            AgentExecution.status.in_(statuses),
        )

    total_executions = count(AgentExecution, AgentExecution.user_id == user_id)
    completed = execution_count(
        state.EXECUTION_COMPLETED, state.EXECUTION_PARTIALLY_COMPLETED
    )
    failed = execution_count(state.EXECUTION_FAILED)
    terminal = execution_count(*tuple(state.EXECUTION_TERMINAL))
    active = execution_count(*tuple(state.EXECUTION_ACTIVE))
    pending_approvals = count(
        AgentApproval, AgentApproval.user_id == user_id, AgentApproval.status == "pending"
    )
    verified = count(TaskVerification, TaskVerification.user_id == user_id, TaskVerification.status == "verified")
    partial = count(
        TaskVerification,
        TaskVerification.user_id == user_id,
        TaskVerification.status == "partially_verified",
    )
    failed_verifications = count(
        TaskVerification, TaskVerification.user_id == user_id, TaskVerification.status == "failed"
    )
    invocations = db.execute(
        select(ToolInvocation.tool_name, ToolInvocation.status, func.count().label("total"))
        .where(ToolInvocation.user_id == user_id)
        .group_by(ToolInvocation.tool_name, ToolInvocation.status)
    ).all()
    tool_usage = []
    for tool_name, status, total in invocations:
        entry = next((item for item in tool_usage if item["tool_name"] == tool_name), None)
        if entry is None:
            entry = {"tool_name": tool_name, "success": 0, "failure": 0}
            tool_usage.append(entry)
        if status == "success":
            entry["success"] += int(total)
        else:
            entry["failure"] += int(total)
    tool_usage.sort(key=lambda item: (-(item["success"] + item["failure"]), item["tool_name"]))

    return {
        "total_executions": total_executions,
        "active_executions": active,
        "completed_executions": completed,
        "failed_executions": failed,
        "cancelled_executions": execution_count(state.EXECUTION_CANCELLED),
        "terminal_executions": terminal,
        "success_rate_percent": (
            round(100 * completed / terminal) if terminal else None
        ),
        "success_rate_definition": (
            "completed or partially_completed executions ÷ finished executions; "
            "null until at least one execution finishes"
        ),
        "total_plans": count(AgentPlan, AgentPlan.user_id == user_id),
        "plans_waiting_for_approval": count(
            AgentPlan, AgentPlan.user_id == user_id, AgentPlan.status == state.PLAN_APPROVED
        ),
        "pending_approvals": pending_approvals,
        "workflow_count": count(WorkflowTemplate, WorkflowTemplate.user_id == user_id),
        "suggested_workflows": count(
            WorkflowTemplate,
            WorkflowTemplate.user_id == user_id,
            WorkflowTemplate.status == "suggested",
        ),
        "verified_tasks": verified,
        "partially_verified_tasks": partial,
        "failed_verifications": failed_verifications,
        "tool_usage": tool_usage,
        "recent_tasks": task_monitor.recent_tasks(db, user_id),
        "recent_events": [
            task_monitor.event_payload(event)
            for event in event_manager.list_recent_events(db, user_id, limit=12)
        ],
    }


def recover_interrupted_executions(factory=None) -> int:
    """Mark crash-interrupted executions paused; never re-run a side effect.

    Called once at application startup. Awaiting-approval and paused runs are
    left untouched because they are already safe to resume by hand. ``factory``
    is injectable so tests can target their own database.
    """
    if not settings.agents_enabled:
        return 0
    if factory is None:
        from app.database.db import SessionLocal

        factory = SessionLocal

    db = factory()
    recovered = 0
    try:
        rows = list(
            db.scalars(
                select(AgentExecution).where(
                    AgentExecution.status.in_(
                        (state.EXECUTION_CREATED, state.EXECUTION_PLANNING, state.EXECUTION_EXECUTING)
                    )
                )
            ).all()
        )
        for execution in rows:
            execution.status = state.EXECUTION_PAUSED
            execution.pause_requested = False
            execution.error = (
                "Interrupted by an application restart. Resume to continue; completed tasks are "
                "preserved and no action is re-run automatically."
            )[:300]
            db.commit()
            execution_monitor.log(
                db,
                execution,
                "execution.recovered",
                "Execution recovered after a restart and marked paused. No task was re-run automatically.",
            )
            recovered += 1
        return recovered
    except SQLAlchemyError as error:
        db.rollback()
        logger.warning("Agent startup recovery skipped (%s).", type(error).__name__)
        return 0
    finally:
        db.close()

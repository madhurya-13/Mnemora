"""Single-task execution: allowlist check, approval, bounded retries, verification.

A task only runs through its registered tool. Arguments are validated against the
tool's Pydantic schema before execution, and the returned result is re-checked by
the verifier before the task is marked completed. Read-only tools run with a hard
timeout; side-effecting tools run inline so a timed-out worker can never commit a
write after the caller has moved on.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.agents import approval_manager, failure_recovery, result_verifier
from app.agents import execution_state as state
from app.agents.agent_schemas import AgentValidationError, ToolContext, ToolResult
from app.agents.monitoring import event_manager, execution_logger, progress_tracker
from app.agents.tool_selector import TOOL_BY_TASK_TYPE, validate_arguments
from app.agents.tools.base_tool import ToolSpec
from app.agents.tools.registry import registry
from app.config import settings
from app.models.agent import AgentExecution, AgentPlan, AgentTask, TaskVerification

COMPLETED = "completed"
AWAITING_APPROVAL = "awaiting_approval"
FAILED = "failed"


@dataclass(slots=True)
class TaskOutcome:
    outcome: str
    summary: str = ""
    verification_status: str = "pending"


def _bounded(value, *, depth: int = 0):
    if depth > 4:
        return "[depth limit]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[: settings.agent_max_result_chars]
    if isinstance(value, dict):
        return {str(k)[:60]: _bounded(v, depth=depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_bounded(item, depth=depth + 1) for item in list(value)[:40]]
    return str(value)[:240]


def _isolated(spec: ToolSpec, db: Session, context_kwargs: dict, payload):
    """Run a read-only handler in its own session so a timeout can be enforced."""
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)

    def work() -> ToolResult:
        worker_db = factory()
        try:
            return spec.handler(ToolContext(db=worker_db, **context_kwargs), payload)
        finally:
            worker_db.close()

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(work)
        try:
            return future.result(timeout=spec.timeout), True
        except FutureTimeout:
            future.cancel()
            return (
                ToolResult(
                    ok=False,
                    summary=f"The '{spec.name}' tool exceeded its {spec.timeout:g}s timeout.",
                    error="tool_timeout",
                    error_kind=failure_recovery.TIMEOUT,
                ),
                False,
            )
        except Exception as error:  # handler failure is reported, never hidden
            return (
                ToolResult(
                    ok=False,
                    summary=f"The '{spec.name}' tool raised {type(error).__name__}.",
                    error=f"{type(error).__name__}: tool failure",
                    error_kind=failure_recovery.classify(str(error)),
                ),
                False,
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def invoke(spec: ToolSpec, db: Session, context_kwargs: dict, payload) -> tuple[ToolResult, int]:
    started = time.perf_counter()
    if spec.side_effects:
        try:
            result = spec.handler(ToolContext(db=db, **context_kwargs), payload)
        except Exception as error:
            result = ToolResult(
                ok=False,
                summary=f"The '{spec.name}' tool raised {type(error).__name__}.",
                error=f"{type(error).__name__}: tool failure",
                error_kind=failure_recovery.classify(str(error)),
            )
    else:
        result, _ = _isolated(spec, db, context_kwargs, payload)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return result, duration_ms


def _upstream(db: Session, execution: AgentExecution, task: AgentTask) -> list[dict]:
    tasks = progress_tracker.tasks_for_execution(db, execution)
    upstream: list[dict] = []
    for item in tasks:
        if item.sequence >= task.sequence or item.status != "completed" or not item.result:
            continue
        result = item.result
        upstream.append(
            {
                "task_id": str(item.task_id),
                "title": item.title,
                "task_type": item.task_type,
                "status": item.status,
                "summary": result.get("summary", ""),
                "data": result.get("data", {}),
                "evidence": result.get("evidence", []),
                "verification_status": item.verification_status,
            }
        )
    return upstream


def execute_task(db: Session, execution: AgentExecution, task: AgentTask) -> TaskOutcome:
    """Run one task, persist every attempt and verify the outcome."""
    spec = registry.get(task.assigned_tool or "")
    if spec is None:
        task.status = state.TASK_FAILED
        task.error = "The assigned tool is not registered; nothing was executed."
        task.completed_at = state.utcnow()
        db.commit()
        event_manager.append_event(
            db,
            task.user_id,
            execution.execution_id,
            "task.denied",
            f"Task '{task.title}' was blocked: tool is not allowlisted.",
            task_id=task.task_id,
        )
        db.commit()
        return TaskOutcome(FAILED, task.error)

    if TOOL_BY_TASK_TYPE.get(task.task_type) != spec.name:
        task.status = state.TASK_FAILED
        task.error = "Task type and tool no longer match the allowlist."
        task.completed_at = state.utcnow()
        db.commit()
        event_manager.append_event(
            db,
            task.user_id,
            execution.execution_id,
            "task.denied",
            f"Task '{task.title}' was blocked: task type/tool mismatch.",
            task_id=task.task_id,
        )
        db.commit()
        return TaskOutcome(FAILED, task.error)

    if not spec.enabled():
        task.status = state.TASK_FAILED
        task.error = f"Tool '{spec.name}' is not configured: {spec.disabled_reason or 'unavailable'}."
        task.completed_at = state.utcnow()
        db.commit()
        execution_logger.record_invocation(
            db,
            execution.user_id,
            execution,
            task,
            tool_name=spec.name,
            arguments=task.input or {},
            result=None,
            status="denied",
            attempts=0,
            duration_ms=0,
            error=task.error,
        )
        return TaskOutcome(FAILED, task.error)

    try:
        payload = validate_arguments(spec, task.input or {})
    except AgentValidationError as error:
        task.status = state.TASK_FAILED
        task.error = str(error)[:300]
        task.completed_at = state.utcnow()
        db.commit()
        execution_logger.record_invocation(
            db,
            execution.user_id,
            execution,
            task,
            tool_name=spec.name,
            arguments=task.input or {},
            result=None,
            status="rejected",
            attempts=0,
            duration_ms=0,
            error=task.error,
        )
        event_manager.append_event(
            db,
            execution.user_id,
            execution.execution_id,
            "task.rejected",
            f"Task '{task.title}' was rejected before execution: invalid tool arguments.",
            task_id=task.task_id,
        )
        db.commit()
        return TaskOutcome(FAILED, task.error)

    if spec.requires_approval:
        if approval_manager.approved_for_task(db, execution.user_id, task) is None:
            approval_manager.request_approval(db, execution.user_id, execution, task, spec)
            return TaskOutcome(AWAITING_APPROVAL, "Waiting for explicit user approval.")
        if not approval_manager.consume_for_task(db, execution.user_id, task):
            approval_manager.request_approval(db, execution.user_id, execution, task, spec)
            return TaskOutcome(AWAITING_APPROVAL, "The previous approval expired; a new one is required.")

    task.status = state.TASK_RUNNING
    task.started_at = task.started_at or state.utcnow()
    task.error = None
    execution.current_task_id = task.task_id
    if not execution.cancel_requested and not execution.pause_requested:
        execution.status = state.EXECUTION_EXECUTING
    db.commit()
    event_manager.append_event(
        db,
        execution.user_id,
        execution.execution_id,
        "task.started",
        f"Started '{task.title}' with {spec.name}.",
        task_id=task.task_id,
        payload={"permission": spec.permission, "reversible": spec.reversible},
    )
    db.commit()

    context_kwargs = {
        "user_id": execution.user_id,
        "execution_id": execution.execution_id,
        "task_id": task.task_id,
        "task_input": dict(task.input or {}),
        "upstream_results": _upstream(db, execution, task),
        "plan_objective": (
            (plan.objective if (plan := db.get(AgentPlan, execution.plan_id)) else "")[:2000]
        ),
    }

    max_attempts = max(1, min(task.max_attempts, spec.attempts))
    attempt = 0
    result: ToolResult | None = None
    duration_ms = 0
    classification = failure_recovery.UNKNOWN
    while attempt < max_attempts:
        attempt += 1
        task.execution_attempts += 1
        db.commit()
        result, duration_ms = invoke(spec, db, context_kwargs, payload)

        execution_logger.record_invocation(
            db,
            execution.user_id,
            execution,
            task,
            tool_name=spec.name,
            arguments=task.input or {},
            result=result,
            status=(
                "success"
                if result.ok
                else "timeout"
                if result.error_kind == failure_recovery.TIMEOUT
                else "failed"
            ),
            attempts=attempt,
            duration_ms=duration_ms,
            error=result.error,
        )
        if result.ok:
            break

        classification = failure_recovery.classify(result.error, result.error_kind)
        retry = failure_recovery.should_retry(
            classification,
            attempt=attempt,
            max_attempts=max_attempts,
            side_effects=spec.side_effects,
        )
        if not retry:
            break
        event_manager.append_event(
            db,
            execution.user_id,
            execution.execution_id,
            "task.retrying",
            f"Retrying '{task.title}' after {classification} failure (attempt {attempt + 1}).",
            task_id=task.task_id,
        )
        db.commit()
        time.sleep(failure_recovery.backoff_seconds(attempt))

    assert result is not None
    if not result.ok:
        task.status = state.TASK_FAILED
        task.error = (
            result.error
            or failure_recovery.describe_failure(spec.name, classification, attempt)
        )[:300]
        task.completed_at = state.utcnow()
        task.result = {
            "tool": spec.name,
            "ok": False,
            "attempts": attempt,
            "error": task.error,
            "error_kind": classification,
            "verification_status": "failed",
            "note": "No output was invented; the failure is recorded verbatim.",
        }
        task.verification_status = "failed"
        task.verified_at = state.utcnow()
        db.add(
            TaskVerification(
                user_id=execution.user_id,
                execution_id=execution.execution_id,
                task_id=task.task_id,
                verification_type="tool_success",
                expected_result=(task.expected_output or "A successful tool result.")[:500],
                observed_result=f"The tool did not succeed: {task.error}",
                status="failed",
                evidence=[],
            )
        )
        db.commit()
        event_manager.append_event(
            db,
            execution.user_id,
            execution.execution_id,
            "task.failed",
            failure_recovery.describe_failure(spec.name, classification, attempt),
            task_id=task.task_id,
            payload={"error": task.error, "attempts": attempt},
        )
        db.commit()
        return TaskOutcome(FAILED, task.error, "failed")

    verification = result_verifier.verify(db, execution.user_id, task, spec.name, result)
    db.add(
        TaskVerification(
            user_id=execution.user_id,
            execution_id=execution.execution_id,
            task_id=task.task_id,
            verification_type=verification.verification_type,
            expected_result=verification.expected_result[:500],
            observed_result=verification.observed_result,
            status=verification.status,
            evidence=verification.evidence[:40],
        )
    )
    task.verification_status = verification.status
    task.verified_at = state.utcnow()
    task.result = _bounded(
        {
            "tool": spec.name,
            "ok": True,
            "summary": result.summary,
            "data": result.data,
            "evidence": result.evidence,
            "sources": result.sources,
            "attempts": attempt,
            "duration_ms": duration_ms,
            "verification": {
                "type": verification.verification_type,
                "status": verification.status,
                "expected": verification.expected_result,
                "observed": verification.observed_result,
                "evidence": verification.evidence,
            },
        }
    )
    task.completed_at = state.utcnow()
    task.status = state.TASK_COMPLETED
    if verification.status == "failed":
        task.status = state.TASK_FAILED
        task.error = "The tool returned a response that failed verification."[:300]
        event_type = "task.verification_failed"
        message = f"'{task.title}' returned data that failed verification; success was not claimed."
    else:
        event_type = "task.completed"
        message = f"Completed '{task.title}' and verified the result ({verification.status})."
    db.commit()
    event_manager.append_event(
        db,
        execution.user_id,
        execution.execution_id,
        event_type,
        message,
        task_id=task.task_id,
        payload={
            "verification_status": verification.status,
            "verification_type": verification.verification_type,
            "attempts": attempt,
        },
    )
    db.commit()
    return TaskOutcome(
        COMPLETED if task.status == state.TASK_COMPLETED else FAILED,
        result.summary,
        verification.status,
    )

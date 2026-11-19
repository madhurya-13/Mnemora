"""Audit log of every tool attempt with redacted arguments and bounded output."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.agent_safety import redact_arguments
from app.agents.agent_schemas import ToolResult
from app.config import settings
from app.models.agent import AgentExecution, AgentTask, ToolInvocation


def _bounded(value, *, depth: int = 0):
    """Coerce tool output into JSON-safe, size-bounded audit data."""
    if depth > 4:
        return "[depth limit]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[: settings.agent_max_result_chars]
    if isinstance(value, dict):
        return {
            str(key)[:60]: _bounded(item, depth=depth + 1)
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded(item, depth=depth + 1) for item in list(value)[:40]]
    return str(value)[:240]


def record_invocation(
    db: Session,
    user_id: UUID,
    execution: AgentExecution,
    task: AgentTask | None,
    *,
    tool_name: str,
    arguments: dict,
    result: ToolResult | None,
    status: str,
    attempts: int,
    duration_ms: int,
    error: str | None = None,
) -> ToolInvocation:
    invocation = ToolInvocation(
        user_id=user_id,
        execution_id=execution.execution_id,
        task_id=task.task_id if task is not None else None,
        tool_name=tool_name[:60],
        status=status,
        arguments=_bounded(redact_arguments(arguments or {})),
        output=_bounded(
            {
                "ok": result.ok if result else False,
                "summary": result.summary if result else "",
                "data": result.data if result else {},
                "evidence": (result.evidence if result else [])[:20],
                "sources": (result.sources if result else [])[:20],
            }
        ),
        error=(error or (result.error if result else None) or "")[:300] or None,
        attempts=max(1, attempts),
        duration_ms=max(0, min(duration_ms, 86_400_000)),
    )
    db.add(invocation)
    db.commit()
    db.refresh(invocation)
    return invocation


def recent_invocations(
    db: Session, user_id: UUID, *, limit: int = 50, execution_id: UUID | None = None
) -> list[ToolInvocation]:
    statement = select(ToolInvocation).where(ToolInvocation.user_id == user_id)
    if execution_id is not None:
        statement = statement.where(ToolInvocation.execution_id == execution_id)
    statement = statement.order_by(ToolInvocation.created_at.desc()).limit(limit)
    return list(db.scalars(statement).all())

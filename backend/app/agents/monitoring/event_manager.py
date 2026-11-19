"""Append-only execution events with per-execution sequence numbers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.execution_state import utcnow
from app.models.agent import ExecutionEvent


def append_event(
    db: Session,
    user_id: UUID,
    execution_id: UUID,
    event_type: str,
    message: str,
    *,
    task_id: UUID | None = None,
    payload: dict | None = None,
) -> ExecutionEvent:
    current = db.scalar(
        select(func.max(ExecutionEvent.sequence)).where(ExecutionEvent.execution_id == execution_id)
    ) or 0
    event = ExecutionEvent(
        user_id=user_id,
        execution_id=execution_id,
        task_id=task_id,
        event_type=event_type,
        message=message[:500],
        payload=payload or {},
        sequence=current + 1,
        created_at=utcnow(),
    )
    db.add(event)
    db.flush()
    return event


def list_events(
    db: Session, user_id: UUID, execution_id: UUID, *, limit: int = 200, offset: int = 0
) -> list[ExecutionEvent]:
    return list(
        db.scalars(
            select(ExecutionEvent)
            .where(
                ExecutionEvent.user_id == user_id,
                ExecutionEvent.execution_id == execution_id,
            )
            .order_by(ExecutionEvent.sequence)
            .limit(limit)
            .offset(offset)
        ).all()
    )


def list_recent_events(db: Session, user_id: UUID, *, limit: int = 20) -> list[ExecutionEvent]:
    return list(
        db.scalars(
            select(ExecutionEvent)
            .where(ExecutionEvent.user_id == user_id)
            .order_by(ExecutionEvent.created_at.desc(), ExecutionEvent.sequence.desc())
            .limit(limit)
        ).all()
    )

"""Classify memory changes and expose a readable evolution timeline."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.memory import Memory, MemoryHistory

_CHANGE_MARKERS = re.compile(
    r"\b(now|instead|no longer|changed|shifted|switched|started|stopped|currently|used to)\b",
    re.I,
)
_CONTRADICTION_MARKERS = re.compile(
    r"\b(not|never|disagree|wrong|incorrect|but|however|actually)\b",
    re.I,
)

CHANGE_TYPES = {
    "new_information",
    "preference_modification",
    "goal_modification",
    "project_status_change",
    "outdated_information",
    "contradictory_information",
    "temporary_change",
    "confirmed_replacement",
    "user_update",
    "conflict_resolution",
    "duplicate_merge",
}


def classify_change(
    previous_content: str,
    new_content: str,
    category: str,
    *,
    reason: str = "user_update",
) -> str:
    """Conservatively classify a change without claiming certainty about intent."""
    if reason == "duplicate_merge":
        return "duplicate_merge"
    if reason == "conflict_resolution":
        return "confirmed_replacement"
    text = new_content.strip()
    lowered = text.casefold()
    if " ".join(previous_content.split()).casefold() == " ".join(text.split()).casefold():
        return "user_update"
    if "no longer" in lowered or "not anymore" in lowered or "stopped" in lowered:
        return "outdated_information"
    if _CHANGE_MARKERS.search(text):
        if category == "preferences":
            return "preference_modification"
        if category == "goals":
            return "goal_modification"
        if category == "projects":
            return "project_status_change"
        if category == "temporary":
            return "temporary_change"
        return "confirmed_replacement"
    if category == "temporary":
        return "temporary_change"
    if category == "preferences":
        return "preference_modification"
    if _CONTRADICTION_MARKERS.search(text):
        return "contradictory_information"
    if " ".join(previous_content.split()).casefold() != " ".join(text.split()).casefold():
        return "new_information"
    return "user_update"


def _ordered_history(
    db: Session, user_id: UUID, memory_id: UUID | None = None, *, limit: int = 200
) -> list[MemoryHistory]:
    predicates = [MemoryHistory.user_id == user_id]
    if memory_id is not None:
        predicates.append(MemoryHistory.memory_id == memory_id)
    rows = db.scalars(
        select(MemoryHistory).where(*predicates).order_by(MemoryHistory.created_at.asc())
    ).all()
    return list(rows)[-limit:]


def evolution_timeline(
    db: Session,
    user_id: UUID,
    *,
    memory_id: UUID | None = None,
    change_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    history = _ordered_history(db, user_id, memory_id)
    if not history:
        return []
    memory_ids = {row.memory_id for row in history}
    memories = {
        memory.memory_id: memory
        for memory in db.scalars(
            select(Memory).where(Memory.user_id == user_id, Memory.memory_id.in_(memory_ids))
        ).all()
    }
    by_memory: dict[UUID, list[MemoryHistory]] = {}
    for row in history:
        by_memory.setdefault(row.memory_id, []).append(row)

    items: list[dict] = []
    for owner_id, rows in by_memory.items():
        current = memories.get(owner_id)
        for index, row in enumerate(rows):
            following = rows[index + 1] if index + 1 < len(rows) else None
            new_content = following.content if following is not None else (current.content if current else None)
            if new_content is None:
                continue
            if " ".join(row.content.split()) == " ".join(new_content.split()):
                continue
            if change_type is not None and row.change_type != change_type:
                continue
            items.append({
                "memory_id": owner_id,
                "previous_content": row.content,
                "new_content": new_content,
                "change_type": row.change_type,
                "change_reason": row.change_reason,
                "source_conversation_id": row.source_conversation_id,
                "approval_status": (following.approval_status if following is not None else (current.approval_status if current else row.approval_status)),
                "changed_at": (following.created_at if following is not None else (current.updated_at if current else row.created_at)),
            })
    items.sort(key=lambda item: item["changed_at"], reverse=True)
    return items[:limit]


def change_types_for_display(rows: Iterable[MemoryHistory]) -> list[str]:
    return sorted({row.change_type for row in rows})

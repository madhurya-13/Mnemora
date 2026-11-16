"""Documented, configurable memory utility scoring and category-aware decay."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.adaptive import AdaptiveSettings, MemoryFeedback
from app.models.memory import Memory, MemoryRetrievalEvent, MemoryRetrievalItem
from app.retrieval.recency import half_life_days, recency_score

# Utility is normalized to 0..1. Weights sum to 1.0 before the outdated penalty.
UTILITY_WEIGHTS = {
    "importance": 0.25,
    "confidence": 0.20,
    "usage": 0.20,
    "recency": 0.15,
    "feedback": 0.10,
    "explicit_approval": 0.10,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _usage_score(count: int) -> float:
    return min(1.0, math.log1p(max(0, count)) / math.log(11))


def _feedback_score(positive: int, negative: int) -> float:
    # Laplace-smoothed; no feedback is neutral rather than negative.
    return (positive + 1.0) / (positive + negative + 2.0)


def _outdated_penalty(memory: Memory, now: datetime) -> float:
    if memory.memory_type != "temporary" and memory.category not in {"temporary", "projects", "goals"}:
        return 0.0
    age_days = max(0.0, (now - memory.updated_at).total_seconds() / 86400)
    horizon = max(1, half_life_days(memory.category, memory.memory_type))
    if age_days <= horizon:
        return 0.0
    return min(0.20, 0.20 * min(1.0, age_days / (horizon * 2)))


def calculate_utility(
    memory: Memory,
    *,
    usage_count: int = 0,
    positive_feedback: int = 0,
    negative_feedback: int = 0,
    now: datetime | None = None,
) -> float:
    """Return a transparent 0..1 utility score.

    The score combines importance, confidence, retrieval usage, category-aware recency,
    feedback sentiment and explicit approval. Old temporary/project/goal memories receive
    at most a 0.20 penalty; the score never deletes or rewrites a memory.
    """
    current = now or _utcnow()
    components = {
        "importance": max(0.0, min(1.0, memory.importance)),
        "confidence": max(0.0, min(1.0, memory.confidence)),
        "usage": _usage_score(usage_count),
        "recency": recency_score(memory.updated_at, memory.category, memory.memory_type, now=current),
        "feedback": _feedback_score(positive_feedback, negative_feedback),
        "explicit_approval": 1.0 if memory.approval_status == "approved" else 0.5,
    }
    score = sum(UTILITY_WEIGHTS[key] * value for key, value in components.items())
    return max(0.0, min(1.0, score - _outdated_penalty(memory, current)))


def _feedback_counts(db: Session, user_id: UUID) -> dict[str, dict[str, int]]:
    rows = db.scalars(select(MemoryFeedback).where(MemoryFeedback.user_id == user_id)).all()
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        ids = set(row.memory_ids or [])
        if row.target_type == "memory":
            ids.add(str(row.target_id))
        positive = row.feedback_type in {"helpful", "correct_personalization", "correct", "important"}
        negative = row.feedback_type in {
            "not_helpful", "incorrect_personalization", "outdated_information",
            "irrelevant_memory", "incorrect", "no_longer_relevant", "not_important",
        }
        for memory_id in ids:
            bucket = counts.setdefault(memory_id, {"positive": 0, "negative": 0})
            if positive:
                bucket["positive"] += 1
            elif negative:
                bucket["negative"] += 1
    return counts


def _usage_counts(db: Session, user_id: UUID) -> dict[str, int]:
    rows = db.execute(
        select(MemoryRetrievalItem.memory_id, func.count(MemoryRetrievalItem.item_id))
        .join(MemoryRetrievalEvent, MemoryRetrievalEvent.event_id == MemoryRetrievalItem.event_id)
        .where(MemoryRetrievalEvent.user_id == user_id, MemoryRetrievalItem.selected.is_(True))
        .group_by(MemoryRetrievalItem.memory_id)
    ).all()
    return {str(memory_id): int(count) for memory_id, count in rows}


def apply_lifecycle(memory: Memory, utility: float, *, now: datetime | None = None) -> None:
    """Move an approved memory between non-destructive lifecycle states."""
    current = now or _utcnow()
    memory.utility_score = round(utility, 4)
    memory.last_evaluated_at = current
    if memory.approval_status != "approved":
        return
    if memory.lifecycle_status in {"archived", "superseded"}:
        return
    if memory.expires_at is not None and memory.expires_at <= current:
        memory.lifecycle_status = "expired"
        return
    age_days = max(0.0, (current - memory.updated_at).total_seconds() / 86400)
    horizon = max(1, half_life_days(memory.category, memory.memory_type))
    if utility < settings.adaptive_outdated_utility_threshold and age_days >= horizon * settings.adaptive_outdated_age_multiplier:
        memory.lifecycle_status = "possibly_outdated"
    # Explicit review states are intentionally not auto-cleared. A user or a newer
    # confirmed update decides when a flagged memory becomes active again.


def evaluate_user(db: Session, user_id: UUID, *, settings_row: AdaptiveSettings | None = None) -> int:
    """Recompute utility and lifecycle for every memory owned by this user."""
    if settings_row is not None and not settings_row.memory_decay_enabled:
        return 0
    memories = db.scalars(select(Memory).where(Memory.user_id == user_id)).all()
    usage = _usage_counts(db, user_id)
    feedback = _feedback_counts(db, user_id)
    now = _utcnow()
    for memory in memories:
        memory_id = str(memory.memory_id)
        counts = feedback.get(memory_id, {"positive": 0, "negative": 0})
        utility = calculate_utility(
            memory,
            usage_count=usage.get(memory_id, 0),
            positive_feedback=counts["positive"],
            negative_feedback=counts["negative"],
            now=now,
        )
        apply_lifecycle(memory, utility, now=now)
    db.commit()
    return len(memories)


def memory_health(db: Session, user_id: UUID) -> dict[str, Any]:
    memories = db.scalars(select(Memory).where(Memory.user_id == user_id)).all()
    approved = [memory for memory in memories if memory.approval_status == "approved"]
    counts: dict[str, int] = {}
    for memory in approved:
        counts[memory.lifecycle_status] = counts.get(memory.lifecycle_status, 0) + 1
    usage = _usage_counts(db, user_id)
    frequently_used = sorted(
        (
            {
                "memory_id": str(memory.memory_id),
                "content": memory.content,
                "category": memory.category,
                "usage_count": usage.get(str(memory.memory_id), 0),
                "utility_score": memory.utility_score,
            }
            for memory in approved
        ),
        key=lambda item: (item["usage_count"], item["utility_score"]),
        reverse=True,
    )[:5]
    last_evaluated = max(
        (memory.last_evaluated_at for memory in memories if memory.last_evaluated_at is not None),
        default=None,
    )
    return {
        "total_approved": len(approved),
        "active": counts.get("active", 0),
        "possibly_outdated": counts.get("possibly_outdated", 0),
        "superseded": counts.get("superseded", 0),
        "expired": counts.get("expired", 0),
        "archived": counts.get("archived", 0),
        "pending_review": counts.get("pending_review", 0),
        "low_utility": sum(1 for memory in approved if memory.utility_score < settings.adaptive_outdated_utility_threshold),
        "frequently_used": frequently_used,
        "last_evaluated_at": last_evaluated,
    }

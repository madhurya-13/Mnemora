"""Orchestrate post-turn adaptive learning without blocking the chat response."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.message import Message
from app.services.adaptive_memory import memory_decay, pattern_detector, preference_learner
from app.services.adaptive_memory.adaptive_settings import get_adaptive_settings


def observe_turn(
    db: Session,
    user_id: UUID,
    *,
    conversation_id: UUID | None,
    user_message_id: UUID,
    assistant_message_id: UUID,
) -> dict[str, int]:
    """Run cheap, deterministic learning for one completed turn."""
    row = get_adaptive_settings(db, user_id)
    user_message = db.get(Message, user_message_id)
    if user_message is None or user_message.role != "user":
        return {"preferences": 0, "patterns": 0, "memories": 0}
    del assistant_message_id  # Idempotency is enforced by the durable job row.

    preferences = 0
    if row.preference_learning_enabled and row.auto_candidate_generation:
        preferences = preference_learner.learn_from_message(
            db, user_id, user_message.content,
            conversation_id=conversation_id,
            message_id=user_message_id,
            confidence_threshold=row.preference_confidence_threshold,
            evidence_threshold=row.preference_evidence_threshold,
            require_user_review=row.require_user_review,
        )
    patterns = 0
    if row.pattern_detection_enabled:
        patterns = pattern_detector.detect_patterns(
            db, user_id, evidence_threshold=row.pattern_evidence_threshold,
        )
    memories = memory_decay.evaluate_user(db, user_id, settings_row=row)
    return {"preferences": preferences, "patterns": patterns, "memories": memories}


def evaluate_user(db: Session, user_id: UUID) -> int:
    return memory_decay.evaluate_user(db, user_id, settings_row=get_adaptive_settings(db, user_id))

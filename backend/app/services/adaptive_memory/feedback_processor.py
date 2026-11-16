"""Store explicit feedback and apply conservative, reversible relevance signals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.adaptive import MemoryFeedback, UserPreference
from app.models.conversation import Conversation
from app.models.memory import Memory, MemoryRetrievalEvent, MemoryRetrievalItem
from app.models.message import Message
from app.schemas.adaptive import FeedbackCreateRequest
from app.services.adaptive_memory import memory_decay


class FeedbackNotFoundError(LookupError):
    pass


class FeedbackConflictError(RuntimeError):
    pass


class FeedbackValidationError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _owned_message(db: Session, user_id: UUID, message_id: UUID) -> Message | None:
    return db.scalar(
        select(Message)
        .join(Conversation, Conversation.conversation_id == Message.conversation_id)
        .where(Message.message_id == message_id, Conversation.user_id == user_id)
    )


def _latest_retrieval_memory_ids(db: Session, user_id: UUID) -> list[str]:
    cutoff = _utcnow() - timedelta(minutes=settings.adaptive_feedback_context_window_minutes)
    event = db.scalar(
        select(MemoryRetrievalEvent)
        .where(MemoryRetrievalEvent.user_id == user_id, MemoryRetrievalEvent.created_at >= cutoff)
        .order_by(MemoryRetrievalEvent.created_at.desc())
        .limit(1)
    )
    if event is None:
        return []
    return [
        str(memory_id)
        for memory_id in db.scalars(select(MemoryRetrievalItem.memory_id).where(
            MemoryRetrievalItem.event_id == event.event_id,
            MemoryRetrievalItem.selected.is_(True),
        )).all()
    ]


def _validate_target(db: Session, user_id: UUID, payload: FeedbackCreateRequest) -> None:
    if payload.target_type == "response":
        message = _owned_message(db, user_id, payload.target_id)
        if message is None:
            raise FeedbackNotFoundError
        if message.role != "assistant":
            raise FeedbackValidationError("Response feedback must target an assistant message.")
        if payload.conversation_id is not None and message.conversation_id != payload.conversation_id:
            raise FeedbackValidationError("The message does not belong to that conversation.")
    elif payload.target_type == "memory":
        owned = db.scalar(select(Memory.memory_id).where(
            Memory.memory_id == payload.target_id, Memory.user_id == user_id,
        ))
        if owned is None:
            raise FeedbackNotFoundError
    else:
        owned = db.scalar(select(UserPreference.preference_id).where(
            UserPreference.preference_id == payload.target_id, UserPreference.user_id == user_id,
        ))
        if owned is None:
            raise FeedbackNotFoundError

    if payload.memory_ids:
        found = set(db.scalars(select(Memory.memory_id).where(
            Memory.user_id == user_id, Memory.memory_id.in_(payload.memory_ids),
        )).all())
        if found != set(payload.memory_ids):
            raise FeedbackNotFoundError
    if payload.preference_ids:
        found = set(db.scalars(select(UserPreference.preference_id).where(
            UserPreference.user_id == user_id, UserPreference.preference_id.in_(payload.preference_ids),
        )).all())
        if found != set(payload.preference_ids):
            raise FeedbackNotFoundError


def _apply(
    db: Session,
    user_id: UUID,
    *,
    feedback_type: str,
    target_type: str,
    target_id: UUID,
    memory_ids: list[UUID],
    preference_ids: list[UUID],
) -> None:
    positive = feedback_type in {"helpful", "correct_personalization", "correct", "important"}
    negative = feedback_type in {
        "not_helpful", "incorrect_personalization", "irrelevant_memory",
        "incorrect", "not_important", "outdated_information", "no_longer_relevant",
    }
    if target_type == "memory":
        memory_ids = list(dict.fromkeys([*memory_ids, target_id]))
    if target_type == "preference":
        preference_ids = list(dict.fromkeys([*preference_ids, target_id]))

    for memory_id in memory_ids:
        memory = db.scalar(select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user_id))
        if memory is None:
            continue
        if feedback_type in {"outdated_information", "no_longer_relevant"}:
            memory.lifecycle_status = "possibly_outdated"
        elif feedback_type == "update_requested":
            memory.lifecycle_status = "pending_review"
        elif positive:
            memory.confidence = min(1.0, round(memory.confidence + 0.02, 4))
            memory.importance = min(1.0, round(memory.importance + 0.02, 4))
        elif negative:
            memory.confidence = max(0.0, round(memory.confidence - 0.03, 4))
            memory.importance = max(0.0, round(memory.importance - 0.02, 4))

    for preference_id in preference_ids:
        preference = db.scalar(select(UserPreference).where(
            UserPreference.preference_id == preference_id,
            UserPreference.user_id == user_id,
        ))
        if preference is None:
            continue
        if positive:
            preference.confidence = min(0.95, round(preference.confidence + 0.03, 4))
        elif negative:
            preference.confidence = max(0.15, round(preference.confidence - 0.05, 4))
            if preference.confidence < 0.35 and preference.status == "confirmed":
                preference.status = "candidate"
        preference.updated_at = _utcnow()


def submit_feedback(db: Session, user_id: UUID, payload: FeedbackCreateRequest) -> MemoryFeedback:
    _validate_target(db, user_id, payload)
    duplicate = db.scalar(select(MemoryFeedback).where(
        MemoryFeedback.user_id == user_id,
        MemoryFeedback.target_type == payload.target_type,
        MemoryFeedback.target_id == payload.target_id,
        MemoryFeedback.feedback_type == payload.feedback_type,
    ))
    if duplicate is not None:
        raise FeedbackConflictError("This feedback has already been recorded.")
    memory_ids = list(payload.memory_ids)
    if payload.target_type == "memory":
        memory_ids = list(dict.fromkeys([*memory_ids, payload.target_id]))
    if not memory_ids and payload.target_type == "response":
        memory_ids = [UUID(value) for value in _latest_retrieval_memory_ids(db, user_id)]
    feedback = MemoryFeedback(
        user_id=user_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        feedback_type=payload.feedback_type,
        comment=payload.comment.strip() if payload.comment else None,
        memory_ids=[str(item) for item in memory_ids],
        preference_ids=[str(item) for item in payload.preference_ids],
        conversation_id=payload.conversation_id,
        message_id=payload.message_id or (payload.target_id if payload.target_type == "response" else None),
        processed=True,
    )
    db.add(feedback)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise FeedbackConflictError("This feedback has already been recorded.") from error
    _apply(
        db, user_id,
        feedback_type=payload.feedback_type,
        target_type=payload.target_type,
        target_id=payload.target_id,
        memory_ids=memory_ids,
        preference_ids=list(payload.preference_ids),
    )
    db.commit()
    db.refresh(feedback)
    memory_decay.evaluate_user(db, user_id)
    db.refresh(feedback)
    return feedback


def list_feedback(
    db: Session, user_id: UUID, *, limit: int = 50, offset: int = 0, feedback_type: str | None = None
) -> tuple[list[MemoryFeedback], int]:
    predicates = [MemoryFeedback.user_id == user_id]
    if feedback_type:
        predicates.append(MemoryFeedback.feedback_type == feedback_type)
    rows = db.scalars(
        select(MemoryFeedback).where(*predicates).order_by(MemoryFeedback.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    from sqlalchemy import func
    total = db.scalar(select(func.count(MemoryFeedback.feedback_id)).where(*predicates)) or 0
    return list(rows), int(total)


def insights(db: Session, user_id: UUID) -> dict:
    rows = list(db.scalars(select(MemoryFeedback).where(
        MemoryFeedback.user_id == user_id,
    ).order_by(MemoryFeedback.created_at.desc())).all())
    by_type: dict[str, int] = {}
    for row in rows:
        by_type[row.feedback_type] = by_type.get(row.feedback_type, 0) + 1
    return {
        "total": len(rows),
        "helpful_count": by_type.get("helpful", 0),
        "not_helpful_count": by_type.get("not_helpful", 0),
        "incorrect_personalization_count": by_type.get("incorrect_personalization", 0),
        "outdated_information_count": by_type.get("outdated_information", 0),
        "correction_requests": by_type.get("update_requested", 0),
        "by_type": by_type,
        "recent": rows[:10],
    }

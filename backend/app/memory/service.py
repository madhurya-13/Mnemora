"""Relational memory lifecycle, vector outbox reconciliation and user-scoped search."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database.db import SessionLocal
from app.memory import embeddings, vector_store
from app.memory.safety import contains_sensitive_information
from app.models.memory import (
    Memory, MemoryConflict, MemoryExtractionJob, MemoryHistory,
    MemoryRetrievalEvent, MemoryRetrievalItem, MemoryVectorOutbox,
)
from app.retrieval.conflict_detector import detect_conflict
from app.schemas.memory import MemoryCandidate, MemoryCreateRequest, MemorySearchResult

logger = logging.getLogger(__name__)


class MemoryNotFoundError(LookupError):
    pass


class MemoryConflictError(RuntimeError):
    pass


class MemoryUnsafeContentError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _source_ids(memory: Memory) -> set[str]:
    return set(memory.source_message_ids or [])


def _enqueue(db: Session, memory: Memory, operation: str = "upsert") -> None:
    memory.vector_sync_status = "pending"
    db.add(MemoryVectorOutbox(memory_id=memory.memory_id, user_id=memory.user_id, operation=operation))


def _record_history(db: Session, memory: Memory, reason: str) -> None:
    db.add(MemoryHistory(
        memory_id=memory.memory_id, user_id=memory.user_id, content=memory.content,
        category=memory.category, importance=memory.importance, confidence=memory.confidence,
        memory_type=memory.memory_type, approval_status=memory.approval_status,
        change_reason=reason,
    ))


async def _semantic_duplicate(db: Session, user_id: UUID, content: str) -> tuple[Memory | None, float | None]:
    """Find only approved, synced memories belonging to this user."""
    candidates = db.scalars(select(Memory).where(
        Memory.user_id == user_id,
        Memory.approval_status.in_(("approved", "pending")),
    )).all()
    normalized = _norm(content)
    exact = next((row for row in candidates if _norm(row.content) == normalized), None)
    if exact is not None:
        return exact, 1.0
    approved = [row for row in candidates if row.approval_status == "approved" and row.vector_sync_status == "synced"]
    if not approved:
        return None, None
    try:
        query_embedding = await embeddings.embed_text(content)
        matches = await asyncio.to_thread(
            vector_store.query_user,
            user_id,
            query_embedding,
            limit=min(settings.memory_top_k, max(len(approved), 1)),
        )
    except (embeddings.EmbeddingConfigurationError, embeddings.EmbeddingServiceError, vector_store.VectorStoreError):
        logger.info("Semantic duplicate check unavailable; candidate remains subject to user review.")
        return None, None
    for match in matches:
        similarity = max(0.0, min(1.0, 1.0 - match["distance"]))
        if similarity >= settings.memory_similarity_threshold:
            row = next((item for item in approved if str(item.memory_id) == match["id"]), None)
            if row is not None:
                return row, similarity
    return None, None


async def add_candidate(
    db: Session,
    user_id: UUID,
    candidate: MemoryCandidate | MemoryCreateRequest,
    *,
    source: str,
    source_conversation_id: UUID | None = None,
    source_message_ids: list[UUID] | None = None,
    auto_save: bool = False,
) -> Memory:
    content = " ".join(candidate.content.split()).strip()
    if contains_sensitive_information(content):
        raise MemoryUnsafeContentError("This memory contains sensitive information and cannot be stored.")

    conversation_id = source_conversation_id or getattr(candidate, "source_conversation_id", None)
    message_ids = [str(item) for item in (source_message_ids or getattr(candidate, "source_message_ids", []))]
    duplicate, similarity = await _semantic_duplicate(db, user_id, content)
    approved_rows = db.scalars(select(Memory).where(
        Memory.user_id == user_id, Memory.approval_status == "approved",
    )).all()
    assessments = [
        (row, detect_conflict(
            row, content, candidate.category,
            semantic_similarity=similarity if duplicate is not None and row.memory_id == duplicate.memory_id else None,
        ))
        for row in approved_rows
    ]
    assessments = [(row, assessment) for row, assessment in assessments if assessment is not None]
    conflict_pair = assessments[0] if assessments else None

    if duplicate is not None and duplicate.approval_status == "pending":
        return duplicate
    if duplicate is not None and auto_save and conflict_pair is None:
        duplicate.updated_at = _now()
        duplicate.source_message_ids = sorted(_source_ids(duplicate) | set(message_ids))
        if conversation_id and duplicate.source_conversation_id is None:
            duplicate.source_conversation_id = conversation_id
        _enqueue(db, duplicate)
        db.commit()
        db.refresh(duplicate)
        return duplicate

    can_auto_approve = (
        auto_save
        and duplicate is None
        and candidate.explicit
        and candidate.confidence >= 0.8
        and candidate.importance >= settings.memory_min_importance
        and embeddings.is_configured()
        and conflict_pair is None
        and not contains_sensitive_information(content)
    )
    memory = Memory(
        user_id=user_id,
        content=content,
        category=candidate.category,
        importance=candidate.importance,
        confidence=candidate.confidence,
        memory_type=candidate.memory_type,
        source=source,
        source_conversation_id=conversation_id,
        source_message_ids=message_ids,
        approval_status="approved" if can_auto_approve else "pending",
        similar_memory_id=duplicate.memory_id if duplicate is not None else None,
        vector_sync_status="pending" if can_auto_approve else "not_required",
        expires_at=_now() + timedelta(days=settings.memory_temporary_ttl_days) if candidate.memory_type == "temporary" else None,
    )
    db.add(memory)
    db.flush()
    for existing, assessment in assessments:
        db.add(MemoryConflict(
            user_id=user_id, existing_memory_id=existing.memory_id, new_memory_id=memory.memory_id,
            conflict_type=assessment.conflict_type, status="unresolved", summary=assessment.summary,
        ))
    if can_auto_approve:
        _enqueue(db, memory)
    db.commit()
    db.refresh(memory)
    return memory


async def approve_memory(db: Session, user_id: UUID, memory_id: UUID) -> Memory:
    memory = db.scalar(select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user_id))
    if memory is None:
        raise MemoryNotFoundError
    if memory.approval_status != "pending":
        raise MemoryConflictError("Only pending memories can be approved.")
    unresolved = db.scalar(select(MemoryConflict.conflict_id).where(
        MemoryConflict.user_id == user_id, MemoryConflict.new_memory_id == memory_id,
        MemoryConflict.status == "unresolved",
    ))
    if memory.similar_memory_id:
        canonical = db.scalar(select(Memory).where(
            Memory.memory_id == memory.similar_memory_id,
            Memory.user_id == user_id,
            Memory.approval_status == "approved",
        ))
        if canonical is not None:
            if unresolved:
                conflict = db.get(MemoryConflict, unresolved)
                if conflict is not None and conflict.conflict_type != "possible_duplicate":
                    raise MemoryConflictError("Resolve the related memory conflict before approving this memory.")
                if conflict is not None:
                    conflict.status = "resolved_updated"
                    conflict.resolution = "accept_update"
                    conflict.resolved_at = _now()
            _record_history(db, canonical, "duplicate_merge")
            canonical.source_message_ids = sorted(_source_ids(canonical) | _source_ids(memory))
            if canonical.source_conversation_id is None:
                canonical.source_conversation_id = memory.source_conversation_id
            canonical.updated_at = _now()
            _enqueue(db, canonical)
            db.delete(memory)
            db.commit()
            db.refresh(canonical)
            return canonical
    if unresolved:
        raise MemoryConflictError("Resolve the related memory conflict before approving this memory.")
    memory.approval_status = "approved"
    _enqueue(db, memory)
    db.commit()
    db.refresh(memory)
    return memory


def reject_memory(db: Session, user_id: UUID, memory_id: UUID) -> Memory:
    memory = db.scalar(select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user_id))
    if memory is None:
        raise MemoryNotFoundError
    if memory.approval_status != "pending":
        raise MemoryConflictError("Only pending memories can be rejected.")
    memory.approval_status = "rejected"
    memory.vector_sync_status = "not_required"
    memory.updated_at = _now()
    conflicts = db.scalars(select(MemoryConflict).where(
        MemoryConflict.user_id == user_id, MemoryConflict.new_memory_id == memory_id,
        MemoryConflict.status == "unresolved",
    )).all()
    for conflict in conflicts:
        conflict.status = "resolved_kept"
        conflict.resolution = "keep_existing"
        conflict.resolved_at = _now()
    db.commit()
    db.refresh(memory)
    return memory


def resolve_conflict(
    db: Session,
    user_id: UUID,
    conflict_id: UUID,
    *,
    resolution: str,
    edited_content: str | None = None,
) -> tuple[MemoryConflict, Memory]:
    conflict = db.scalar(select(MemoryConflict).where(
        MemoryConflict.conflict_id == conflict_id, MemoryConflict.user_id == user_id,
    ))
    if conflict is None:
        raise MemoryNotFoundError
    if conflict.status != "unresolved":
        raise MemoryConflictError("This memory conflict has already been resolved.")
    if resolution == "keep_unresolved":
        existing = db.scalar(select(Memory).where(Memory.memory_id == conflict.existing_memory_id, Memory.user_id == user_id))
        return conflict, existing
    existing = db.scalar(select(Memory).where(Memory.memory_id == conflict.existing_memory_id, Memory.user_id == user_id))
    candidate = db.scalar(select(Memory).where(Memory.memory_id == conflict.new_memory_id, Memory.user_id == user_id))
    if existing is None or candidate is None:
        raise MemoryNotFoundError
    now = _now()
    if resolution == "keep_existing":
        candidate.approval_status = "rejected"
        candidate.vector_sync_status = "not_required"
        candidate.updated_at = now
        conflict.status = "resolved_kept"
    elif resolution in {"accept_update", "edit"}:
        content = edited_content if resolution == "edit" else candidate.content
        if not content or contains_sensitive_information(content):
            raise MemoryUnsafeContentError("The updated memory is blank or contains sensitive information.")
        _record_history(db, existing, "conflict_resolution")
        existing.content = content
        existing.category = candidate.category
        existing.importance = candidate.importance
        existing.confidence = candidate.confidence
        existing.memory_type = candidate.memory_type
        existing.updated_at = now
        existing.source_message_ids = sorted(_source_ids(existing) | _source_ids(candidate))
        if existing.source_conversation_id is None:
            existing.source_conversation_id = candidate.source_conversation_id
        candidate.approval_status = "rejected"
        candidate.vector_sync_status = "not_required"
        candidate.updated_at = now
        _enqueue(db, existing)
        conflict.status = "resolved_updated"
    else:
        raise MemoryConflictError("Unsupported conflict resolution.")
    conflict.resolution = resolution
    conflict.resolved_at = now
    db.commit()
    db.refresh(conflict)
    db.refresh(existing)
    return conflict, existing


def memory_history(db: Session, user_id: UUID, memory_id: UUID) -> list[MemoryHistory]:
    owned = db.scalar(select(Memory.memory_id).where(Memory.memory_id == memory_id, Memory.user_id == user_id))
    if owned is None:
        raise MemoryNotFoundError
    return list(db.scalars(select(MemoryHistory).where(
        MemoryHistory.memory_id == memory_id, MemoryHistory.user_id == user_id,
    ).order_by(MemoryHistory.created_at.desc())))


def retrieval_stats(db: Session, user_id: UUID) -> dict[str, Any]:
    events = db.scalars(select(MemoryRetrievalEvent).where(
        MemoryRetrievalEvent.user_id == user_id,
    ).order_by(MemoryRetrievalEvent.created_at.desc()).limit(10)).all()
    totals = db.execute(select(
        func.count(MemoryRetrievalEvent.event_id),
        func.coalesce(func.sum(MemoryRetrievalEvent.selected_count), 0),
        func.coalesce(func.sum(MemoryRetrievalEvent.excluded_count), 0),
        func.coalesce(func.avg(MemoryRetrievalEvent.latency_ms), 0),
    ).where(MemoryRetrievalEvent.user_id == user_id)).one()
    category_rows = db.execute(
        select(Memory.category, func.count(MemoryRetrievalItem.item_id))
        .join(MemoryRetrievalItem, MemoryRetrievalItem.memory_id == Memory.memory_id)
        .join(MemoryRetrievalEvent, MemoryRetrievalEvent.event_id == MemoryRetrievalItem.event_id)
        .where(MemoryRetrievalEvent.user_id == user_id, MemoryRetrievalItem.selected.is_(True))
        .group_by(Memory.category)
    ).all()
    frequent_ids = db.execute(
        select(MemoryRetrievalItem.memory_id, func.count(MemoryRetrievalItem.item_id).label("uses"))
        .join(MemoryRetrievalEvent, MemoryRetrievalEvent.event_id == MemoryRetrievalItem.event_id)
        .where(MemoryRetrievalEvent.user_id == user_id, MemoryRetrievalItem.selected.is_(True))
        .group_by(MemoryRetrievalItem.memory_id).order_by(func.count(MemoryRetrievalItem.item_id).desc()).limit(5)
    ).all()
    frequent = [db.scalar(select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user_id)) for memory_id, _ in frequent_ids]
    recently_accessed = db.scalars(select(Memory).where(
        Memory.user_id == user_id, Memory.approval_status == "approved", Memory.last_accessed_at.is_not(None),
    ).order_by(Memory.last_accessed_at.desc()).limit(5)).all()
    high_importance = db.scalars(select(Memory).where(
        Memory.user_id == user_id, Memory.approval_status == "approved",
    ).order_by(Memory.importance.desc(), Memory.updated_at.desc()).limit(5)).all()
    return {
        "retrieval_count": int(totals[0] or 0), "selected_count": int(totals[1] or 0),
        "excluded_count": int(totals[2] or 0), "average_latency_ms": float(totals[3] or 0),
        "recently_retrieved": [item for item in frequent if item is not None],
        "recently_accessed": list(recently_accessed),
        "high_importance": list(high_importance),
        "category_distribution": dict(category_rows), "recent_events": list(events),
    }


def update_memory(db: Session, user_id: UUID, memory_id: UUID, changes: dict[str, Any]) -> Memory:
    memory = db.scalar(select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user_id))
    if memory is None:
        raise MemoryNotFoundError
    if "content" in changes and contains_sensitive_information(changes["content"]):
        raise MemoryUnsafeContentError("This memory contains sensitive information and cannot be stored.")
    _record_history(db, memory, "user_update")
    for field, value in changes.items():
        if value is not None:
            setattr(memory, field, value)
    memory.updated_at = _now()
    if memory.approval_status == "approved":
        _enqueue(db, memory)
    db.commit()
    db.refresh(memory)
    return memory


async def delete_memory(db: Session, user_id: UUID, memory_id: UUID) -> bool:
    memory = db.scalar(select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user_id))
    if memory is None:
        raise MemoryNotFoundError
    needs_vector_delete = memory.approval_status == "approved" or memory.vector_sync_status in {"pending", "synced", "failed"}
    if needs_vector_delete:
        db.add(MemoryVectorOutbox(memory_id=memory_id, user_id=user_id, operation="delete"))
    db.delete(memory)
    db.commit()
    return needs_vector_delete


async def process_vector_outbox(factory: sessionmaker = SessionLocal, *, limit: int = 20) -> int:
    """Idempotently reconcile Chroma to committed relational state."""
    processed = 0
    for _ in range(limit):
        with factory() as db:
            operation = db.scalar(select(MemoryVectorOutbox).order_by(MemoryVectorOutbox.created_at).limit(1))
            if operation is None:
                break
            operation_id, memory_id, user_id = operation.operation_id, operation.memory_id, operation.user_id
            memory = db.scalar(select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user_id))
            snapshot = None
            if memory is not None and memory.approval_status == "approved":
                snapshot = SimpleNamespace(
                    memory_id=memory.memory_id, user_id=memory.user_id, content=memory.content,
                    category=memory.category, importance=memory.importance, confidence=memory.confidence,
                    memory_type=memory.memory_type, source_conversation_id=memory.source_conversation_id,
                    created_at=memory.created_at, updated_at=memory.updated_at,
                )
        try:
            if snapshot is None:
                await asyncio.to_thread(vector_store.delete_memory, memory_id)
            else:
                vector = await embeddings.embed_document(snapshot.content)
                await asyncio.to_thread(vector_store.upsert_memory, snapshot, vector)
        except Exception as error:
            with factory() as db:
                operation = db.get(MemoryVectorOutbox, operation_id)
                memory = db.get(Memory, memory_id)
                if operation:
                    operation.attempts += 1
                    operation.last_error = type(error).__name__[:100]
                if memory:
                    memory.vector_sync_status = "failed"
                db.commit()
            logger.warning("Memory vector reconciliation deferred (%s).", type(error).__name__)
            break
        with factory() as db:
            memory = db.get(Memory, memory_id)
            operation = db.get(MemoryVectorOutbox, operation_id)
            if memory and memory.approval_status == "approved":
                memory.vector_sync_status = "synced"
            if operation:
                db.delete(operation)
            db.commit()
        processed += 1
    return processed


def list_memories(
    db: Session,
    user_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    category: str | None = None,
    approval_status: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
) -> tuple[list[Memory], int]:
    predicates = [Memory.user_id == user_id]
    if category:
        predicates.append(Memory.category == category)
    if approval_status:
        predicates.append(Memory.approval_status == approval_status)
    sort_column = {"created_at": Memory.created_at, "updated_at": Memory.updated_at, "importance": Memory.importance}[sort_by]
    sort = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    items = db.scalars(select(Memory).where(*predicates).order_by(sort, Memory.memory_id).limit(limit).offset(offset)).all()
    total = db.scalar(select(func.count(Memory.memory_id)).where(*predicates)) or 0
    return list(items), int(total)


def memory_stats(db: Session, user_id: UUID) -> dict[str, Any]:
    counts = dict(db.execute(
        select(Memory.category, func.count(Memory.memory_id))
        .where(Memory.user_id == user_id, Memory.approval_status != "rejected")
        .group_by(Memory.category)
    ).all())
    status_counts = dict(db.execute(
        select(Memory.approval_status, func.count(Memory.memory_id))
        .where(Memory.user_id == user_id).group_by(Memory.approval_status)
    ).all())
    total = db.scalar(select(func.count(Memory.memory_id)).where(Memory.user_id == user_id)) or 0
    sync_pending = db.scalar(select(func.count(Memory.memory_id)).where(
        Memory.user_id == user_id, Memory.approval_status == "approved", Memory.vector_sync_status != "synced"
    )) or 0
    jobs = db.scalars(select(MemoryExtractionJob).where(MemoryExtractionJob.user_id == user_id)).all()
    recent = db.scalars(select(Memory).where(Memory.user_id == user_id).order_by(Memory.updated_at.desc()).limit(5)).all()
    return {
        "total": int(total), "approved": int(status_counts.get("approved", 0)),
        "pending": int(status_counts.get("pending", 0)), "rejected": int(status_counts.get("rejected", 0)),
        "vector_sync_pending": int(sync_pending),
        "extraction_jobs_pending": sum(job.status in {"pending", "processing"} for job in jobs),
        "extraction_jobs_failed": sum(job.status == "failed" for job in jobs),
        "semantic_search_available": embeddings.is_configured(),
        "vector_index_available": vector_store.runtime_available(),
        "automatic_save_enabled": settings.memory_auto_save,
        "categories": counts, "recently_updated": recent,
    }

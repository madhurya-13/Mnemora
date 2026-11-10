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
from app.models.memory import Memory, MemoryExtractionJob, MemoryVectorOutbox
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

    if duplicate is not None and duplicate.approval_status == "pending":
        return duplicate
    if duplicate is not None and auto_save:
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
        and bool(settings.openai_api_key.strip())
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
    if memory.similar_memory_id:
        canonical = db.scalar(select(Memory).where(
            Memory.memory_id == memory.similar_memory_id,
            Memory.user_id == user_id,
            Memory.approval_status == "approved",
        ))
        if canonical is not None:
            canonical.source_message_ids = sorted(_source_ids(canonical) | _source_ids(memory))
            if canonical.source_conversation_id is None:
                canonical.source_conversation_id = memory.source_conversation_id
            canonical.updated_at = _now()
            _enqueue(db, canonical)
            db.delete(memory)
            db.commit()
            db.refresh(canonical)
            return canonical
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
    db.commit()
    db.refresh(memory)
    return memory


def update_memory(db: Session, user_id: UUID, memory_id: UUID, changes: dict[str, Any]) -> Memory:
    memory = db.scalar(select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user_id))
    if memory is None:
        raise MemoryNotFoundError
    if "content" in changes and contains_sensitive_information(changes["content"]):
        raise MemoryUnsafeContentError("This memory contains sensitive information and cannot be stored.")
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
        "semantic_search_available": bool(settings.openai_api_key.strip()),
        "vector_index_available": vector_store.runtime_available(),
        "automatic_save_enabled": settings.memory_auto_save,
        "categories": counts, "recently_updated": recent,
    }

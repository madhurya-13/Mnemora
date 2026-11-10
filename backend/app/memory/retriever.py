"""User-scoped semantic retrieval, ranking and LLM context preparation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.memory import embeddings, vector_store
from app.models.memory import Memory
from app.schemas.memory import MemorySearchResult

logger = logging.getLogger(__name__)


async def search_memories(
    db: Session,
    user_id: UUID,
    query: str,
    *,
    top_k: int | None = None,
    category: str | None = None,
) -> list[MemorySearchResult]:
    if not query.strip():
        raise ValueError("Search query cannot be blank.")
    limit = min(top_k or settings.memory_top_k, settings.memory_top_k)
    query_vector = await embeddings.embed_text(query)
    matches = await asyncio.to_thread(
        vector_store.query_user, user_id, query_vector,
        limit=max(limit * 3, limit), category=category,
    )
    ids: list[UUID] = []
    for match in matches:
        try:
            ids.append(UUID(match["id"]))
        except (ValueError, TypeError):
            continue
    if not ids:
        return []
    records = db.scalars(select(Memory).where(
        Memory.memory_id.in_(ids), Memory.user_id == user_id,
        Memory.approval_status == "approved", Memory.vector_sync_status == "synced",
        Memory.importance >= settings.memory_min_importance,
        Memory.confidence >= settings.memory_min_confidence,
        or_(Memory.expires_at.is_(None), Memory.expires_at > datetime.now(timezone.utc)),
    )).all()
    by_id = {str(item.memory_id): item for item in records}
    now = datetime.now(timezone.utc)
    results: list[MemorySearchResult] = []
    for match in matches:
        memory = by_id.get(match["id"])
        if memory is None:
            continue
        similarity = max(0.0, min(1.0, 1.0 - match["distance"]))
        if similarity < settings.memory_min_relevance:
            continue
        relevance = 0.7 * similarity + 0.2 * memory.importance + 0.1 * memory.confidence
        memory.last_accessed_at = now
        results.append(MemorySearchResult(memory=memory, similarity=similarity, relevance=relevance))
    db.commit()
    results.sort(key=lambda item: item.relevance, reverse=True)
    return results[:limit]


async def retrieve_context(db: Session, user_id: UUID, query: str) -> list[str]:
    """Return only useful approved memories; search/index failures never block chat."""
    try:
        has_memories = db.scalar(select(Memory.memory_id).where(
            Memory.user_id == user_id, Memory.approval_status == "approved",
            Memory.vector_sync_status == "synced",
        ).limit(1))
        if not has_memories:
            return []
        results = await search_memories(db, user_id, query, top_k=settings.memory_max_context_items)
        return [item.memory.content for item in results]
    except Exception as error:
        logger.warning("Memory retrieval skipped (%s).", type(error).__name__)
        return []

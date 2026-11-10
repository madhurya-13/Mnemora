"""Milestone 4 compatibility facade over the Milestone 5 retrieval pipeline."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.memory import Memory
from app.retrieval import hybrid_retriever
from app.schemas.memory import MemorySearchResult

logger = logging.getLogger(__name__)


async def search_memories(
    db: Session,
    user_id: UUID,
    query: str,
    *,
    top_k: int | None = None,
    category: str | None = None,
    min_importance: float | None = None,
    date_from=None,
    date_to=None,
    sort_by: str = "relevance",
) -> list[MemorySearchResult]:
    result = await hybrid_retriever.retrieve(
        db, user_id, query, top_k=top_k, category=category,
        min_importance=min_importance, date_from=date_from, date_to=date_to,
    )
    selected = result.context["selected"]
    if sort_by == "importance":
        selected = sorted(selected, key=lambda row: row["memory"].importance, reverse=True)
    elif sort_by in {"created_at", "updated_at"}:
        selected = sorted(selected, key=lambda row: getattr(row["memory"], sort_by), reverse=True)
    return [MemorySearchResult(
        memory=row["memory"], similarity=row["semantic_score"], relevance=row["final_score"],
        keyword_score=row["keyword_score"], recency_score=row["components"]["recency"],
        retrieval_reason=row["retrieval_reason"], score_components=row["components"],
    ) for row in selected]


async def retrieve_context(db: Session, user_id: UUID, query: str) -> list[str]:
    """Return context only for relevant, approved memories; failure never blocks chat."""
    try:
        result = await hybrid_retriever.retrieve(db, user_id, query)
        text = result.context["text"]
        return [text] if text else []
    except Exception as error:
        logger.warning("Memory retrieval skipped (%s).", type(error).__name__)
        return []

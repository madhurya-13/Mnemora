"""User-scoped semantic + SQL keyword retrieval, RRF fusion, ranking and auditing."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.memory import embeddings, vector_store
from app.models.memory import Memory, MemoryConflict, MemoryRetrievalEvent, MemoryRetrievalItem
from app.retrieval import context_builder, query_analyzer, query_expander, ranker

logger = logging.getLogger(__name__)


@dataclass
class HybridRetrieval:
    analysis: Any
    ranked: list[dict[str, Any]]
    context: dict[str, Any]
    candidate_count: int
    latency_ms: float


def _safe_tokens(text: str) -> list[str]:
    return list(dict.fromkeys(part.casefold() for part in query_analyzer._keywords(text) if len(part) > 1))


def _memory_predicates(user_id: UUID, *, category: str | None, min_importance: float | None, date_from: datetime | None, date_to: datetime | None):
    now = datetime.now(timezone.utc)
    predicates = [
        Memory.user_id == user_id,
        Memory.approval_status == "approved",
        Memory.vector_sync_status == "synced",
        Memory.importance >= max(settings.memory_min_importance, settings.retrieval_min_importance, min_importance or 0),
        Memory.confidence >= settings.memory_min_confidence,
        or_(Memory.expires_at.is_(None), Memory.expires_at > now),
    ]
    if category:
        predicates.append(Memory.category == category)
    if date_from:
        predicates.append(Memory.updated_at >= date_from)
    if date_to:
        predicates.append(Memory.updated_at <= date_to)
    return predicates


def _keyword_hits(db: Session, user_id: UUID, query: str, *, limit: int, category: str | None, min_importance: float | None, date_from: datetime | None, date_to: datetime | None):
    tokens = _safe_tokens(query)
    if not tokens:
        return [], {}
    predicates = _memory_predicates(user_id, category=category, min_importance=min_importance, date_from=date_from, date_to=date_to)
    predicates.append(or_(*(Memory.content.ilike(f"%{token}%") for token in tokens)))
    rows = db.scalars(select(Memory).where(*predicates).order_by(Memory.updated_at.desc()).limit(limit)).all()
    scores = {}
    for memory in rows:
        content = set(_safe_tokens(memory.content))
        scores[str(memory.memory_id)] = len(content.intersection(tokens)) / max(1, len(tokens))
    rows.sort(key=lambda row: (scores[str(row.memory_id)], row.importance, row.updated_at), reverse=True)
    return rows, scores


async def retrieve(
    db: Session,
    user_id: UUID,
    query: str,
    *,
    top_k: int | None = None,
    category: str | None = None,
    min_importance: float | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    audit: bool = True,
) -> HybridRetrieval:
    started = time.perf_counter()
    analysis = query_analyzer.analyze_query(query)
    query_texts = query_expander.expand_query(query, analysis)
    limit = min(settings.retrieval_candidate_limit, max(settings.memory_top_k, (top_k or settings.memory_max_context_items) * 4))
    memory_by_id: dict[str, Memory] = {}
    keyword_scores: dict[str, float] = {}
    semantic_scores: dict[str, float] = {}
    rankings: list[list[str]] = []

    if analysis.requires_memory:
        keyword_rows, keyword_scores = _keyword_hits(
            db, user_id, query, limit=limit, category=category, min_importance=min_importance,
            date_from=date_from, date_to=date_to,
        )
        for row in keyword_rows:
            memory_by_id[str(row.memory_id)] = row
        if keyword_rows:
            rankings.append([str(row.memory_id) for row in keyword_rows])

        has_approved = db.scalar(select(Memory.memory_id).where(*_memory_predicates(
            user_id, category=category, min_importance=min_importance, date_from=date_from, date_to=date_to,
        )).limit(1))
        query_vectors = await embeddings.embed_texts(query_texts) if has_approved else []
        semantic_lists = await asyncio.gather(*[
            asyncio.to_thread(vector_store.query_user, user_id, vector, limit=limit, category=category)
            for vector in query_vectors
        ])
        semantic_ids: set[str] = set()
        for matches in semantic_lists:
            ids: list[str] = []
            for match in matches:
                memory_id = str(match.get("id", ""))
                try:
                    UUID(memory_id)
                except ValueError:
                    continue
                ids.append(memory_id)
                semantic_ids.add(memory_id)
                semantic_scores[memory_id] = max(semantic_scores.get(memory_id, 0.0), max(0.0, min(1.0, 1.0 - float(match.get("distance", 1)))))
            if ids:
                rankings.append(ids)
        if semantic_ids:
            predicates = _memory_predicates(
                user_id, category=category, min_importance=min_importance, date_from=date_from, date_to=date_to,
            )
            predicates.append(Memory.memory_id.in_([UUID(value) for value in semantic_ids]))
            for memory in db.scalars(select(Memory).where(*predicates)).all():
                memory_by_id[str(memory.memory_id)] = memory

    fused = ranker.reciprocal_rank_fusion(rankings)
    usage_rows = db.execute(
        select(MemoryRetrievalItem.memory_id, func.count(MemoryRetrievalItem.item_id))
        .join(MemoryRetrievalEvent, MemoryRetrievalEvent.event_id == MemoryRetrievalItem.event_id)
        .where(MemoryRetrievalEvent.user_id == user_id, MemoryRetrievalItem.selected.is_(True))
        .group_by(MemoryRetrievalItem.memory_id)
    ).all()
    usage = {str(memory_id): count for memory_id, count in usage_rows}

    candidates: list[dict[str, Any]] = []
    for memory_id, memory in memory_by_id.items():
        semantic = semantic_scores.get(memory_id, 0.0)
        keyword = keyword_scores.get(memory_id, 0.0)
        normalized_fusion = fused.get(memory_id, 0.0)
        fused_semantic = min(1.0, 0.75 * semantic + 0.25 * normalized_fusion)
        category_score = 1.0 if memory.category in analysis.categories else (0.35 if not analysis.categories else 0.0)
        components = ranker.score_memory(
            memory, semantic=fused_semantic, keyword=keyword, category_match=category_score,
            usage_count=usage.get(memory_id, 0),
        )
        reason_parts = []
        if semantic >= settings.memory_min_relevance:
            reason_parts.append("semantic match")
        if keyword > 0:
            reason_parts.append("keyword overlap")
        if category_score >= 1:
            reason_parts.append(f"{memory.category} category match")
        if memory.importance >= 0.8:
            reason_parts.append("high importance")
        candidates.append({
            "memory": memory, "semantic_score": semantic, "keyword_score": keyword,
            "fusion_score": normalized_fusion, "components": components,
            "final_score": components["final"],
            "retrieval_reason": "; ".join(reason_parts) or "supporting hybrid retrieval rank",
            "eligible": components["final"] >= settings.memory_min_relevance,
        })
    candidates.sort(key=lambda item: item["final_score"], reverse=True)

    conflict_rows = db.scalars(select(MemoryConflict).where(
        MemoryConflict.user_id == user_id, MemoryConflict.status == "unresolved",
    )).all()
    unresolved_pairs = {
        frozenset((str(item.existing_memory_id), str(item.new_memory_id))) for item in conflict_rows
    }
    context = context_builder.build_context(
        candidates, unresolved_pairs, max_items=top_k or settings.memory_max_context_items,
    )
    selected_ids = {str(row["memory"].memory_id) for row in context["selected"]}
    now = datetime.now(timezone.utc)
    for row in context["selected"]:
        row["memory"].last_accessed_at = now

    latency_ms = (time.perf_counter() - started) * 1000
    if audit:
        event = MemoryRetrievalEvent(
            user_id=user_id, intent=analysis.intent, query_type=analysis.query_type,
            category=category or (analysis.categories[0] if analysis.categories else None),
            candidate_count=len(candidates), selected_count=len(selected_ids),
            excluded_count=max(0, len(candidates) - len(selected_ids)), latency_ms=latency_ms,
        )
        db.add(event)
        db.flush()
        for rank, row in enumerate(candidates, 1):
            memory = row["memory"]
            components = row["components"]
            chosen = str(memory.memory_id) in selected_ids
            reason = row["retrieval_reason"] if chosen else context["excluded"].get(str(memory.memory_id), "below relevance threshold")
            db.add(MemoryRetrievalItem(
                event_id=event.event_id, memory_id=memory.memory_id, rank=rank, selected=chosen,
                reason=reason[:240], semantic_score=row["semantic_score"], keyword_score=row["keyword_score"],
                importance_score=components["importance"], confidence_score=components["confidence"],
                recency_score=components["recency"], category_score=components["category"],
                usage_score=components["usage"], final_score=row["final_score"],
            ))
        db.commit()

    return HybridRetrieval(analysis, candidates, context, len(candidates), latency_ms)

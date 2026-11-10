"""Normalized weighted ranking and reciprocal-rank fusion."""

from __future__ import annotations

import math

from app.config import settings
from app.models.memory import Memory
from app.retrieval.recency import recency_score


def reciprocal_rank_fusion(rankings: list[list[str]], *, k: int | None = None) -> dict[str, float]:
    denominator = max(1, len(rankings))
    offset = k or settings.retrieval_rrf_k
    values: dict[str, float] = {}
    for ranking in rankings:
        for rank, memory_id in enumerate(ranking, 1):
            values[memory_id] = values.get(memory_id, 0.0) + 1.0 / (offset + rank)
    maximum = 1.0 / (offset + 1) * denominator
    return {memory_id: min(1.0, score / maximum) for memory_id, score in values.items()}


def score_memory(memory: Memory, *, semantic: float, keyword: float, category_match: float, usage_count: int, now=None) -> dict[str, float]:
    recency = recency_score(memory.updated_at, memory.category, memory.memory_type, now=now)
    usage = min(1.0, math.log1p(max(0, usage_count)) / math.log(11))
    weights = {
        "semantic": settings.retrieval_weight_semantic, "keyword": settings.retrieval_weight_keyword,
        "importance": settings.retrieval_weight_importance, "confidence": settings.retrieval_weight_confidence,
        "recency": settings.retrieval_weight_recency, "category": settings.retrieval_weight_category,
        "usage": settings.retrieval_weight_usage,
    }
    total = sum(weights.values()) or 1.0
    components = {
        "semantic": max(0.0, min(1.0, semantic)), "keyword": max(0.0, min(1.0, keyword)),
        "importance": max(0.0, min(1.0, memory.importance)), "confidence": max(0.0, min(1.0, memory.confidence)),
        "recency": recency, "category": max(0.0, min(1.0, category_match)), "usage": usage,
    }
    components["final"] = sum(weights[key] * value for key, value in components.items()) / total
    return components

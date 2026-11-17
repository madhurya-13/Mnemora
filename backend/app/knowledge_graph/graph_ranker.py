"""Path ranking for graph retrieval, with evidence and recency tie-breakers."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from app.knowledge_graph.graph_schemas import GraphPath
from app.models.graph import GraphRelationship


def _recency(relationship: GraphRelationship, now: datetime) -> float:
    value = relationship.valid_from or relationship.updated_at
    if value is None:
        return 0.5
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - value).total_seconds() / 86400)
    return math.pow(0.5, age_days / 180.0)


def score_path(
    path: GraphPath,
    relationships: dict,
    *,
    type_relevance: float = 1.0,
    now: datetime | None = None,
) -> float:
    """Combine confidence, depth, recency and evidence strength into 0..1."""
    now = now or datetime.now(timezone.utc)
    rows = [relationships.get(relationship_id) for relationship_id in path.relationship_ids]
    rows = [row for row in rows if row is not None]
    if not rows:
        return 0.0
    confidence = sum(row.confidence for row in rows) / len(rows)
    depth_factor = {1: 1.0, 2: 0.86, 3: 0.72}.get(path.depth, 0.6)
    recency = sum(_recency(row, now) for row in rows) / len(rows)
    evidence = min(1.0, 0.5 + 0.1 * sum(len(row.evidence_memory_ids or []) for row in rows))
    historical_penalty = 0.55 if path.historical else 1.0
    score = (
        0.45 * confidence
        + 0.20 * depth_factor
        + 0.15 * recency
        + 0.20 * evidence
    ) * max(0.0, min(1.0, type_relevance)) * historical_penalty
    return round(max(0.0, min(1.0, score)), 4)


def rank_paths(
    paths: list[GraphPath],
    relationships: list[GraphRelationship],
    *,
    type_relevance: dict[str, float] | None = None,
    now: datetime | None = None,
) -> list[GraphPath]:
    lookup = {row.relationship_id: row for row in relationships}
    relevance = type_relevance or {}
    unique: dict[tuple[tuple, tuple], GraphPath] = {}
    for path in paths:
        last_type = None
        if path.relationship_ids:
            last = lookup.get(path.relationship_ids[-1])
            last_type = last.relationship_type if last is not None else None
        weight = relevance.get(last_type, 1.0) if last_type else 1.0
        scored = score_path(path, lookup, type_relevance=weight, now=now)
        key = (tuple(path.entity_ids), tuple(path.relationship_ids))
        if key not in unique or scored > unique[key].score:
            path.score = scored
            unique[key] = path
    return sorted(unique.values(), key=lambda item: (item.score, -item.depth), reverse=True)

"""Real graph statistics computed from stored rows, never hardcoded."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.graph import (
    GraphEntity,
    GraphMergeRecord,
    GraphRelationship,
    GraphSyncRecord,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _entity_summary(entity: GraphEntity) -> dict:
    return {
        "entity_id": str(entity.entity_id),
        "entity_name": entity.entity_name,
        "entity_type": entity.entity_type,
        "confidence": round(entity.confidence, 3),
        "status": entity.status,
        "created_at": entity.created_at.isoformat(),
        "updated_at": entity.updated_at.isoformat(),
    }


def _relationship_summary(relationship: GraphRelationship, source: str, target: str) -> dict:
    return {
        "relationship_id": str(relationship.relationship_id),
        "source_entity_id": str(relationship.source_entity_id),
        "target_entity_id": str(relationship.target_entity_id),
        "source_name": source,
        "target_name": target,
        "relationship_type": relationship.relationship_type,
        "confidence": round(relationship.confidence, 3),
        "status": relationship.status,
        "updated_at": relationship.updated_at.isoformat(),
        "valid_from": relationship.valid_from.isoformat() if relationship.valid_from else None,
        "valid_until": relationship.valid_until.isoformat() if relationship.valid_until else None,
    }


def compute_insights(
    db: Session,
    user_id: UUID,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    entity_type: str | None = None,
    relationship_type: str | None = None,
) -> dict:
    entity_predicates = [GraphEntity.user_id == user_id]
    relationship_predicates = [GraphRelationship.user_id == user_id]
    if date_from is not None:
        entity_predicates.append(GraphEntity.created_at >= date_from)
        relationship_predicates.append(GraphRelationship.created_at >= date_from)
    if date_to is not None:
        entity_predicates.append(GraphEntity.created_at <= date_to)
        relationship_predicates.append(GraphRelationship.created_at <= date_to)
    if entity_type:
        entity_predicates.append(GraphEntity.entity_type == entity_type)
    if relationship_type:
        relationship_predicates.append(GraphRelationship.relationship_type == relationship_type)

    entities = db.scalars(select(GraphEntity).where(*entity_predicates)).all()
    relationships = db.scalars(select(GraphRelationship).where(*relationship_predicates)).all()
    entity_lookup = {
        entity.entity_id: entity
        for entity in db.scalars(
            select(GraphEntity).where(GraphEntity.user_id == user_id)
        ).all()
    }

    active_entities = [entity for entity in entities if entity.status == "active"]
    active_relationships = [row for row in relationships if row.status == "active"]
    degree = Counter()
    for relationship in active_relationships:
        degree[relationship.source_entity_id] += 1
        degree[relationship.target_entity_id] += 1
    most_connected = sorted(
        (entity for entity in active_entities if degree.get(entity.entity_id, 0) > 0),
        key=lambda entity: degree.get(entity.entity_id, 0),
        reverse=True,
    )[:8]
    isolated = [entity for entity in active_entities if degree.get(entity.entity_id, 0) == 0]

    now = _utcnow()
    growth_start = (date_from or (now - timedelta(days=29))).date()
    growth_end = (date_to or now).date()
    growth_counts: Counter = Counter()
    for entity in entities:
        created = entity.created_at.date()
        if growth_start <= created <= growth_end:
            growth_counts[created.isoformat()] += 1
    growth: list[dict] = []
    cursor = growth_start
    while cursor <= growth_end and len(growth) < 120:
        growth.append({"date": cursor.isoformat(), "entities": growth_counts.get(cursor.isoformat(), 0)})
        cursor += timedelta(days=1)

    pending_entities = [entity for entity in entities if entity.status == "pending_review"]
    pending_relationships = [row for row in relationships if row.status == "pending_review"]
    historical = [row for row in relationships if row.status == "historical"]
    merges = db.scalar(
        select(func.count()).select_from(GraphMergeRecord).where(
            GraphMergeRecord.user_id == user_id, GraphMergeRecord.status == "active"
        )
    ) or 0
    sync_pending = db.scalar(
        select(func.count()).select_from(GraphSyncRecord).where(
            GraphSyncRecord.user_id == user_id, GraphSyncRecord.status == "pending"
        )
    ) or 0
    sync_failed = db.scalar(
        select(func.count()).select_from(GraphSyncRecord).where(
            GraphSyncRecord.user_id == user_id, GraphSyncRecord.status == "failed"
        )
    ) or 0
    with_evidence = sum(
        1
        for row in active_relationships
        if row.evidence_memory_ids
        or any(item.get("kind") == "user" for item in (row.evidence or []))
    )

    recent_entities = sorted(entities, key=lambda entity: entity.created_at, reverse=True)[:8]
    recent_relationships = sorted(relationships, key=lambda row: row.updated_at, reverse=True)[:8]

    return {
        "total_entities": len(entities),
        "active_entities": len(active_entities),
        "total_relationships": len(relationships),
        "active_relationships": len(active_relationships),
        "historical_relationships": len(historical),
        "pending_entities": len(pending_entities),
        "pending_relationships": len(pending_relationships),
        "entity_type_counts": dict(Counter(entity.entity_type for entity in entities)),
        "relationship_type_counts": dict(Counter(row.relationship_type for row in relationships)),
        "recently_added_entities": [_entity_summary(entity) for entity in recent_entities],
        "recently_updated_relationships": [
            _relationship_summary(
                row,
                entity_lookup.get(row.source_entity_id).entity_name if entity_lookup.get(row.source_entity_id) else "Unknown",
                entity_lookup.get(row.target_entity_id).entity_name if entity_lookup.get(row.target_entity_id) else "Unknown",
            )
            for row in recent_relationships
        ],
        "most_connected_entities": [
            {**_entity_summary(entity), "degree": degree.get(entity.entity_id, 0)}
            for entity in most_connected
        ],
        "isolated_entities": [_entity_summary(entity) for entity in isolated[:20]],
        "growth": growth,
        "pending_corrections": len(pending_entities) + len(pending_relationships),
        "merge_count": merges,
        "sync_pending": sync_pending,
        "sync_failed": sync_failed,
        "evidence_coverage": round(with_evidence / len(active_relationships), 3) if active_relationships else 0.0,
    }

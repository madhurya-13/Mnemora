"""Temporal graph updates: supersession, closure and evidence activation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.graph import GraphEntity, GraphHistory, GraphRelationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def supersede_matching(
    db: Session,
    user_id: UUID,
    *,
    new_relationship: GraphRelationship,
    replace_types: tuple[str, ...],
    replace_target_types: tuple[str, ...],
) -> int:
    """Mark older, explicitly replaced facts historical without deleting them."""
    if not replace_types or not replace_target_types:
        return 0
    now = _utcnow()
    rows = db.scalars(
        select(GraphRelationship)
        .join(GraphEntity, GraphEntity.entity_id == GraphRelationship.target_entity_id)
        .where(
            GraphRelationship.user_id == user_id,
            GraphRelationship.source_entity_id == new_relationship.source_entity_id,
            GraphRelationship.relationship_type.in_(replace_types),
            GraphRelationship.status == "active",
            GraphRelationship.relationship_id != new_relationship.relationship_id,
            GraphRelationship.target_entity_id != new_relationship.target_entity_id,
            GraphEntity.entity_type.in_(replace_target_types),
        )
    ).all()
    for row in rows:
        row.status = "historical"
        row.valid_until = row.valid_until or now
        row.superseded_by = new_relationship.relationship_id
        row.updated_at = now
    return len(rows)


def close_relationship(db: Session, relationship: GraphRelationship) -> None:
    now = _utcnow()
    relationship.status = "historical"
    relationship.valid_until = relationship.valid_until or now
    relationship.updated_at = now


def mark_historical(db: Session, relationship: GraphRelationship) -> None:
    now = _utcnow()
    relationship.status = "historical"
    relationship.valid_until = relationship.valid_until or now
    relationship.updated_at = now


def activate_memory_facts(db: Session, user_id: UUID, memory_id: UUID) -> dict[str, int]:
    """Activate pending facts supported by a newly approved memory."""
    key = str(memory_id)
    entities = db.scalars(
        select(GraphEntity).where(
            GraphEntity.user_id == user_id,
            GraphEntity.status == "pending_review",
        )
    ).all()
    activated_entities = 0
    for entity in entities:
        if key in (entity.source_memory_ids or []):
            entity.status = "active"
            entity.updated_at = _utcnow()
            activated_entities += 1

    relationships = db.scalars(
        select(GraphRelationship).where(
            GraphRelationship.user_id == user_id,
            GraphRelationship.status == "pending_review",
        )
    ).all()
    activated_relationships = 0
    for relationship in relationships:
        if key in (relationship.evidence_memory_ids or []):
            relationship.status = "active"
            relationship.valid_from = relationship.valid_from or _utcnow()
            relationship.updated_at = _utcnow()
            activated_relationships += 1

    if activated_entities or activated_relationships:
        db.add(
            GraphHistory(
                user_id=user_id,
                action="activate",
                summary=(
                    f"Activated {activated_entities} entities and "
                    f"{activated_relationships} relationships after memory approval."
                ),
                actor="system",
                after={
                    "memory_id": key,
                    "entities": activated_entities,
                    "relationships": activated_relationships,
                },
            )
        )
        db.commit()
    return {"entities": activated_entities, "relationships": activated_relationships}


def withdraw_memory(db: Session, user_id: UUID, memory_id: UUID) -> int:
    """Archive facts that have no evidence other than a rejected/deleted memory."""
    key = str(memory_id)
    now = _utcnow()
    changed = 0
    relationships = db.scalars(
        select(GraphRelationship).where(
            GraphRelationship.user_id == user_id,
            GraphRelationship.status.in_(("active", "pending_review")),
        )
    ).all()
    for relationship in relationships:
        evidence_ids = list(relationship.evidence_memory_ids or [])
        if key not in evidence_ids:
            continue
        remaining = [item for item in evidence_ids if item != key]
        has_user_evidence = any(
            item.get("kind") == "user" for item in (relationship.evidence or [])
        )
        if remaining or has_user_evidence:
            relationship.evidence_memory_ids = remaining
            relationship.evidence = [
                item
                for item in (relationship.evidence or [])
                if item.get("memory_id") != key
            ]
            relationship.updated_at = now
        else:
            relationship.status = "archived"
            relationship.updated_at = now
        changed += 1
    if changed:
        db.add(
            GraphHistory(
                user_id=user_id,
                action="withdraw",
                summary=f"Withdrew or trimmed {changed} relationships for memory {key}.",
                actor="system",
                after={"memory_id": key, "relationships": changed},
            )
        )
        db.commit()
    return changed

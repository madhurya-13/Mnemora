"""Entity normalisation, conservative resolution and auditable merging."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.knowledge_graph.graph_schemas import TECHNOLOGY_LIKE
from app.models.graph import (
    GraphEntity,
    GraphHistory,
    GraphMergeRecord,
    GraphRelationship,
)

_GENERIC_PROJECT_SUFFIXES = {"project", "projects", "app", "application"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_entity_name(name: str, entity_type: str | None = None) -> str:
    """Return the stable identity key used for duplicate prevention."""
    text = " ".join(name.casefold().replace("’", "'").split())
    text = re.sub(r"'s\b", "", text)
    if entity_type in TECHNOLOGY_LIKE:
        return re.sub(r"[^a-z0-9+#]", "", text)
    text = re.sub(r"[^a-z0-9+#. ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if len(words) > 1 and words[-1] in _GENERIC_PROJECT_SUFFIXES:
        text = " ".join(words[:-1])
    return text


def compact_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def name_similarity(left: str, right: str) -> float:
    left_key = compact_name(left)
    right_key = compact_name(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return round(SequenceMatcher(None, left_key, right_key).ratio(), 4)


def find_entity(db: Session, user_id: UUID, name: str, entity_type: str) -> GraphEntity | None:
    """Exact, normalised then alias match. Never uses fuzzy matching."""
    normalized = normalize_entity_name(name, entity_type)
    if not normalized:
        return None
    direct = db.scalar(
        select(GraphEntity).where(
            GraphEntity.user_id == user_id,
            GraphEntity.entity_type == entity_type,
            GraphEntity.normalized_name == normalized,
        )
    )
    if direct is not None:
        return direct
    rows = db.scalars(
        select(GraphEntity).where(
            GraphEntity.user_id == user_id,
            GraphEntity.entity_type == entity_type,
            GraphEntity.status.in_(("active", "pending_review")),
        )
    ).all()
    for row in rows:
        for alias in row.aliases or []:
            if normalize_entity_name(alias, entity_type) == normalized:
                return row
    return None


def duplicate_candidates(
    db: Session, user_id: UUID, entity: GraphEntity, *, threshold: float = 0.8
) -> list[dict]:
    """Suggest possible duplicates. Suggestions are never applied automatically."""
    rows = db.scalars(
        select(GraphEntity).where(
            GraphEntity.user_id == user_id,
            GraphEntity.entity_id != entity.entity_id,
            GraphEntity.status.in_(("active", "pending_review")),
        )
    ).all()
    suggestions: list[dict] = []
    for row in rows:
        similarity = name_similarity(entity.entity_name, row.entity_name)
        same_type = row.entity_type == entity.entity_type
        alias_match = any(
            normalize_entity_name(alias, row.entity_type)
            == normalize_entity_name(entity.entity_name, row.entity_type)
            for alias in (row.aliases or [])
        )
        if similarity >= threshold or alias_match:
            suggestions.append({
                "entity_id": str(row.entity_id),
                "entity_name": row.entity_name,
                "entity_type": row.entity_type,
                "similarity": 1.0 if alias_match else similarity,
                "same_type": same_type,
                "reason": "alias_match" if alias_match else "name_similarity",
            })
    suggestions.sort(key=lambda item: item["similarity"], reverse=True)
    return suggestions[:10]


def _record_history(
    db: Session,
    user_id: UUID,
    *,
    action: str,
    summary: str,
    entity_id: UUID | None = None,
    relationship_id: UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
    actor: str = "user",
) -> None:
    db.add(
        GraphHistory(
            user_id=user_id,
            entity_id=entity_id,
            relationship_id=relationship_id,
            action=action,
            summary=summary[:500],
            actor=actor,
            before=before,
            after=after,
        )
    )


def merge_entities(
    db: Session,
    user_id: UUID,
    primary_entity_id: UUID,
    duplicate_entity_id: UUID,
    *,
    confirm_similar: bool = False,
    actor: str = "user",
) -> dict:
    """Merge a duplicate into a primary entity, preserving evidence and history.

    Names that are not proven equal (normalised or alias match) require explicit
    confirmation. Every merge stores an undo snapshot.
    """
    if primary_entity_id == duplicate_entity_id:
        raise ValueError("Choose two different entities to merge.")
    primary = db.scalar(
        select(GraphEntity).where(
            GraphEntity.entity_id == primary_entity_id, GraphEntity.user_id == user_id
        )
    )
    duplicate = db.scalar(
        select(GraphEntity).where(
            GraphEntity.entity_id == duplicate_entity_id, GraphEntity.user_id == user_id
        )
    )
    if primary is None or duplicate is None:
        raise LookupError("Entity not found.")
    if primary.status in {"archived", "merged"} or duplicate.status in {"archived", "merged"}:
        raise ValueError("Archived or already merged entities cannot be merged.")

    primary_key = normalize_entity_name(primary.entity_name, primary.entity_type)
    duplicate_key = normalize_entity_name(duplicate.entity_name, duplicate.entity_type)
    alias_equivalent = any(
        normalize_entity_name(alias, primary.entity_type) == duplicate_key
        for alias in (primary.aliases or [])
    )
    proven_equal = primary_key == duplicate_key and primary.entity_type == duplicate.entity_type
    if not proven_equal and not alias_equivalent and not confirm_similar:
        suggestion = name_similarity(primary.entity_name, duplicate.entity_name)
        raise PermissionError(
            "These entities are not provably the same. Confirm the merge explicitly "
            f"(name similarity {suggestion})."
        )

    now = _utcnow()
    primary_snapshot = {
        "entity_name": primary.entity_name,
        "aliases": list(primary.aliases or []),
        "description": primary.description,
        "confidence": primary.confidence,
        "source_memory_ids": list(primary.source_memory_ids or []),
        "first_observed_at": primary.first_observed_at.isoformat(),
        "last_observed_at": primary.last_observed_at.isoformat(),
    }
    duplicate_snapshot = {
        "entity_name": duplicate.entity_name,
        "normalized_name": duplicate.normalized_name,
        "entity_type": duplicate.entity_type,
        "description": duplicate.description,
        "aliases": list(duplicate.aliases or []),
        "confidence": duplicate.confidence,
        "source_memory_ids": list(duplicate.source_memory_ids or []),
        "status": duplicate.status,
        "merged_into_id": None,
        "first_observed_at": duplicate.first_observed_at.isoformat(),
        "last_observed_at": duplicate.last_observed_at.isoformat(),
    }

    aliases = list(primary.aliases or [])
    for alias in [duplicate.entity_name, *(duplicate.aliases or [])]:
        key = normalize_entity_name(alias, primary.entity_type)
        if key and key != primary_key and alias not in aliases:
            aliases.append(alias)
    primary.aliases = aliases[: settings.graph_max_aliases]
    primary.source_memory_ids = sorted(
        set(primary.source_memory_ids or []) | set(duplicate.source_memory_ids or [])
    )
    primary.confidence = max(primary.confidence, duplicate.confidence)
    primary.description = primary.description or duplicate.description
    primary.first_observed_at = min(primary.first_observed_at, duplicate.first_observed_at)
    primary.last_observed_at = max(primary.last_observed_at, duplicate.last_observed_at)
    primary.updated_at = now

    relationships = db.scalars(
        select(GraphRelationship).where(
            GraphRelationship.user_id == user_id,
            GraphRelationship.status != "archived",
            (GraphRelationship.source_entity_id == duplicate.entity_id)
            | (GraphRelationship.target_entity_id == duplicate.entity_id),
        )
    ).all()
    relationship_snapshots: list[dict] = []
    moved = 0
    collapsed = 0
    for relationship in relationships:
        snapshot = {
            "relationship_id": str(relationship.relationship_id),
            "source_entity_id": str(relationship.source_entity_id),
            "target_entity_id": str(relationship.target_entity_id),
            "status": relationship.status,
            "collapsed": False,
        }
        new_source = primary.entity_id if relationship.source_entity_id == duplicate.entity_id else relationship.source_entity_id
        new_target = primary.entity_id if relationship.target_entity_id == duplicate.entity_id else relationship.target_entity_id
        if new_source == new_target:
            relationship.status = "archived"
            relationship.updated_at = now
            snapshot["collapsed"] = True
            relationship_snapshots.append(snapshot)
            collapsed += 1
            continue
        existing = db.scalar(
            select(GraphRelationship).where(
                GraphRelationship.user_id == user_id,
                GraphRelationship.relationship_id != relationship.relationship_id,
                GraphRelationship.source_entity_id == new_source,
                GraphRelationship.target_entity_id == new_target,
                GraphRelationship.relationship_type == relationship.relationship_type,
                GraphRelationship.status == "active",
            )
        )
        if existing is not None and relationship.status == "active":
            existing.evidence_memory_ids = sorted(
                set(existing.evidence_memory_ids or [])
                | set(relationship.evidence_memory_ids or [])
            )
            existing.evidence = list(existing.evidence or []) + [
                item
                for item in (relationship.evidence or [])
                if item not in (existing.evidence or [])
            ]
            existing.confidence = max(existing.confidence, relationship.confidence)
            existing.updated_at = now
            relationship.status = "archived"
            relationship.superseded_by = existing.relationship_id
            snapshot["collapsed"] = True
            collapsed += 1
        else:
            relationship.source_entity_id = new_source
            relationship.target_entity_id = new_target
            relationship.updated_at = now
            moved += 1
        relationship_snapshots.append(snapshot)

    duplicate.status = "merged"
    duplicate.merged_into_id = primary.entity_id
    duplicate.updated_at = now

    record = GraphMergeRecord(
        user_id=user_id,
        primary_entity_id=primary.entity_id,
        merged_entity_id=duplicate.entity_id,
        snapshot={
            "primary": primary_snapshot,
            "duplicate": duplicate_snapshot,
            "relationships": relationship_snapshots,
        },
        status="active",
        performed_by=actor,
    )
    db.add(record)
    _record_history(
        db,
        user_id,
        action="merge",
        summary=f"Merged {duplicate.entity_name} into {primary.entity_name}.",
        entity_id=primary.entity_id,
        before={"merged_entity_id": str(duplicate.entity_id)},
        after={"merge_id": str(record.merge_id)},
        actor=actor,
    )
    db.commit()
    db.refresh(primary)
    return {
        "merge_id": record.merge_id,
        "primary": primary,
        "merged_entity_id": duplicate.entity_id,
        "moved_relationships": moved,
        "collapsed_relationships": collapsed,
        "aliases": list(primary.aliases or []),
    }


def undo_merge(db: Session, user_id: UUID, merge_id: UUID) -> GraphEntity:
    record = db.scalar(
        select(GraphMergeRecord).where(
            GraphMergeRecord.merge_id == merge_id, GraphMergeRecord.user_id == user_id
        )
    )
    if record is None:
        raise LookupError("Merge record not found.")
    if record.status != "active":
        raise ValueError("This merge has already been undone.")

    primary = db.scalar(
        select(GraphEntity).where(
            GraphEntity.entity_id == record.primary_entity_id, GraphEntity.user_id == user_id
        )
    )
    duplicate = db.scalar(
        select(GraphEntity).where(
            GraphEntity.entity_id == record.merged_entity_id, GraphEntity.user_id == user_id
        )
    )
    if primary is None or duplicate is None:
        raise LookupError("The merged entities no longer exist.")

    now = _utcnow()
    snapshot = record.snapshot or {}
    primary_snapshot = snapshot.get("primary", {})
    duplicate_snapshot = snapshot.get("duplicate", {})
    primary.aliases = list(primary_snapshot.get("aliases", primary.aliases or []))
    primary.source_memory_ids = list(
        primary_snapshot.get("source_memory_ids", primary.source_memory_ids or [])
    )
    primary.description = primary_snapshot.get("description", primary.description)
    primary.updated_at = now

    duplicate.status = duplicate_snapshot.get("status", "pending_review")
    duplicate.merged_into_id = None
    duplicate.entity_name = duplicate_snapshot.get("entity_name", duplicate.entity_name)
    duplicate.normalized_name = duplicate_snapshot.get("normalized_name", duplicate.normalized_name)
    duplicate.description = duplicate_snapshot.get("description", duplicate.description)
    duplicate.aliases = list(duplicate_snapshot.get("aliases", duplicate.aliases or []))
    duplicate.confidence = duplicate_snapshot.get("confidence", duplicate.confidence)
    duplicate.source_memory_ids = list(
        duplicate_snapshot.get("source_memory_ids", duplicate.source_memory_ids or [])
    )
    duplicate.updated_at = now

    for item in snapshot.get("relationships", []):
        relationship = db.get(GraphRelationship, UUID(item["relationship_id"]))
        if relationship is None or relationship.user_id != user_id:
            continue
        original_source = UUID(item["source_entity_id"])
        original_target = UUID(item["target_entity_id"])
        relationship.source_entity_id = original_source
        relationship.target_entity_id = original_target
        if item.get("collapsed"):
            # Another active edge may already represent this fact after undo.
            duplicate_active = db.scalar(
                select(GraphRelationship).where(
                    GraphRelationship.user_id == user_id,
                    GraphRelationship.relationship_id != relationship.relationship_id,
                    GraphRelationship.source_entity_id == original_source,
                    GraphRelationship.target_entity_id == original_target,
                    GraphRelationship.relationship_type == relationship.relationship_type,
                    GraphRelationship.status == "active",
                )
            )
            if duplicate_active is None:
                relationship.status = item.get("status", "active")
                relationship.superseded_by = None
            else:
                relationship.status = "historical"
                relationship.valid_until = relationship.valid_until or now
                relationship.superseded_by = duplicate_active.relationship_id
        else:
            relationship.status = item.get("status", "active")
        relationship.updated_at = now

    record.status = "undone"
    record.undone_at = now
    _record_history(
        db,
        user_id,
        action="merge_undo",
        summary=f"Undid merge of {duplicate.entity_name} into {primary.entity_name}.",
        entity_id=primary.entity_id,
        before={"merge_id": str(merge_id)},
        after={"restored_entity_id": str(duplicate.entity_id)},
    )
    db.commit()
    db.refresh(duplicate)
    return duplicate

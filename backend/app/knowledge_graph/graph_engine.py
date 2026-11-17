"""Public graph operations: CRUD, search, traversal, history and rebuild."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.knowledge_graph import (
    graph_builder,
    graph_merger,
    graph_retriever,
    graph_traversal,
    graph_visualizer,
)
from app.knowledge_graph.graph_schemas import GraphPath
from app.knowledge_graph.graph_validator import (
    GraphConflictError,
    GraphNotFoundError,
    GraphValidationError,
    assert_relationship_owned,
    validate_entity_type,
    validate_pair,
    validate_relationship_type,
)
from app.models.graph import (
    GraphEntity,
    GraphHistory,
    GraphMergeRecord,
    GraphRelationship,
    GraphSyncRecord,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _record(
    db: Session,
    user_id: UUID,
    *,
    action: str,
    summary: str,
    entity_id: UUID | None = None,
    relationship_id: UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        GraphHistory(
            user_id=user_id,
            entity_id=entity_id,
            relationship_id=relationship_id,
            action=action,
            summary=summary[:500],
            actor="user",
            before=before,
            after=after,
        )
    )


def _entity_snapshot(entity: GraphEntity) -> dict:
    return {
        "entity_name": entity.entity_name,
        "entity_type": entity.entity_type,
        "description": entity.description,
        "aliases": list(entity.aliases or []),
        "confidence": entity.confidence,
        "status": entity.status,
    }


def _relationship_snapshot(relationship: GraphRelationship) -> dict:
    return {
        "relationship_type": relationship.relationship_type,
        "description": relationship.description,
        "confidence": relationship.confidence,
        "status": relationship.status,
        "valid_from": relationship.valid_from.isoformat() if relationship.valid_from else None,
        "valid_until": relationship.valid_until.isoformat() if relationship.valid_until else None,
    }


def list_entities(
    db: Session,
    user_id: UUID,
    *,
    entity_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[GraphEntity], int]:
    predicates = [GraphEntity.user_id == user_id]
    if entity_type:
        predicates.append(GraphEntity.entity_type == entity_type)
    if status:
        predicates.append(GraphEntity.status == status)
    if search:
        needle = search.casefold().strip()
        predicates.append(
            or_(
                func.lower(GraphEntity.entity_name).contains(needle),
                func.lower(GraphEntity.normalized_name).contains(needle),
            )
        )
    total = db.scalar(select(func.count()).select_from(GraphEntity).where(*predicates)) or 0
    rows = db.scalars(
        select(GraphEntity)
        .where(*predicates)
        .order_by(GraphEntity.updated_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total


def get_entity(db: Session, user_id: UUID, entity_id: UUID) -> GraphEntity:
    row = db.scalar(
        select(GraphEntity).where(
            GraphEntity.entity_id == entity_id, GraphEntity.user_id == user_id
        )
    )
    if row is None:
        raise GraphNotFoundError("Entity not found.")
    return row


def create_entity(
    db: Session,
    user_id: UUID,
    *,
    entity_name: str,
    entity_type: str,
    description: str | None = None,
    aliases: list[str] | None = None,
    confidence: float = 0.9,
) -> GraphEntity:
    validate_entity_type(entity_type)
    name = " ".join(entity_name.split()).strip()
    if not name:
        raise GraphValidationError("Entity name cannot be blank.")
    if not 0 <= confidence <= 1:
        raise GraphValidationError("Confidence must be between 0 and 1.")
    normalized = graph_merger.normalize_entity_name(name, entity_type)
    existing = graph_merger.find_entity(db, user_id, name, entity_type)
    if existing is not None:
        raise GraphConflictError(f"An entity named {existing.entity_name} already exists.")
    cleaned_aliases: list[str] = []
    for alias in aliases or []:
        value = " ".join(alias.split()).strip()
        if value and value not in cleaned_aliases and value.casefold() != name.casefold():
            cleaned_aliases.append(value)
    now = _utcnow()
    entity = GraphEntity(
        user_id=user_id,
        entity_name=name,
        normalized_name=normalized,
        entity_type=entity_type,
        description=description,
        aliases=cleaned_aliases[: settings.graph_max_aliases],
        confidence=confidence,
        source_memory_ids=[],
        status="active",
        first_observed_at=now,
        last_observed_at=now,
    )
    db.add(entity)
    db.flush()
    _record(
        db,
        user_id,
        action="create_entity",
        summary=f"Created {entity_type} entity {name}.",
        entity_id=entity.entity_id,
        after=_entity_snapshot(entity),
    )
    db.commit()
    db.refresh(entity)
    return entity


def update_entity(
    db: Session,
    user_id: UUID,
    entity_id: UUID,
    changes: dict,
) -> GraphEntity:
    entity = get_entity(db, user_id, entity_id)
    if entity.status == "merged":
        raise GraphValidationError("Merged entities cannot be edited; undo the merge first.")
    before = _entity_snapshot(entity)

    if "entity_type" in changes and changes["entity_type"] is not None:
        validate_entity_type(changes["entity_type"])
        entity.entity_type = changes["entity_type"]
    if "entity_name" in changes and changes["entity_name"] is not None:
        new_name = " ".join(changes["entity_name"].split()).strip()
        if not new_name:
            raise GraphValidationError("Entity name cannot be blank.")
        if new_name.casefold() != entity.entity_name.casefold():
            aliases = list(entity.aliases or [])
            if entity.entity_name not in aliases:
                aliases.append(entity.entity_name)
            entity.aliases = aliases[: settings.graph_max_aliases]
            entity.entity_name = new_name
    if "description" in changes:
        entity.description = changes["description"]
    if "aliases" in changes and changes["aliases"] is not None:
        entity.aliases = list(dict.fromkeys(changes["aliases"]))[: settings.graph_max_aliases]
    if "confidence" in changes and changes["confidence"] is not None:
        if not 0 <= changes["confidence"] <= 1:
            raise GraphValidationError("Confidence must be between 0 and 1.")
        entity.confidence = changes["confidence"]
    if "status" in changes and changes["status"] is not None:
        if changes["status"] not in {"active", "pending_review", "archived"}:
            raise GraphValidationError("Unsupported entity status.")
        entity.status = changes["status"]

    entity.normalized_name = graph_merger.normalize_entity_name(entity.entity_name, entity.entity_type)
    duplicate = db.scalar(
        select(GraphEntity).where(
            GraphEntity.user_id == user_id,
            GraphEntity.entity_type == entity.entity_type,
            GraphEntity.normalized_name == entity.normalized_name,
            GraphEntity.entity_id != entity.entity_id,
        )
    )
    if duplicate is not None:
        db.rollback()
        raise GraphConflictError(f"Another entity already uses the name {duplicate.entity_name}.")
    entity.updated_at = _utcnow()
    _record(
        db,
        user_id,
        action="update_entity",
        summary=f"Updated {entity.entity_type} entity {entity.entity_name}.",
        entity_id=entity.entity_id,
        before=before,
        after=_entity_snapshot(entity),
    )
    db.commit()
    db.refresh(entity)
    return entity


def delete_entity(db: Session, user_id: UUID, entity_id: UUID) -> dict:
    entity = get_entity(db, user_id, entity_id)
    now = _utcnow()
    entity.status = "archived"
    entity.updated_at = now
    relationships = db.scalars(
        select(GraphRelationship).where(
            GraphRelationship.user_id == user_id,
            (GraphRelationship.source_entity_id == entity_id)
            | (GraphRelationship.target_entity_id == entity_id),
            GraphRelationship.status.in_(("active", "pending_review")),
        )
    ).all()
    for relationship in relationships:
        relationship.status = "archived"
        relationship.updated_at = now
    _record(
        db,
        user_id,
        action="archive_entity",
        summary=(
            f"Archived {entity.entity_name} and {len(relationships)} connected relationships. "
            "Source memories were not deleted."
        ),
        entity_id=entity.entity_id,
        before={"status": "active"},
        after={"status": "archived", "relationships_archived": len(relationships)},
    )
    db.commit()
    return {
        "deleted": True,
        "entity_id": str(entity.entity_id),
        "relationships_archived": len(relationships),
        "memories_deleted": 0,
    }


def list_relationships(
    db: Session,
    user_id: UUID,
    *,
    source_entity_id: UUID | None = None,
    target_entity_id: UUID | None = None,
    relationship_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[GraphRelationship], int]:
    predicates = [GraphRelationship.user_id == user_id]
    if source_entity_id:
        predicates.append(GraphRelationship.source_entity_id == source_entity_id)
    if target_entity_id:
        predicates.append(GraphRelationship.target_entity_id == target_entity_id)
    if relationship_type:
        predicates.append(GraphRelationship.relationship_type == relationship_type)
    if status:
        predicates.append(GraphRelationship.status == status)
    total = db.scalar(select(func.count()).select_from(GraphRelationship).where(*predicates)) or 0
    rows = db.scalars(
        select(GraphRelationship)
        .where(*predicates)
        .order_by(GraphRelationship.updated_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total


def create_relationship(
    db: Session,
    user_id: UUID,
    *,
    source_entity_id: UUID,
    target_entity_id: UUID,
    relationship_type: str,
    description: str | None = None,
    confidence: float = 0.9,
    valid_from: datetime | None = None,
) -> GraphRelationship:
    validate_relationship_type(relationship_type)
    if not 0 <= confidence <= 1:
        raise GraphValidationError("Confidence must be between 0 and 1.")
    source, target = assert_relationship_owned(db, user_id, source_entity_id, target_entity_id)
    if not validate_pair(source.entity_type, target.entity_type, relationship_type):
        raise GraphValidationError(
            f"{relationship_type} is not valid from {source.entity_type} to {target.entity_type}."
        )
    existing = db.scalar(
        select(GraphRelationship).where(
            GraphRelationship.user_id == user_id,
            GraphRelationship.source_entity_id == source_entity_id,
            GraphRelationship.target_entity_id == target_entity_id,
            GraphRelationship.relationship_type == relationship_type,
            GraphRelationship.status.in_(("active", "pending_review")),
        )
    )
    if existing is not None:
        raise GraphConflictError("This relationship already exists.")
    now = _utcnow()
    relationship = GraphRelationship(
        user_id=user_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relationship_type=relationship_type,
        description=description,
        confidence=confidence,
        evidence_memory_ids=[],
        evidence=[
            {
                "kind": "user",
                "user_confirmed": True,
                "excerpt": description or f"{source.entity_name} {relationship_type} {target.entity_name}",
                "observed_at": now.isoformat(),
            }
        ],
        valid_from=valid_from,
        status="active",
    )
    db.add(relationship)
    db.flush()
    _record(
        db,
        user_id,
        action="create_relationship",
        summary=f"Created {source.entity_name} {relationship_type} {target.entity_name}.",
        relationship_id=relationship.relationship_id,
        after=_relationship_snapshot(relationship),
    )
    db.commit()
    db.refresh(relationship)
    return relationship


def get_relationship(db: Session, user_id: UUID, relationship_id: UUID) -> GraphRelationship:
    row = db.scalar(
        select(GraphRelationship).where(
            GraphRelationship.relationship_id == relationship_id,
            GraphRelationship.user_id == user_id,
        )
    )
    if row is None:
        raise GraphNotFoundError("Relationship not found.")
    return row


def update_relationship(
    db: Session, user_id: UUID, relationship_id: UUID, changes: dict
) -> GraphRelationship:
    relationship = get_relationship(db, user_id, relationship_id)
    before = _relationship_snapshot(relationship)
    source, target = assert_relationship_owned(
        db, user_id, relationship.source_entity_id, relationship.target_entity_id
    )
    relationship_type = changes.get("relationship_type") or relationship.relationship_type
    validate_relationship_type(relationship_type)
    if not validate_pair(source.entity_type, target.entity_type, relationship_type):
        raise GraphValidationError(
            f"{relationship_type} is not valid from {source.entity_type} to {target.entity_type}."
        )
    relationship.relationship_type = relationship_type
    if "description" in changes:
        relationship.description = changes["description"]
    if "confidence" in changes and changes["confidence"] is not None:
        if not 0 <= changes["confidence"] <= 1:
            raise GraphValidationError("Confidence must be between 0 and 1.")
        relationship.confidence = changes["confidence"]
    if "valid_from" in changes:
        relationship.valid_from = changes["valid_from"]
    if "valid_until" in changes:
        relationship.valid_until = changes["valid_until"]
    if "status" in changes and changes["status"] is not None:
        if changes["status"] not in {"active", "pending_review", "historical", "rejected", "archived"}:
            raise GraphValidationError("Unsupported relationship status.")
        relationship.status = changes["status"]
        if relationship.status == "historical" and relationship.valid_until is None:
            relationship.valid_until = _utcnow()
        if relationship.status == "active":
            relationship.valid_until = None
    relationship.updated_at = _utcnow()
    _record(
        db,
        user_id,
        action="update_relationship",
        summary=f"Updated {source.entity_name} {relationship.relationship_type} {target.entity_name}.",
        relationship_id=relationship.relationship_id,
        before=before,
        after=_relationship_snapshot(relationship),
    )
    db.commit()
    db.refresh(relationship)
    return relationship


def delete_relationship(db: Session, user_id: UUID, relationship_id: UUID) -> dict:
    relationship = get_relationship(db, user_id, relationship_id)
    relationship.status = "archived"
    relationship.updated_at = _utcnow()
    _record(
        db,
        user_id,
        action="archive_relationship",
        summary=f"Archived relationship {relationship.relationship_type}.",
        relationship_id=relationship.relationship_id,
        before={"status": "active"},
        after={"status": "archived"},
    )
    db.commit()
    return {"deleted": True, "relationship_id": str(relationship.relationship_id)}


def entity_history(db: Session, user_id: UUID, entity_id: UUID) -> list[GraphHistory]:
    get_entity(db, user_id, entity_id)
    relationship_ids = db.scalars(
        select(GraphRelationship.relationship_id).where(
            GraphRelationship.user_id == user_id,
            (GraphRelationship.source_entity_id == entity_id)
            | (GraphRelationship.target_entity_id == entity_id),
        )
    ).all()
    return list(
        db.scalars(
            select(GraphHistory)
            .where(
                GraphHistory.user_id == user_id,
                (GraphHistory.entity_id == entity_id)
                | (GraphHistory.relationship_id.in_(relationship_ids)),
            )
            .order_by(GraphHistory.created_at.desc())
            .limit(200)
        ).all()
    )


def activity(db: Session, user_id: UUID, *, limit: int = 50, offset: int = 0) -> dict:
    total = db.scalar(
        select(func.count()).select_from(GraphHistory).where(GraphHistory.user_id == user_id)
    ) or 0
    history = db.scalars(
        select(GraphHistory)
        .where(GraphHistory.user_id == user_id)
        .order_by(GraphHistory.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    syncs = db.scalars(
        select(GraphSyncRecord)
        .where(GraphSyncRecord.user_id == user_id)
        .order_by(GraphSyncRecord.created_at.desc())
        .limit(limit)
    ).all()
    return {"history": list(history), "sync_records": list(syncs), "total": total}


def resolve_start_entity(
    db: Session,
    user_id: UUID,
    *,
    start_entity_id: UUID | None,
    start_name: str | None,
) -> GraphEntity:
    if start_entity_id is not None:
        return get_entity(db, user_id, start_entity_id)
    if not start_name or not start_name.strip():
        raise GraphValidationError("Provide start_entity_id or start_name.")
    candidates: list[GraphEntity] = []
    for entity_type in (
        "project", "technology", "programming_language", "tool", "concept", "subject",
        "goal", "interest", "preference", "person", "organization", "location", "event",
        "product", "skill", "educational_institution",
    ):
        found = graph_merger.find_entity(db, user_id, start_name.strip(), entity_type)
        if found is not None and found.status == "active":
            candidates.append(found)
    if not candidates:
        raise GraphNotFoundError("No matching entity was found.")
    candidates.sort(
        key=lambda entity: graph_merger.name_similarity(entity.entity_name, start_name),
        reverse=True,
    )
    return candidates[0]


def traverse(
    db: Session,
    user_id: UUID,
    *,
    start_entity_id: UUID | None = None,
    start_name: str | None = None,
    max_depth: int = 2,
    direction: str = "both",
    relationship_types: set[str] | None = None,
    include_historical: bool = False,
) -> dict:
    start = resolve_start_entity(
        db, user_id, start_entity_id=start_entity_id, start_name=start_name
    )
    subgraph = graph_traversal.traverse(
        db,
        user_id,
        [start],
        max_depth=min(max_depth, settings.graph_max_depth),
        relationship_types=relationship_types,
        include_historical=include_historical,
        direction=direction,
    )
    from app.knowledge_graph import graph_ranker

    paths = graph_ranker.rank_paths(subgraph.paths, subgraph.edges)
    degree = Counter()
    for edge in subgraph.edges:
        degree[edge.source_entity_id] += 1
        degree[edge.target_entity_id] += 1
    return {
        "start": start,
        "nodes": [
            graph_visualizer._node(entity, degree.get(entity.entity_id, 0), start.entity_id)
            for entity in subgraph.nodes.values()
        ],
        "edges": [graph_visualizer._edge(edge) for edge in subgraph.edges],
        "paths": paths,
        "truncated": subgraph.truncated,
        "max_depth": min(max_depth, settings.graph_max_depth),
    }


def merge(
    db: Session,
    user_id: UUID,
    *,
    primary_entity_id: UUID,
    duplicate_entity_id: UUID,
    confirm_similar: bool,
) -> dict:
    return graph_merger.merge_entities(
        db,
        user_id,
        primary_entity_id,
        duplicate_entity_id,
        confirm_similar=confirm_similar,
    )


def undo_merge(db: Session, user_id: UUID, merge_id: UUID) -> GraphEntity:
    return graph_merger.undo_merge(db, user_id, merge_id)


def list_merges(db: Session, user_id: UUID, *, limit: int = 50) -> list[GraphMergeRecord]:
    return list(
        db.scalars(
            select(GraphMergeRecord)
            .where(GraphMergeRecord.user_id == user_id)
            .order_by(GraphMergeRecord.created_at.desc())
            .limit(limit)
        ).all()
    )


def rebuild(db: Session, user_id: UUID, *, include_pending: bool = True) -> dict:
    return graph_builder.rebuild(db, user_id, include_pending=include_pending)


def serialize_paths(paths: list[GraphPath], relationships: list[GraphRelationship]) -> list[dict]:
    lookup = {row.relationship_id: row for row in relationships}
    return [
        {
            "entity_ids": [str(entity_id) for entity_id in path.entity_ids],
            "relationship_ids": [str(relationship_id) for relationship_id in path.relationship_ids],
            "labels": path.labels,
            "depth": path.depth,
            "score": path.score,
            "historical": path.historical,
            "evidence_memory_ids": path.evidence_memory_ids,
            "relationship_types": [
                lookup[relationship_id].relationship_type
                for relationship_id in path.relationship_ids
                if relationship_id in lookup
            ],
        }
        for path in paths
    ]


def search(
    db: Session,
    user_id: UUID,
    query: str,
    *,
    max_depth: int = 2,
    include_historical: bool = False,
) -> dict:
    retrieval = graph_retriever.search(
        db, user_id, query, max_depth=max_depth, include_historical=include_historical
    )
    degree = Counter()
    for edge in retrieval.subgraph.edges:
        degree[edge.source_entity_id] += 1
        degree[edge.target_entity_id] += 1
    return {
        "query": query,
        "matched_entities": [
            graph_visualizer._node(entity, degree.get(entity.entity_id, 0), None)
            for entity in retrieval.seeds
        ],
        "nodes": [
            graph_visualizer._node(entity, degree.get(entity.entity_id, 0), None)
            for entity in retrieval.subgraph.nodes.values()
        ],
        "edges": [graph_visualizer._edge(edge) for edge in retrieval.subgraph.edges],
        "paths": serialize_paths(retrieval.paths, retrieval.subgraph.edges),
        "historical": retrieval.historical,
    }

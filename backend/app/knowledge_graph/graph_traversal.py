"""Bounded, user-scoped breadth-first traversal of the knowledge graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.knowledge_graph.graph_schemas import GraphPath
from app.models.graph import GraphEntity, GraphRelationship
from app.models.memory import Memory


@dataclass
class Subgraph:
    nodes: dict[UUID, GraphEntity] = field(default_factory=dict)
    edges: list[GraphRelationship] = field(default_factory=list)
    paths: list[GraphPath] = field(default_factory=list)
    truncated: bool = False


def approved_memory_ids(db: Session, user_id: UUID) -> set[str]:
    now = datetime.now(timezone.utc)
    return {
        str(memory_id)
        for memory_id in db.scalars(
            select(Memory.memory_id).where(
                Memory.user_id == user_id,
                Memory.approval_status == "approved",
                Memory.lifecycle_status == "active",
                or_(Memory.expires_at.is_(None), Memory.expires_at > now),
            )
        ).all()
    }


def evidence_supported(relationship: GraphRelationship, approved_ids: set[str]) -> bool:
    """A fact is retrievable only with approved-memory or explicit user support."""
    evidence = relationship.evidence or []
    if any(item.get("kind") == "user" and item.get("user_confirmed") for item in evidence):
        return True
    memory_ids = relationship.evidence_memory_ids or []
    if memory_ids:
        return any(memory_id in approved_ids for memory_id in memory_ids)
    # Graph facts created without memory evidence must be user-created.
    return not evidence


def retrievable_entities(db: Session, user_id: UUID) -> dict[UUID, GraphEntity]:
    rows = db.scalars(
        select(GraphEntity).where(
            GraphEntity.user_id == user_id,
            GraphEntity.status == "active",
        )
    ).all()
    return {row.entity_id: row for row in rows}


def _recent_activity(row: GraphRelationship) -> datetime:
    value = row.valid_from or row.updated_at
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def traverse(
    db: Session,
    user_id: UUID,
    seeds: list[GraphEntity],
    *,
    max_depth: int | None = None,
    relationship_types: set[str] | None = None,
    include_historical: bool = False,
    direction: str = "both",
    approved_ids: set[str] | None = None,
    limit_nodes: int | None = None,
    limit_edges: int | None = None,
) -> Subgraph:
    """Breadth-first traversal with depth, node and edge caps and path dedup."""
    depth_cap = min(max_depth or settings.graph_default_depth, settings.graph_max_depth)
    node_cap = limit_nodes or settings.graph_max_nodes
    edge_cap = limit_edges or settings.graph_max_edges
    approved = approved_ids if approved_ids is not None else approved_memory_ids(db, user_id)
    nodes = retrievable_entities(db, user_id)
    graph = Subgraph()
    for seed in seeds:
        if seed.user_id != user_id:
            continue
        live = nodes.get(seed.entity_id)
        if live is None:
            continue
        graph.nodes[seed.entity_id] = live

    allowed_status = {"active", "historical"} if include_historical else {"active"}
    frontier: list[tuple[UUID, list[UUID], list[UUID], list[str]]] = [
        (entity_id, [entity_id], [], [nodes[entity_id].entity_name])
        for entity_id in graph.nodes
    ]
    seen_paths: set[tuple[tuple[UUID, ...], tuple[UUID, ...]]] = set()
    seen_edges: set[UUID] = set()

    for depth in range(1, depth_cap + 1):
        if not frontier:
            break
        frontier_ids = {item[0] for item in frontier}
        predicates = [
            GraphRelationship.user_id == user_id,
            GraphRelationship.status.in_(allowed_status),
        ]
        if direction == "out":
            predicates.append(GraphRelationship.source_entity_id.in_(frontier_ids))
        elif direction == "in":
            predicates.append(GraphRelationship.target_entity_id.in_(frontier_ids))
        else:
            predicates.append(
                (GraphRelationship.source_entity_id.in_(frontier_ids))
                | (GraphRelationship.target_entity_id.in_(frontier_ids))
            )
        if relationship_types:
            predicates.append(GraphRelationship.relationship_type.in_(relationship_types))
        rows = db.scalars(
            select(GraphRelationship)
            .where(*predicates)
            .order_by(GraphRelationship.updated_at.desc())
            .limit(edge_cap * 2)
        ).all()

        next_frontier: list[tuple[UUID, list[UUID], list[UUID], list[str]]] = []
        for relationship in rows:
            if relationship.status == "historical" and not include_historical:
                continue
            if not evidence_supported(relationship, approved):
                continue
            if relationship.source_entity_id in frontier_ids:
                start_id, end_id = relationship.source_entity_id, relationship.target_entity_id
            elif direction == "both" and relationship.target_entity_id in frontier_ids:
                start_id, end_id = relationship.target_entity_id, relationship.source_entity_id
            else:
                continue
            if end_id not in nodes:
                continue

            parent = next(
                (item for item in frontier if item[0] == start_id), None
            )
            if parent is None:
                continue
            entity_ids = [*parent[1], end_id]
            relationship_ids = [*parent[2], relationship.relationship_id]
            labels = [*parent[3], nodes[end_id].entity_name]
            path_key = (tuple(entity_ids), tuple(relationship_ids))
            if path_key in seen_paths or end_id in parent[1]:
                continue
            if relationship.relationship_id not in seen_edges:
                if len(graph.edges) >= edge_cap:
                    graph.truncated = True
                    break
                seen_edges.add(relationship.relationship_id)
                graph.edges.append(relationship)
            seen_paths.add(path_key)
            graph.nodes[end_id] = nodes[end_id]
            graph.paths.append(
                GraphPath(
                    entity_ids=entity_ids,
                    relationship_ids=relationship_ids,
                    labels=labels,
                    depth=depth,
                    historical=relationship.status == "historical",
                    evidence_memory_ids=list(relationship.evidence_memory_ids or []),
                )
            )
            next_frontier.append((end_id, entity_ids, relationship_ids, labels))
            if len(graph.nodes) >= node_cap:
                graph.truncated = True
                break
        frontier = next_frontier
        if graph.truncated:
            break
    return graph


def neighbors(
    db: Session,
    user_id: UUID,
    entity_id: UUID,
    *,
    approved_ids: set[str] | None = None,
    include_historical: bool = False,
) -> Subgraph:
    seed = db.scalar(
        select(GraphEntity).where(
            GraphEntity.entity_id == entity_id, GraphEntity.user_id == user_id
        )
    )
    if seed is None:
        return Subgraph()
    return traverse(
        db,
        user_id,
        [seed],
        max_depth=1,
        include_historical=include_historical,
        approved_ids=approved_ids,
    )

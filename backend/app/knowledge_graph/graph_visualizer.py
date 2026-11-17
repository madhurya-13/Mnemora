"""Graph visualization payloads with filters and bounded expansion."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.knowledge_graph import graph_traversal
from app.models.graph import GraphEntity, GraphRelationship


def _node(entity: GraphEntity, degree: int, center_id: UUID | None) -> dict:
    return {
        "id": str(entity.entity_id),
        "label": entity.entity_name,
        "entity_type": entity.entity_type,
        "description": entity.description,
        "confidence": round(entity.confidence, 3),
        "status": entity.status,
        "degree": degree,
        "is_center": entity.entity_id == center_id,
        "first_observed_at": entity.first_observed_at.isoformat(),
        "last_observed_at": entity.last_observed_at.isoformat(),
        "aliases": list(entity.aliases or []),
    }


def _edge(relationship: GraphRelationship) -> dict:
    return {
        "id": str(relationship.relationship_id),
        "source": str(relationship.source_entity_id),
        "target": str(relationship.target_entity_id),
        "relationship_type": relationship.relationship_type,
        "label": relationship.relationship_type.replace("_", " ").title(),
        "description": relationship.description,
        "confidence": round(relationship.confidence, 3),
        "status": relationship.status,
        "valid_from": relationship.valid_from.isoformat() if relationship.valid_from else None,
        "valid_until": relationship.valid_until.isoformat() if relationship.valid_until else None,
        "evidence_memory_ids": list(relationship.evidence_memory_ids or []),
        "superseded_by": str(relationship.superseded_by) if relationship.superseded_by else None,
    }


def visualization(
    db: Session,
    user_id: UUID,
    *,
    entity_types: set[str] | None = None,
    relationship_types: set[str] | None = None,
    center_entity_id: UUID | None = None,
    search: str | None = None,
    depth: int = 2,
    include_isolated: bool = True,
    include_historical: bool = False,
    limit_nodes: int | None = None,
    limit_edges: int | None = None,
) -> dict:
    node_cap = min(limit_nodes or settings.graph_max_nodes, settings.graph_max_nodes)
    edge_cap = min(limit_edges or settings.graph_max_edges, settings.graph_max_edges)
    truncated = False

    if center_entity_id is not None:
        center = db.scalar(
            select(GraphEntity).where(
                GraphEntity.entity_id == center_entity_id, GraphEntity.user_id == user_id
            )
        )
        if center is None:
            raise LookupError("Entity not found.")
        subgraph = graph_traversal.traverse(
            db,
            user_id,
            [center],
            max_depth=min(depth, settings.graph_max_depth),
            relationship_types=relationship_types,
            include_historical=include_historical,
            limit_nodes=node_cap,
            limit_edges=edge_cap,
        )
        entities = list(subgraph.nodes.values())
        edges = subgraph.edges
        truncated = subgraph.truncated
    else:
        predicates = [GraphEntity.user_id == user_id, GraphEntity.status.in_(("active", "pending_review"))]
        if entity_types:
            predicates.append(GraphEntity.entity_type.in_(entity_types))
        rows = db.scalars(
            select(GraphEntity)
            .where(*predicates)
            .order_by(GraphEntity.updated_at.desc())
            .limit(node_cap + 1)
        ).all()
        if len(rows) > node_cap:
            rows = rows[:node_cap]
            truncated = True
        entities = list(rows)
        entity_ids = {entity.entity_id for entity in entities}
        edge_predicates = [
            GraphRelationship.user_id == user_id,
            GraphRelationship.source_entity_id.in_(entity_ids),
            GraphRelationship.target_entity_id.in_(entity_ids),
            GraphRelationship.status.in_(("active", "historical") if include_historical else ("active",)),
        ]
        if relationship_types:
            edge_predicates.append(GraphRelationship.relationship_type.in_(relationship_types))
        edges = list(
            db.scalars(
                select(GraphRelationship)
                .where(*edge_predicates)
                .order_by(GraphRelationship.updated_at.desc())
                .limit(edge_cap)
            ).all()
        )

    if entity_types:
        entities = [entity for entity in entities if entity.entity_type in entity_types]
    if search:
        needle = search.casefold().strip()
        entities = [
            entity
            for entity in entities
            if needle in entity.entity_name.casefold()
            or any(needle in alias.casefold() for alias in (entity.aliases or []))
        ]
    if relationship_types:
        edges = [edge for edge in edges if edge.relationship_type in relationship_types]
    included_ids = {entity.entity_id for entity in entities}
    edges = [
        edge
        for edge in edges
        if edge.source_entity_id in included_ids and edge.target_entity_id in included_ids
    ]

    degree = Counter()
    for edge in edges:
        degree[edge.source_entity_id] += 1
        degree[edge.target_entity_id] += 1
    if not include_isolated and center_entity_id is None:
        entities = [entity for entity in entities if degree.get(entity.entity_id, 0) > 0]

    entities.sort(
        key=lambda entity: (
            entity.entity_id != center_entity_id,
            -degree.get(entity.entity_id, 0),
            entity.entity_name.casefold(),
        )
    )
    return {
        "nodes": [_node(entity, degree.get(entity.entity_id, 0), center_entity_id) for entity in entities],
        "edges": [_edge(edge) for edge in edges],
        "total_nodes": len(entities),
        "total_edges": len(edges),
        "truncated": truncated,
    }


def connections(
    db: Session,
    user_id: UUID,
    entity_id: UUID,
    *,
    depth: int = 1,
    direction: str = "both",
    include_historical: bool = False,
    relationship_types: set[str] | None = None,
) -> dict:
    entity = db.scalar(
        select(GraphEntity).where(
            GraphEntity.entity_id == entity_id, GraphEntity.user_id == user_id
        )
    )
    if entity is None:
        raise LookupError("Entity not found.")
    subgraph = graph_traversal.traverse(
        db,
        user_id,
        [entity],
        max_depth=min(depth, settings.graph_max_depth),
        relationship_types=relationship_types,
        include_historical=include_historical,
        direction=direction,
    )
    degree = Counter()
    for edge in subgraph.edges:
        degree[edge.source_entity_id] += 1
        degree[edge.target_entity_id] += 1
    return {
        "entity_id": str(entity.entity_id),
        "nodes": [_node(row, degree.get(row.entity_id, 0), entity.entity_id) for row in subgraph.nodes.values()],
        "edges": [_edge(edge) for edge in subgraph.edges],
        "truncated": subgraph.truncated,
    }

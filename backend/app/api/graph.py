"""Owner-scoped knowledge graph API: entities, relationships, retrieval and insights."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.knowledge_graph import graph_engine, graph_insights, graph_merger, graph_visualizer
from app.knowledge_graph.graph_validator import (
    GraphConflictError,
    GraphNotFoundError,
    GraphValidationError,
)
from app.models.graph import GraphEntity, GraphMergeRecord, GraphRelationship
from app.models.user import User
from app.schemas.graph import (
    GraphActivityResponse,
    GraphConnection,
    GraphDuplicateCandidate,
    GraphEntityCreate,
    GraphEntityDetail,
    GraphEntityPage,
    GraphEntityResponse,
    GraphEntityUpdate,
    GraphHealthResponse,
    GraphHistoryResponse,
    GraphInsightsResponse,
    GraphMergeRecordResponse,
    GraphMergeRequest,
    GraphMergeResponse,
    GraphMergeUndoResponse,
    GraphPathResponse,
    GraphRebuildRequest,
    GraphRebuildResponse,
    GraphRelationshipCreate,
    GraphRelationshipPage,
    GraphRelationshipResponse,
    GraphRelationshipUpdate,
    GraphSearchRequest,
    GraphSearchResponse,
    GraphTraverseRequest,
    GraphTraverseResponse,
    GraphVisualizationResponse,
)
from app.services.session_service import get_current_user

router = APIRouter(prefix="/api/v1/graph", tags=["knowledge-graph"])


def _not_found(message: str = "Entity not found.") -> HTTPException:
    return HTTPException(status_code=404, detail=message)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def _invalid(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _relationship_payload(
    db: Session, relationship: GraphRelationship
) -> GraphRelationshipResponse:
    source = db.get(GraphEntity, relationship.source_entity_id)
    target = db.get(GraphEntity, relationship.target_entity_id)
    return GraphRelationshipResponse(
        relationship_id=relationship.relationship_id,
        source_entity_id=relationship.source_entity_id,
        target_entity_id=relationship.target_entity_id,
        relationship_type=relationship.relationship_type,
        description=relationship.description,
        confidence=relationship.confidence,
        evidence_memory_ids=list(relationship.evidence_memory_ids or []),
        evidence=list(relationship.evidence or []),
        valid_from=relationship.valid_from,
        valid_until=relationship.valid_until,
        status=relationship.status,
        superseded_by=relationship.superseded_by,
        created_at=relationship.created_at,
        updated_at=relationship.updated_at,
        source_entity_name=source.entity_name if source is not None else None,
        target_entity_name=target.entity_name if target is not None else None,
    )


@router.get("/health", response_model=GraphHealthResponse)
def graph_health(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> GraphHealthResponse:
    from app.config import settings

    entities = db.scalar(
        select(func.count()).select_from(GraphEntity).where(GraphEntity.user_id == user.user_id)
    ) or 0
    relationships = db.scalar(
        select(func.count())
        .select_from(GraphRelationship)
        .where(GraphRelationship.user_id == user.user_id)
    ) or 0
    active = db.scalar(
        select(func.count())
        .select_from(GraphRelationship)
        .where(GraphRelationship.user_id == user.user_id, GraphRelationship.status == "active")
    ) or 0
    pending = db.scalar(
        select(func.count())
        .select_from(GraphRelationship)
        .where(
            GraphRelationship.user_id == user.user_id,
            GraphRelationship.status == "pending_review",
        )
    ) or 0
    from app.models.graph import GraphSyncRecord

    sync_pending = db.scalar(
        select(func.count())
        .select_from(GraphSyncRecord)
        .where(GraphSyncRecord.user_id == user.user_id, GraphSyncRecord.status == "pending")
    ) or 0
    sync_failed = db.scalar(
        select(func.count())
        .select_from(GraphSyncRecord)
        .where(GraphSyncRecord.user_id == user.user_id, GraphSyncRecord.status == "failed")
    ) or 0
    return GraphHealthResponse(
        enabled=settings.knowledge_graph_enabled,
        entities=entities,
        relationships=relationships,
        active_relationships=active,
        pending_review=pending,
        sync_pending=sync_pending,
        sync_failed=sync_failed,
        max_depth=settings.graph_max_depth,
    )


@router.get("/entities", response_model=GraphEntityPage)
def list_entities(
    entity_type: str | None = Query(default=None, max_length=40),
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphEntityPage:
    rows, total = graph_engine.list_entities(
        db,
        user.user_id,
        entity_type=entity_type,
        status=status_filter,
        search=search,
        limit=limit,
        offset=offset,
    )
    return GraphEntityPage(items=rows, total=total, limit=limit, offset=offset)


@router.post("/entities", response_model=GraphEntityResponse, status_code=status.HTTP_201_CREATED)
def create_entity(
    payload: GraphEntityCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphEntity:
    try:
        return graph_engine.create_entity(
            db,
            user.user_id,
            entity_name=payload.entity_name,
            entity_type=payload.entity_type,
            description=payload.description,
            aliases=payload.aliases,
            confidence=payload.confidence,
        )
    except GraphConflictError as error:
        raise _conflict(str(error)) from error
    except GraphValidationError as error:
        raise _invalid(str(error)) from error


@router.post("/entities/merge", response_model=GraphMergeResponse)
def merge_entities(
    payload: GraphMergeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphMergeResponse:
    try:
        result = graph_engine.merge(
            db,
            user.user_id,
            primary_entity_id=payload.primary_entity_id,
            duplicate_entity_id=payload.duplicate_entity_id,
            confirm_similar=payload.confirm_similar,
        )
        return GraphMergeResponse(
            merge_id=result["merge_id"],
            primary=GraphEntityResponse.model_validate(result["primary"]),
            merged_entity_id=result["merged_entity_id"],
            moved_relationships=result["moved_relationships"],
            collapsed_relationships=result["collapsed_relationships"],
            aliases=result["aliases"],
        )
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error
    except LookupError as error:
        raise _not_found(str(error)) from error
    except PermissionError as error:
        raise _conflict(str(error)) from error
    except ValueError as error:
        raise _invalid(str(error)) from error


@router.get("/merges", response_model=list[GraphMergeRecordResponse])
def list_merges(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[GraphMergeRecord]:
    return graph_engine.list_merges(db, user.user_id, limit=limit)


@router.post("/entities/merge/{merge_id}/undo", response_model=GraphMergeUndoResponse)
def undo_merge(
    merge_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphMergeUndoResponse:
    try:
        entity = graph_engine.undo_merge(db, user.user_id, merge_id)
        return GraphMergeUndoResponse(
            undone=True, restored_entity=GraphEntityResponse.model_validate(entity)
        )
    except LookupError as error:
        raise _not_found(str(error)) from error
    except ValueError as error:
        raise _invalid(str(error)) from error


@router.get("/entities/{entity_id}", response_model=GraphEntityDetail)
def get_entity(
    entity_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphEntityDetail:
    try:
        entity = graph_engine.get_entity(db, user.user_id, entity_id)
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error
    relationships = db.scalars(
        select(GraphRelationship).where(
            GraphRelationship.user_id == user.user_id,
            (GraphRelationship.source_entity_id == entity_id)
            | (GraphRelationship.target_entity_id == entity_id),
            GraphRelationship.status != "archived",
        )
    ).all()
    connections: list[GraphConnection] = []
    incoming = outgoing = 0
    for relationship in relationships:
        if relationship.source_entity_id == entity_id:
            outgoing += 1
            other = db.get(GraphEntity, relationship.target_entity_id)
            direction = "outgoing"
        else:
            incoming += 1
            other = db.get(GraphEntity, relationship.source_entity_id)
            direction = "incoming"
        if other is None:
            continue
        connections.append(
            GraphConnection(
                relationship_id=relationship.relationship_id,
                relationship_type=relationship.relationship_type,
                direction=direction,
                entity=GraphEntityResponse.model_validate(other),
                description=relationship.description,
                confidence=relationship.confidence,
                status=relationship.status,
                valid_from=relationship.valid_from,
                valid_until=relationship.valid_until,
                evidence_memory_ids=list(relationship.evidence_memory_ids or []),
            )
        )
    suggestions = graph_merger.duplicate_candidates(db, user.user_id, entity)
    return GraphEntityDetail(
        **GraphEntityResponse.model_validate(entity).model_dump(),
        connections=connections,
        possible_duplicates=[GraphDuplicateCandidate(**item) for item in suggestions],
        incoming_count=incoming,
        outgoing_count=outgoing,
    )


@router.patch("/entities/{entity_id}", response_model=GraphEntityResponse)
def update_entity(
    entity_id: UUID,
    payload: GraphEntityUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphEntity:
    try:
        return graph_engine.update_entity(
            db, user.user_id, entity_id, payload.model_dump(exclude_unset=True)
        )
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error
    except GraphConflictError as error:
        raise _conflict(str(error)) from error
    except GraphValidationError as error:
        raise _invalid(str(error)) from error


@router.delete("/entities/{entity_id}")
def delete_entity(
    entity_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return graph_engine.delete_entity(db, user.user_id, entity_id)
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error


@router.get("/entities/{entity_id}/connections", response_model=GraphVisualizationResponse)
def entity_connections(
    entity_id: UUID,
    depth: int = Query(default=1, ge=1, le=4),
    direction: str = Query(default="both", pattern="^(both|out|in)$"),
    include_historical: bool = Query(default=False),
    relationship_types: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphVisualizationResponse:
    try:
        payload = graph_visualizer.connections(
            db,
            user.user_id,
            entity_id,
            depth=depth,
            direction=direction,
            include_historical=include_historical,
            relationship_types=set(relationship_types) if relationship_types else None,
        )
    except LookupError as error:
        raise _not_found(str(error)) from error
    return GraphVisualizationResponse(
        nodes=payload["nodes"],
        edges=payload["edges"],
        total_nodes=len(payload["nodes"]),
        total_edges=len(payload["edges"]),
        truncated=payload["truncated"],
    )


@router.get("/entities/{entity_id}/history", response_model=list[GraphHistoryResponse])
def entity_history(
    entity_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    try:
        return graph_engine.entity_history(db, user.user_id, entity_id)
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error


@router.get("/relationships", response_model=GraphRelationshipPage)
def list_relationships(
    source_entity_id: UUID | None = Query(default=None),
    target_entity_id: UUID | None = Query(default=None),
    relationship_type: str | None = Query(default=None, max_length=40),
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphRelationshipPage:
    rows, total = graph_engine.list_relationships(
        db,
        user.user_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relationship_type=relationship_type,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return GraphRelationshipPage(
        items=[_relationship_payload(db, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/relationships",
    response_model=GraphRelationshipResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_relationship(
    payload: GraphRelationshipCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphRelationshipResponse:
    try:
        relationship = graph_engine.create_relationship(
            db,
            user.user_id,
            source_entity_id=payload.source_entity_id,
            target_entity_id=payload.target_entity_id,
            relationship_type=payload.relationship_type,
            description=payload.description,
            confidence=payload.confidence,
            valid_from=payload.valid_from,
        )
        return _relationship_payload(db, relationship)
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error
    except GraphConflictError as error:
        raise _conflict(str(error)) from error
    except GraphValidationError as error:
        raise _invalid(str(error)) from error


@router.get("/relationships/{relationship_id}", response_model=GraphRelationshipResponse)
def get_relationship(
    relationship_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphRelationshipResponse:
    try:
        relationship = graph_engine.get_relationship(db, user.user_id, relationship_id)
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error
    return _relationship_payload(db, relationship)


@router.patch("/relationships/{relationship_id}", response_model=GraphRelationshipResponse)
def update_relationship(
    relationship_id: UUID,
    payload: GraphRelationshipUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphRelationshipResponse:
    try:
        relationship = graph_engine.update_relationship(
            db, user.user_id, relationship_id, payload.model_dump(exclude_unset=True)
        )
        return _relationship_payload(db, relationship)
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error
    except GraphValidationError as error:
        raise _invalid(str(error)) from error


@router.delete("/relationships/{relationship_id}")
def delete_relationship(
    relationship_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return graph_engine.delete_relationship(db, user.user_id, relationship_id)
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error


@router.get("/visualization", response_model=GraphVisualizationResponse)
def visualization(
    entity_types: list[str] | None = Query(default=None),
    relationship_types: list[str] | None = Query(default=None),
    center_entity_id: UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    depth: int = Query(default=2, ge=1, le=4),
    include_isolated: bool = Query(default=True),
    include_historical: bool = Query(default=False),
    limit_nodes: int = Query(default=150, ge=10, le=500),
    limit_edges: int = Query(default=300, ge=10, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphVisualizationResponse:
    try:
        payload = graph_visualizer.visualization(
            db,
            user.user_id,
            entity_types=set(entity_types) if entity_types else None,
            relationship_types=set(relationship_types) if relationship_types else None,
            center_entity_id=center_entity_id,
            search=search,
            depth=depth,
            include_isolated=include_isolated,
            include_historical=include_historical,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
    except LookupError as error:
        raise _not_found(str(error)) from error
    return GraphVisualizationResponse(**payload)


@router.post("/search", response_model=GraphSearchResponse)
def search_graph(
    payload: GraphSearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphSearchResponse:
    result = graph_engine.search(
        db,
        user.user_id,
        payload.query,
        max_depth=payload.max_depth,
        include_historical=payload.include_historical,
    )
    return GraphSearchResponse(**result)


@router.post("/traverse", response_model=GraphTraverseResponse)
def traverse_graph(
    payload: GraphTraverseRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphTraverseResponse:
    try:
        result = graph_engine.traverse(
            db,
            user.user_id,
            start_entity_id=payload.start_entity_id,
            start_name=payload.start_name,
            max_depth=payload.max_depth,
            direction=payload.direction,
            relationship_types=set(payload.relationship_types) if payload.relationship_types else None,
            include_historical=payload.include_historical,
        )
    except GraphNotFoundError as error:
        raise _not_found(str(error)) from error
    except GraphValidationError as error:
        raise _invalid(str(error)) from error
    paths = [
        GraphPathResponse(
            entity_ids=[str(item) for item in path.entity_ids],
            relationship_ids=[str(item) for item in path.relationship_ids],
            labels=path.labels,
            depth=path.depth,
            score=path.score,
            historical=path.historical,
            evidence_memory_ids=path.evidence_memory_ids,
            relationship_types=[
                next(
                    (
                        edge["relationship_type"]
                        for edge in result["edges"]
                        if edge["id"] == str(relationship_id)
                    ),
                    "",
                )
                for relationship_id in path.relationship_ids
            ],
        )
        for path in result["paths"]
    ]
    return GraphTraverseResponse(
        start=GraphEntityResponse.model_validate(result["start"]),
        nodes=result["nodes"],
        edges=result["edges"],
        paths=paths,
        truncated=result["truncated"],
        max_depth=result["max_depth"],
    )


@router.get("/insights", response_model=GraphInsightsResponse)
def insights(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    entity_type: str | None = Query(default=None, max_length=40),
    relationship_type: str | None = Query(default=None, max_length=40),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphInsightsResponse:
    return GraphInsightsResponse(
        **graph_insights.compute_insights(
            db,
            user.user_id,
            date_from=date_from,
            date_to=date_to,
            entity_type=entity_type,
            relationship_type=relationship_type,
        )
    )


@router.get("/activity", response_model=GraphActivityResponse)
def graph_activity(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphActivityResponse:
    result = graph_engine.activity(db, user.user_id, limit=limit, offset=offset)
    return GraphActivityResponse(
        history=[GraphHistoryResponse.model_validate(row) for row in result["history"]],
        sync_records=result["sync_records"],
        total=result["total"],
    )


@router.post("/rebuild", response_model=GraphRebuildResponse)
def rebuild_graph(
    payload: GraphRebuildRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GraphRebuildResponse:
    result = graph_engine.rebuild(db, user.user_id, include_pending=payload.include_pending)
    return GraphRebuildResponse(**result)

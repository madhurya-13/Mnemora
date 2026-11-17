"""Validated request and response models for the knowledge graph API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EntityType = Literal[
    "person", "organization", "project", "technology", "programming_language",
    "skill", "educational_institution", "subject", "goal", "preference",
    "interest", "location", "event", "concept", "tool", "product",
]
RelationshipType = Literal[
    "STUDIES", "WORKS_ON", "DEVELOPS", "USES", "BUILT_WITH", "LEARNS",
    "INTERESTED_IN", "PREFERS", "BELONGS_TO", "HAS_GOAL", "HAS_FEATURE",
    "RELATED_TO", "DEPENDS_ON", "COMPLETED", "PARTICIPATES_IN", "LOCATED_IN",
    "REPLACED_BY", "EVOLVED_INTO",
]
EntityStatus = Literal["active", "pending_review", "archived", "merged"]
RelationshipStatus = Literal["active", "pending_review", "historical", "rejected", "archived"]
Direction = Literal["both", "out", "in"]


class GraphEntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_id: UUID
    entity_name: str
    normalized_name: str
    entity_type: str
    description: str | None
    aliases: list[str]
    confidence: float
    source_memory_ids: list[str]
    status: EntityStatus
    merged_into_id: UUID | None
    first_observed_at: datetime
    last_observed_at: datetime
    created_at: datetime
    updated_at: datetime


class GraphEntityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_name: str = Field(min_length=1, max_length=200)
    entity_type: EntityType
    description: str | None = Field(default=None, max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(default=0.9, ge=0, le=1)

    @field_validator("entity_name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Entity name cannot be blank.")
        return " ".join(value.split())


class GraphEntityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_name: str | None = Field(default=None, min_length=1, max_length=200)
    entity_type: EntityType | None = None
    description: str | None = Field(default=None, max_length=2000)
    aliases: list[str] | None = Field(default=None, max_length=12)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["active", "pending_review", "archived"] | None = None


class GraphDuplicateCandidate(BaseModel):
    entity_id: str
    entity_name: str
    entity_type: str
    similarity: float
    same_type: bool
    reason: str


class GraphConnection(BaseModel):
    relationship_id: UUID
    relationship_type: str
    direction: Literal["outgoing", "incoming"]
    entity: GraphEntityResponse
    description: str | None
    confidence: float
    status: str
    valid_from: datetime | None
    valid_until: datetime | None
    evidence_memory_ids: list[str]


class GraphEntityDetail(GraphEntityResponse):
    connections: list[GraphConnection] = Field(default_factory=list)
    possible_duplicates: list[GraphDuplicateCandidate] = Field(default_factory=list)
    incoming_count: int = 0
    outgoing_count: int = 0


class GraphEntityPage(BaseModel):
    items: list[GraphEntityResponse]
    total: int
    limit: int
    offset: int


class GraphRelationshipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: RelationshipType
    description: str | None = Field(default=None, max_length=500)
    confidence: float = Field(default=0.9, ge=0, le=1)
    valid_from: datetime | None = None


class GraphRelationshipUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_type: RelationshipType | None = None
    description: str | None = Field(default=None, max_length=500)
    confidence: float | None = Field(default=None, ge=0, le=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: RelationshipStatus | None = None


class GraphRelationshipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    relationship_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: str
    description: str | None
    confidence: float
    evidence_memory_ids: list[str]
    evidence: list[dict]
    valid_from: datetime | None
    valid_until: datetime | None
    status: RelationshipStatus
    superseded_by: UUID | None
    created_at: datetime
    updated_at: datetime
    source_entity_name: str | None = None
    target_entity_name: str | None = None


class GraphRelationshipPage(BaseModel):
    items: list[GraphRelationshipResponse]
    total: int
    limit: int
    offset: int


class GraphVisualizationNode(BaseModel):
    id: str
    label: str
    entity_type: str
    description: str | None
    confidence: float
    status: str
    degree: int
    is_center: bool
    first_observed_at: str
    last_observed_at: str
    aliases: list[str] = Field(default_factory=list)


class GraphVisualizationEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: str
    label: str
    description: str | None
    confidence: float
    status: str
    valid_from: str | None
    valid_until: str | None
    evidence_memory_ids: list[str] = Field(default_factory=list)
    superseded_by: str | None = None


class GraphVisualizationResponse(BaseModel):
    nodes: list[GraphVisualizationNode]
    edges: list[GraphVisualizationEdge]
    total_nodes: int
    total_edges: int
    truncated: bool


class GraphPathResponse(BaseModel):
    entity_ids: list[str]
    relationship_ids: list[str]
    labels: list[str]
    depth: int
    score: float
    historical: bool
    evidence_memory_ids: list[str]
    relationship_types: list[str]


class GraphTraverseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_entity_id: UUID | None = None
    start_name: str | None = Field(default=None, max_length=200)
    max_depth: int = Field(default=2, ge=1, le=5)
    direction: Direction = "both"
    relationship_types: list[RelationshipType] | None = None
    include_historical: bool = False

    @field_validator("max_depth")
    @classmethod
    def depth_within_configuration(cls, value: int) -> int:
        from app.config import settings

        if value > settings.graph_max_depth:
            raise ValueError(
                f"max_depth {value} exceeds the configured limit of {settings.graph_max_depth}."
            )
        return value


class GraphTraverseResponse(BaseModel):
    start: GraphEntityResponse
    nodes: list[GraphVisualizationNode]
    edges: list[GraphVisualizationEdge]
    paths: list[GraphPathResponse]
    truncated: bool
    max_depth: int


class GraphSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=500)
    max_depth: int = Field(default=2, ge=1, le=4)
    include_historical: bool = False

    @field_validator("max_depth")
    @classmethod
    def search_depth_within_configuration(cls, value: int) -> int:
        from app.config import settings

        if value > settings.graph_max_depth:
            raise ValueError(
                f"max_depth {value} exceeds the configured limit of {settings.graph_max_depth}."
            )
        return value

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Search query cannot be blank.")
        return value.strip()


class GraphSearchResponse(BaseModel):
    query: str
    matched_entities: list[GraphVisualizationNode]
    nodes: list[GraphVisualizationNode]
    edges: list[GraphVisualizationEdge]
    paths: list[GraphPathResponse]
    historical: bool


class GraphMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_entity_id: UUID
    duplicate_entity_id: UUID
    confirm_similar: bool = False


class GraphMergeResponse(BaseModel):
    merge_id: UUID
    primary: GraphEntityResponse
    merged_entity_id: UUID
    moved_relationships: int
    collapsed_relationships: int
    aliases: list[str]


class GraphMergeUndoResponse(BaseModel):
    undone: bool = True
    restored_entity: GraphEntityResponse


class GraphMergeRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    merge_id: UUID
    primary_entity_id: UUID
    merged_entity_id: UUID
    status: str
    performed_by: str
    created_at: datetime
    undone_at: datetime | None


class GraphHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    history_id: UUID
    entity_id: UUID | None
    relationship_id: UUID | None
    action: str
    summary: str
    actor: str
    before: dict | None
    after: dict | None
    created_at: datetime


class GraphSyncRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sync_id: UUID
    source_type: str
    source_id: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class GraphActivityResponse(BaseModel):
    history: list[GraphHistoryResponse]
    sync_records: list[GraphSyncRecordResponse]
    total: int


class GraphGrowthPoint(BaseModel):
    date: str
    entities: int


class GraphEntitySummary(BaseModel):
    entity_id: str
    entity_name: str
    entity_type: str
    confidence: float
    status: str
    created_at: str
    updated_at: str


class GraphConnectedEntity(GraphEntitySummary):
    degree: int


class GraphRelationshipSummary(BaseModel):
    relationship_id: str
    source_entity_id: str
    target_entity_id: str
    source_name: str
    target_name: str
    relationship_type: str
    confidence: float
    status: str
    updated_at: str
    valid_from: str | None
    valid_until: str | None


class GraphInsightsResponse(BaseModel):
    total_entities: int
    active_entities: int
    total_relationships: int
    active_relationships: int
    historical_relationships: int
    pending_entities: int
    pending_relationships: int
    entity_type_counts: dict[str, int]
    relationship_type_counts: dict[str, int]
    recently_added_entities: list[GraphEntitySummary]
    recently_updated_relationships: list[GraphRelationshipSummary]
    most_connected_entities: list[GraphConnectedEntity]
    isolated_entities: list[GraphEntitySummary]
    growth: list[GraphGrowthPoint]
    pending_corrections: int
    merge_count: int
    sync_pending: int
    sync_failed: int
    evidence_coverage: float


class GraphRebuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_pending: bool = True


class GraphRebuildResponse(BaseModel):
    memories_processed: int
    preference_links: int
    entities: int
    relationships: int


class GraphHealthResponse(BaseModel):
    enabled: bool
    entities: int
    relationships: int
    active_relationships: int
    pending_review: int
    sync_pending: int
    sync_failed: int
    max_depth: int

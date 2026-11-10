"""Validated request and response models for long-term memory operations."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MemoryType = Literal["stable", "temporary"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
MemoryCategory = Literal[
    "personal", "education", "career", "interests", "preferences", "projects", "goals", "temporary", "other"
]


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=3, max_length=2000)
    category: MemoryCategory
    importance: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    memory_type: MemoryType
    explicit: bool


class MemoryExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memories: list[MemoryCandidate] = Field(default_factory=list, max_length=8)


class MemoryCreateRequest(MemoryCandidate):
    explicit: bool = True
    source_conversation_id: UUID | None = None
    source_message_ids: list[UUID] = Field(default_factory=list, max_length=10)


class MemoryUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=3, max_length=2000)
    category: MemoryCategory | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    memory_type: MemoryType | None = None

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Memory content cannot be blank.")
        return value.strip() if value else value


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    memory_id: UUID
    content: str
    category: str
    importance: float
    confidence: float
    memory_type: str
    source: str
    source_conversation_id: UUID | None
    source_message_ids: list[str]
    approval_status: ApprovalStatus
    similar_memory_id: UUID | None
    vector_sync_status: str
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None
    expires_at: datetime | None


class MemoryPage(BaseModel):
    items: list[MemoryResponse]
    total: int
    limit: int
    offset: int


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    category: MemoryCategory | None = None
    min_importance: float | None = Field(default=None, ge=0, le=1)
    date_from: datetime | None = None
    date_to: datetime | None = None
    sort_by: Literal["relevance", "importance", "created_at", "updated_at"] = "relevance"

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Search query cannot be blank.")
        return value.strip()


class MemorySearchResult(BaseModel):
    memory: MemoryResponse
    similarity: float
    relevance: float
    keyword_score: float = 0
    recency_score: float = 0
    retrieval_reason: str = ""
    score_components: dict[str, float] = Field(default_factory=dict)


class MemorySearchResponse(BaseModel):
    query: str
    results: list[MemorySearchResult]


class MemoryStats(BaseModel):
    total: int
    approved: int
    pending: int
    rejected: int
    vector_sync_pending: int
    extraction_jobs_pending: int
    extraction_jobs_failed: int
    semantic_search_available: bool
    vector_index_available: bool
    automatic_save_enabled: bool
    categories: dict[str, int]
    recently_updated: list[MemoryResponse]


class QueryAnalysisResponse(BaseModel):
    intent: str
    categories: list[MemoryCategory]
    requires_personalization: bool
    requires_memory: bool
    query_type: Literal["factual", "recommendation", "planning", "historical", "follow_up", "personal", "general"]
    keywords: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class MemoryRetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class MemoryRetrieveItem(BaseModel):
    memory: MemoryResponse
    rank: int
    retrieval_reason: str
    semantic_score: float
    keyword_score: float
    importance_score: float
    confidence_score: float
    recency_score: float
    category_score: float
    usage_score: float
    final_score: float


class MemoryRetrieveResponse(BaseModel):
    query: str
    analysis: QueryAnalysisResponse
    selected: list[MemoryRetrieveItem]
    candidate_count: int
    excluded_count: int
    latency_ms: float


class MemoryConflictResponse(BaseModel):
    conflict_id: UUID
    conflict_type: str
    status: str
    summary: str
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None
    existing_memory: MemoryResponse
    new_memory: MemoryResponse


class MemoryConflictPage(BaseModel):
    items: list[MemoryConflictResponse]
    total: int


class MemoryConflictResolveRequest(BaseModel):
    resolution: Literal["keep_existing", "accept_update", "edit", "keep_unresolved"]
    edited_content: str | None = Field(default=None, min_length=3, max_length=2000)

    @field_validator("edited_content")
    @classmethod
    def edited_content_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Edited memory content cannot be blank.")
        return value.strip() if value else value


class MemoryHistoryResponse(BaseModel):
    history_id: UUID
    memory_id: UUID
    content: str
    category: str
    importance: float
    confidence: float
    memory_type: str
    approval_status: str
    change_reason: str
    created_at: datetime


class RetrievalEventSummary(BaseModel):
    event_id: UUID
    intent: str
    query_type: str
    category: str | None
    candidate_count: int
    selected_count: int
    excluded_count: int
    latency_ms: float
    created_at: datetime


class RetrievalStatsResponse(BaseModel):
    retrieval_count: int
    selected_count: int
    excluded_count: int
    average_latency_ms: float
    recently_retrieved: list[MemoryResponse]
    recently_accessed: list[MemoryResponse]
    high_importance: list[MemoryResponse]
    category_distribution: dict[str, int]
    recent_events: list[RetrievalEventSummary]

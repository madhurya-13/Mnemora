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

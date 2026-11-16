"""Validated schemas for adaptive preferences, patterns, feedback and memory health."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

PreferenceCategory = Literal[
    "communication_style",
    "learning_style",
    "programming",
    "technology",
    "project_workflow",
    "ui_ux",
    "content",
    "other",
]
PreferenceStatus = Literal["candidate", "confirmed", "rejected", "disabled"]
PatternType = Literal[
    "recurring_interest",
    "repeated_project_activity",
    "repeated_learning_topic",
    "repeated_workflow",
    "recurring_goal",
    "emerging_preference",
]
PatternStatus = Literal["candidate", "confirmed", "dismissed"]
FeedbackTarget = Literal["response", "memory", "preference"]
FeedbackType = Literal[
    "helpful",
    "not_helpful",
    "correct_personalization",
    "incorrect_personalization",
    "outdated_information",
    "irrelevant_memory",
    "correct",
    "incorrect",
    "update_requested",
    "no_longer_relevant",
    "important",
    "not_important",
]
LifecycleStatus = Literal[
    "active", "possibly_outdated", "superseded", "expired", "archived", "pending_review"
]


class PreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    preference_id: UUID
    category: str
    description: str
    normalized_key: str
    confidence: float
    evidence_count: int
    supporting_memory_ids: list[str]
    evidence: list[dict]
    status: PreferenceStatus
    first_observed_at: datetime
    last_observed_at: datetime
    created_at: datetime
    updated_at: datetime


class PreferencePage(BaseModel):
    items: list[PreferenceResponse]
    total: int
    limit: int
    offset: int


class PreferenceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, min_length=3, max_length=500)
    category: PreferenceCategory | None = None
    status: Literal["candidate", "confirmed", "disabled"] | None = None

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Preference description cannot be blank.")
        return value.strip() if value else value


class PreferenceConfirmRequest(BaseModel):
    description: str | None = Field(default=None, min_length=3, max_length=500)


class PatternResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pattern_id: UUID
    pattern_type: str
    description: str
    normalized_key: str
    evidence_count: int
    confidence: float
    supporting_conversation_ids: list[str]
    supporting_message_ids: list[str]
    first_observed_at: datetime
    last_observed_at: datetime
    status: PatternStatus
    created_at: datetime
    updated_at: datetime


class PatternPage(BaseModel):
    items: list[PatternResponse]
    total: int


class FeedbackCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: FeedbackTarget
    target_id: UUID
    feedback_type: FeedbackType
    comment: str | None = Field(default=None, max_length=1000)
    memory_ids: list[UUID] = Field(default_factory=list, max_length=20)
    preference_ids: list[UUID] = Field(default_factory=list, max_length=20)
    conversation_id: UUID | None = None
    message_id: UUID | None = None


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feedback_id: UUID
    target_type: str
    target_id: UUID
    feedback_type: str
    comment: str | None
    memory_ids: list[str]
    preference_ids: list[str]
    conversation_id: UUID | None
    message_id: UUID | None
    processed: bool
    created_at: datetime


class FeedbackPage(BaseModel):
    items: list[FeedbackResponse]
    total: int
    limit: int
    offset: int


class FeedbackInsights(BaseModel):
    total: int
    helpful_count: int
    not_helpful_count: int
    incorrect_personalization_count: int
    outdated_information_count: int
    correction_requests: int
    by_type: dict[str, int]
    recent: list[FeedbackResponse]


class EvolutionItem(BaseModel):
    memory_id: UUID
    previous_content: str
    new_content: str
    change_type: str
    change_reason: str
    source_conversation_id: UUID | None
    approval_status: str
    changed_at: datetime


class EvolutionPage(BaseModel):
    items: list[EvolutionItem]
    total: int


class MemoryHealthResponse(BaseModel):
    total_approved: int
    active: int
    possibly_outdated: int
    superseded: int
    expired: int
    archived: int
    pending_review: int
    low_utility: int
    frequently_used: list[dict]
    last_evaluated_at: datetime | None


class AdaptiveSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    preference_learning_enabled: bool
    auto_candidate_generation: bool
    pattern_detection_enabled: bool
    personalization_enabled: bool
    memory_decay_enabled: bool
    require_user_review: bool
    preference_confidence_threshold: float
    preference_evidence_threshold: int
    pattern_evidence_threshold: int
    updated_at: datetime


class AdaptiveSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preference_learning_enabled: bool | None = None
    auto_candidate_generation: bool | None = None
    pattern_detection_enabled: bool | None = None
    personalization_enabled: bool | None = None
    memory_decay_enabled: bool | None = None
    require_user_review: bool | None = None
    preference_confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    preference_evidence_threshold: int | None = Field(default=None, ge=2, le=20)
    pattern_evidence_threshold: int | None = Field(default=None, ge=2, le=20)


class LifecycleUpdateRequest(BaseModel):
    status: Literal["active", "possibly_outdated", "archived"]


class AdaptiveRunResponse(BaseModel):
    processed_jobs: int
    evaluated_memories: int
    detected_patterns: int

"""Internal, provider-free extraction models shared by the graph modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

ENTITY_TYPES: tuple[str, ...] = (
    "person",
    "organization",
    "project",
    "technology",
    "programming_language",
    "skill",
    "educational_institution",
    "subject",
    "goal",
    "preference",
    "interest",
    "location",
    "event",
    "concept",
    "tool",
    "product",
)

RELATIONSHIP_TYPES: tuple[str, ...] = (
    "STUDIES",
    "WORKS_ON",
    "DEVELOPS",
    "USES",
    "BUILT_WITH",
    "LEARNS",
    "INTERESTED_IN",
    "PREFERS",
    "BELONGS_TO",
    "HAS_GOAL",
    "HAS_FEATURE",
    "RELATED_TO",
    "DEPENDS_ON",
    "COMPLETED",
    "PARTICIPATES_IN",
    "LOCATED_IN",
    "REPLACED_BY",
    "EVOLVED_INTO",
)

ENTITY_STATUSES: tuple[str, ...] = ("active", "pending_review", "archived", "merged")
RELATIONSHIP_STATUSES: tuple[str, ...] = (
    "active",
    "pending_review",
    "historical",
    "rejected",
    "archived",
)

TECHNOLOGY_LIKE = {"technology", "programming_language", "tool", "product"}


@dataclass(frozen=True)
class EntityMention:
    """An entity candidate found in one piece of text."""

    name: str
    entity_type: str
    confidence: float = 0.6
    description: str | None = None
    start: int = 0
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationshipDraft:
    """A directed relationship candidate backed by explicit sentence evidence."""

    source_name: str
    source_type: str
    target_name: str
    target_type: str
    relationship_type: str
    description: str
    confidence: float = 0.65
    excerpt: str = ""
    temporal_action: str = "none"  # none | replace | close | historical
    replace_types: tuple[str, ...] = ()
    replace_target_types: tuple[str, ...] = ()


@dataclass
class ExtractionResult:
    entities: list[EntityMention] = field(default_factory=list)
    relationships: list[RelationshipDraft] = field(default_factory=list)


@dataclass
class GraphPath:
    """A retrieved path through the graph, with its concrete evidence."""

    entity_ids: list[UUID]
    relationship_ids: list[UUID]
    labels: list[str]
    depth: int
    score: float = 0.0
    historical: bool = False
    evidence_memory_ids: list[str] = field(default_factory=list)


def utc_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

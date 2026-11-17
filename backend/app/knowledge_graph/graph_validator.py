"""Validation for graph entities, relationships and extracted drafts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge_graph.graph_schemas import (
    ENTITY_TYPES,
    RELATIONSHIP_TYPES,
    RelationshipDraft,
)
from app.models.graph import GraphEntity

_PERSON = {"person"}
_PROJECT = {"project"}
_TECH = {"technology", "programming_language", "tool", "product"}
_ANY = set(ENTITY_TYPES)

# Directed source/target type compatibility. Anything not listed is rejected.
ALLOWED_PAIRS: dict[str, tuple[set[str], set[str]]] = {
    "STUDIES": (_PERSON, {"subject", "concept", "skill", "programming_language", "technology"}),
    "WORKS_ON": (_PERSON, _PROJECT),
    "DEVELOPS": (_PERSON, _PROJECT),
    "USES": (_PERSON | _PROJECT, _TECH),
    "BUILT_WITH": (_PROJECT | _TECH, _TECH),
    "LEARNS": (_PERSON, {"programming_language", "technology", "skill", "subject", "concept"}),
    "INTERESTED_IN": (_PERSON, _ANY),
    "PREFERS": (_PERSON, _ANY - {"person"}),
    "BELONGS_TO": (_PERSON, {"organization", "educational_institution"}),
    "HAS_GOAL": (_PERSON | _PROJECT, {"goal"}),
    "HAS_FEATURE": (_PROJECT | {"product"}, {"concept", "subject", "skill", "tool", "product", "technology"}),
    "RELATED_TO": (_ANY, _ANY),
    "DEPENDS_ON": (_PROJECT | _TECH, _TECH | _PROJECT),
    "COMPLETED": (_PERSON, {"goal", "project", "subject", "event"}),
    "PARTICIPATES_IN": (_PERSON, {"event", "organization", "project"}),
    "LOCATED_IN": (_PERSON | {"organization", "project", "event"}, {"location"}),
    "REPLACED_BY": (_ANY, _ANY),
    "EVOLVED_INTO": (_ANY, _ANY),
}


class GraphValidationError(ValueError):
    """Raised when a graph mutation would store an invalid fact."""


class GraphNotFoundError(LookupError):
    """Owner-scoped lookup failed."""


class GraphConflictError(RuntimeError):
    """A duplicate or contradictory graph fact already exists."""


def validate_entity_type(entity_type: str) -> str:
    if entity_type not in ENTITY_TYPES:
        raise GraphValidationError(f"Unsupported entity type: {entity_type}.")
    return entity_type


def validate_relationship_type(relationship_type: str) -> str:
    if relationship_type not in RELATIONSHIP_TYPES:
        raise GraphValidationError(f"Unsupported relationship type: {relationship_type}.")
    return relationship_type


def validate_confidence(value: float, *, field: str = "confidence") -> float:
    if not 0 <= value <= 1:
        raise GraphValidationError(f"{field} must be between 0 and 1.")
    return value


def validate_pair(source_type: str, target_type: str, relationship_type: str) -> bool:
    allowed = ALLOWED_PAIRS.get(relationship_type)
    if allowed is None:
        return False
    sources, targets = allowed
    return source_type in sources and target_type in targets


def validate_draft(draft: RelationshipDraft) -> bool:
    """Return True when a draft is structurally valid (never raise for extraction)."""
    if draft.source_name.casefold() == draft.target_name.casefold():
        return False
    if draft.source_type not in ENTITY_TYPES or draft.target_type not in ENTITY_TYPES:
        return False
    if draft.relationship_type not in RELATIONSHIP_TYPES:
        return False
    if not validate_pair(draft.source_type, draft.target_type, draft.relationship_type):
        return False
    return 0 <= draft.confidence <= 1


def get_owned_entity(db: Session, user_id: UUID, entity_id: UUID) -> GraphEntity:
    row = db.scalar(
        select(GraphEntity).where(
            GraphEntity.entity_id == entity_id,
            GraphEntity.user_id == user_id,
        )
    )
    if row is None:
        raise GraphNotFoundError("Entity not found.")
    return row


def assert_relationship_owned(
    db: Session, user_id: UUID, source_entity_id: UUID, target_entity_id: UUID
) -> tuple[GraphEntity, GraphEntity]:
    source = get_owned_entity(db, user_id, source_entity_id)
    target = get_owned_entity(db, user_id, target_entity_id)
    if source.entity_id == target.entity_id:
        raise GraphValidationError("An entity cannot be related to itself.")
    for entity in (source, target):
        if entity.status in {"archived", "merged"}:
            raise GraphValidationError("Archived or merged entities cannot receive relationships.")
    return source, target

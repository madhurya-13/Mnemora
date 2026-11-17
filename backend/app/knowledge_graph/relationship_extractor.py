"""Deterministic relationship extraction with explicit evidence requirements.

A relationship is only produced when the sentence contains an explicit verb or
connective that expresses it (for example "developing", "built with", "learning",
"prefers" or "is interested in"). Two entities merely appearing in the same
sentence never create an edge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.knowledge_graph.graph_schemas import EntityMention, RelationshipDraft

_DEVELOP = re.compile(r"\b(?:developing|building|creating|working\s+on|launching)\b", re.I)
_BUILT = re.compile(
    r"\b(?:using|built\s+with|built\s+using|is\s+built\s+with|uses|use|based\s+on|powered\s+by)\b",
    re.I,
)
_USE = re.compile(r"\b(?:use|using|work\s+with|working\s+with)\b", re.I)
_LEARN = re.compile(r"\b(?:learning|learn|studying|study|started\s+learning|picked\s+up)\b", re.I)
_PREFER = re.compile(r"\b(?:prefer|prefers|favourite|favorite|like|like\s+to\s+use|love|enjoy)\b", re.I)
_SWITCH = re.compile(r"\b(?:switched\s+to|moved\s+to|changed\s+to|now\s+using|now\s+learning|now\s+prefer)\b", re.I)
_CLOSE = re.compile(r"\b(?:no\s+longer|not\s+anymore|stopped)\b", re.I)
_HISTORICAL = re.compile(r"\b(?:used\s+to|previously|in\s+the\s+past|formerly)\b", re.I)
_INTEREST = re.compile(r"\b(?:interested\s+in|passionate\s+about|fascinated\s+by|curious\s+about)\b", re.I)
_FEATURE = re.compile(r"\b(?:has|have|includes?|supports?|features?|comes\s+with)\b", re.I)
_WITH = re.compile(r"\bwith\b", re.I)
_STUDY = re.compile(r"\b(?:study|studying|studies|studied|majoring\s+in)\b", re.I)
_STUDY_AT = re.compile(r"\b(?:study|studying|studies|studied)\s+at\b", re.I)
_WORK_AT = re.compile(r"\b(?:work|working|works|worked)\s+(?:at|for)\b", re.I)
_LIVE_IN = re.compile(r"\b(?:live|living|lives|lived|based|located)\s+in\b", re.I)
_GOAL = re.compile(r"\b(?:my\s+goal\s+is\s+to|i\s+want\s+to|i\s+aim\s+to|i\s+plan\s+to|i\s+hope\s+to)\b", re.I)
_COMPLETED = re.compile(r"\b(?:completed|finished|graduated\s+from)\b", re.I)
_DEPENDS = re.compile(r"\b(?:depends\s+on|relies\s+on|requires)\b", re.I)
_RELATED = re.compile(r"\b(?:is\s+related\s+to|related\s+to|connected\s+to|works?\s+with)\b", re.I)

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“(])|\n+")

_RELEVANCE = {
    "DEVELOPS": 0.78,
    "BUILT_WITH": 0.76,
    "USES": 0.7,
    "LEARNS": 0.72,
    "PREFERS": 0.72,
    "INTERESTED_IN": 0.68,
    "STUDIES": 0.7,
    "BELONGS_TO": 0.68,
    "HAS_GOAL": 0.7,
    "HAS_FEATURE": 0.7,
    "LOCATED_IN": 0.68,
    "COMPLETED": 0.7,
    "DEPENDS_ON": 0.68,
    "RELATED_TO": 0.6,
}

_TECH_TARGET_TYPES = {"technology", "programming_language", "tool", "product", "skill", "subject"}
_COMMON_REPLACE_SCOPE = {
    "types": ("LEARNS", "PREFERS", "STUDIES"),
    "target_types": ("programming_language", "technology", "skill", "subject"),
}


@dataclass(frozen=True)
class _Present:
    mention: EntityMention
    start: int


def _name_pattern(name: str) -> re.Pattern[str]:
    escaped = re.escape(name)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace(r"\.", r"\.?\s*")
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.I)


def _present_entities(sentence: str, entities: list[EntityMention]) -> list[_Present]:
    present: list[_Present] = []
    seen: set[tuple[str, str]] = set()
    for entity in entities:
        variants = [entity.name, *entity.aliases]
        best: re.Match[str] | None = None
        for variant in variants:
            match = _name_pattern(variant).search(sentence)
            if match is not None and (best is None or match.start() < best.start()):
                best = match
        if best is None:
            continue
        key = (entity.entity_type, entity.name.casefold())
        if key in seen:
            continue
        seen.add(key)
        present.append(_Present(entity, best.start()))
    return present


def _draft(
    source: EntityMention,
    target: EntityMention,
    relationship_type: str,
    *,
    excerpt: str,
    description: str,
    temporal_action: str = "none",
    replace_scope: dict[str, tuple[str, ...]] | None = None,
) -> RelationshipDraft:
    scope = replace_scope or {}
    return RelationshipDraft(
        source_name=source.name,
        source_type=source.entity_type,
        target_name=target.name,
        target_type=target.entity_type,
        relationship_type=relationship_type,
        description=description,
        confidence=_RELEVANCE.get(relationship_type, 0.6),
        excerpt=excerpt[:300],
        temporal_action=temporal_action,
        replace_types=scope.get("types", ()),
        replace_target_types=scope.get("target_types", ()),
    )


def extract_relationships(
    text: str,
    entities: list[EntityMention],
    *,
    user_entity: EntityMention | None = None,
) -> list[RelationshipDraft]:
    """Extract directed relationships that the sentence explicitly states."""
    if not text or not entities:
        return []
    user = user_entity or EntityMention(name="User", entity_type="person")

    drafts: list[RelationshipDraft] = []
    seen: set[tuple[str, str, str]] = set()
    last_project: EntityMention | None = None

    def add(draft: RelationshipDraft) -> None:
        key = (
            draft.source_name.casefold(),
            draft.relationship_type,
            draft.target_name.casefold(),
        )
        if key in seen:
            return
        seen.add(key)
        drafts.append(draft)

    for raw_sentence in _SENTENCE.split(text):
        sentence = raw_sentence.strip()
        if len(sentence) < 3:
            continue
        present = _present_entities(sentence, entities)
        if not present:
            continue

        projects = [item for item in present if item.mention.entity_type == "project"]
        pronoun_reference = re.match(
            r"\s*(?:it|this|that|they|he|she|my\s+project|the\s+project)\b", sentence, re.I
        )
        if projects:
            last_project = projects[0].mention
            project = projects[0].mention
            project_start = projects[0].start
        elif last_project is not None and pronoun_reference is not None:
            # "It is an AI assistant with persistent memory." continues the
            # previously named project; nothing else inherits across sentences.
            project = last_project
            project_start = 0
        else:
            project = None
            project_start = 0
        targets = [
            item
            for item in present
            if item.mention.entity_type != "project"
            and item.mention.entity_type != "person"
        ]
        techs = [item for item in targets if item.mention.entity_type in _TECH_TARGET_TYPES]
        excerpt = sentence.strip()

        # User -> DEVELOPS -> Project
        if project is not None and _DEVELOP.search(sentence):
            add(
                _draft(
                    user,
                    project,
                    "DEVELOPS",
                    excerpt=excerpt,
                    description=f"The user is developing {project.name}.",
                )
            )

        # Project -> BUILT_WITH -> Technology
        mentions_project = project is not None
        if mentions_project and _BUILT.search(sentence):
            for item in techs:
                add(
                    _draft(
                        project,
                        item.mention,
                        "BUILT_WITH",
                        excerpt=excerpt,
                        description=f"{project.name} is built with {item.mention.name}.",
                    )
                )
        elif not project and _USE.search(sentence):
            # User -> USES -> Technology, only when no project is the subject.
            for item in techs:
                add(
                    _draft(
                        user,
                        item.mention,
                        "USES",
                        excerpt=excerpt,
                        description=f"The user uses {item.mention.name}.",
                    )
                )

        # Project -> HAS_FEATURE -> Concept / subject
        feature_targets: list[_Present] = []
        if project is not None and _FEATURE.search(sentence):
            feature_targets.extend(targets)
        if project is not None:
            with_match = _WITH.search(sentence)
            if with_match is not None:
                for item in targets:
                    if item.start > with_match.start() and item.mention.entity_type in {
                        "concept",
                        "subject",
                        "skill",
                        "product",
                        "tool",
                    }:
                        feature_targets.append(item)
        for item in feature_targets:
            add(
                _draft(
                    project,
                    item.mention,
                    "HAS_FEATURE",
                    excerpt=excerpt,
                    description=f"{project.name} has the feature {item.mention.name}.",
                )
            )

        # Learning, preference and interest relationships
        learning = _LEARN.search(sentence)
        switching = _SWITCH.search(sentence)
        preferring = _PREFER.search(sentence)
        interested = _INTEREST.search(sentence)
        closing = _CLOSE.search(sentence)
        historical = _HISTORICAL.search(sentence)

        if interested is not None:
            for item in targets:
                add(
                    _draft(
                        user,
                        item.mention,
                        "INTERESTED_IN",
                        excerpt=excerpt,
                        description=f"The user is interested in {item.mention.name}.",
                    )
                )

        if switching is not None:
            for item in targets:
                add(
                    _draft(
                        user,
                        item.mention,
                        "PREFERS",
                        excerpt=excerpt,
                        description=f"The user now prefers {item.mention.name}.",
                        temporal_action="replace",
                        replace_scope=_COMMON_REPLACE_SCOPE,
                    )
                )
        elif closing is not None and (learning is not None or preferring is not None):
            for item in targets:
                add(
                    _draft(
                        user,
                        item.mention,
                        "LEARNS" if learning is not None else "PREFERS",
                        excerpt=excerpt,
                        description=f"The user no longer uses {item.mention.name}.",
                        temporal_action="close",
                        replace_scope=_COMMON_REPLACE_SCOPE,
                    )
                )
        elif learning is not None:
            action = "historical" if historical is not None else "none"
            for item in targets:
                if item.mention.entity_type in {"organization", "location", "event"}:
                    continue
                add(
                    _draft(
                        user,
                        item.mention,
                        "LEARNS",
                        excerpt=excerpt,
                        description=f"The user is learning {item.mention.name}.",
                        temporal_action=action,
                        replace_scope=_COMMON_REPLACE_SCOPE if switching is not None else None,
                    )
                )
        elif preferring is not None:
            for item in targets:
                add(
                    _draft(
                        user,
                        item.mention,
                        "PREFERS",
                        excerpt=excerpt,
                        description=f"The user prefers {item.mention.name}.",
                        temporal_action="none",
                    )
                )

        # Study / work / location / goals / completion
        if _STUDY.search(sentence):
            for item in targets:
                if item.mention.entity_type in {"subject", "concept", "technology", "programming_language"}:
                    add(
                        _draft(
                            user,
                            item.mention,
                            "STUDIES",
                            excerpt=excerpt,
                            description=f"The user studies {item.mention.name}.",
                        )
                    )
        if _STUDY_AT.search(sentence) or _WORK_AT.search(sentence):
            for item in targets:
                if item.mention.entity_type in {"educational_institution", "organization"}:
                    add(
                        _draft(
                            user,
                            item.mention,
                            "BELONGS_TO",
                            excerpt=excerpt,
                            description=f"The user is associated with {item.mention.name}.",
                        )
                    )
        if _LIVE_IN.search(sentence):
            for item in targets:
                if item.mention.entity_type == "location":
                    add(
                        _draft(
                            user,
                            item.mention,
                            "LOCATED_IN",
                            excerpt=excerpt,
                            description=f"The user lives in {item.mention.name}.",
                        )
                    )
        if _GOAL.search(sentence):
            for item in targets:
                if item.mention.entity_type == "goal":
                    add(
                        _draft(
                            user,
                            item.mention,
                            "HAS_GOAL",
                            excerpt=excerpt,
                            description=f"The user's goal is to {item.mention.name}.",
                        )
                    )
        if _COMPLETED.search(sentence):
            for item in targets:
                add(
                    _draft(
                        user,
                        item.mention,
                        "COMPLETED",
                        excerpt=excerpt,
                        description=f"The user completed {item.mention.name}.",
                    )
                )

        # Explicit entity-to-entity relationships
        if _DEPENDS.search(sentence) and len(targets) >= 2:
            add(
                _draft(
                    targets[0].mention,
                    targets[1].mention,
                    "DEPENDS_ON",
                    excerpt=excerpt,
                    description=f"{targets[0].mention.name} depends on {targets[1].mention.name}.",
                )
            )
        if _RELATED.search(sentence) and len(targets) >= 2:
            add(
                _draft(
                    targets[0].mention,
                    targets[1].mention,
                    "RELATED_TO",
                    excerpt=excerpt,
                    description=f"{targets[0].mention.name} is related to {targets[1].mention.name}.",
                )
            )

    return drafts

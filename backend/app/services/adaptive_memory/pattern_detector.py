"""Conservative recurring-topic detection across distinct conversations."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.memory.safety import contains_sensitive_information
from app.models.adaptive import MemoryPattern
from app.models.conversation import Conversation
from app.models.message import Message

_VOCAB = {
    "mnemora": ("project", "mnemora"),
    "fastapi": ("programming", "fastapi"),
    "next.js": ("programming", "next.js"),
    "nextjs": ("programming", "next.js"),
    "react": ("programming", "react"),
    "python": ("programming", "python"),
    "java": ("programming", "java"),
    "javascript": ("programming", "javascript"),
    "typescript": ("programming", "typescript"),
    "sqlite": ("programming", "sqlite"),
    "postgres": ("programming", "postgres"),
    "chromadb": ("programming", "chromadb"),
    "chroma": ("programming", "chromadb"),
    "gemini": ("technology", "gemini"),
    "openai": ("technology", "openai"),
    "docker": ("deployment", "docker"),
    "kubernetes": ("deployment", "kubernetes"),
    "deployment": ("deployment", "deployment"),
    "debugging": ("workflow", "debugging"),
    "testing": ("workflow", "testing"),
    "planning": ("workflow", "planning"),
    "roadmap": ("goal", "roadmap"),
    "milestone": ("goal", "milestones"),
    "voice": ("interest", "voice input"),
    "image": ("interest", "image understanding"),
    "memory": ("interest", "memory"),
}

_TYPE_BY_GROUP = {
    "project": "repeated_project_activity",
    "programming": "repeated_learning_topic",
    "technology": "repeated_learning_topic",
    "deployment": "repeated_workflow",
    "workflow": "repeated_workflow",
    "goal": "recurring_goal",
    "interest": "recurring_interest",
}

_DESCRIPTION = {
    "repeated_project_activity": "Recurring activity: work involving {topic} across {conversations} conversations.",
    "repeated_learning_topic": "Repeated learning topic: {topic} appears across {conversations} conversations.",
    "repeated_workflow": "Repeated workflow: {topic} appears across {conversations} conversations.",
    "recurring_goal": "Recurring goal: {topic} appears across {conversations} conversations.",
    "recurring_interest": "Recurring interest: {topic} appears across {conversations} conversations.",
    "emerging_preference": "Emerging preference around {topic}.",
}

_CAPITALIZED = re.compile(r"\b[A-Z][A-Za-z0-9.+#-]{2,}\b")
_WORD = re.compile(r"[a-z0-9.+#-]{3,}")
_CAPITAL_STOP = {
    "the", "this", "that", "these", "those", "can", "could", "would", "should", "please",
    "explain", "help", "give", "show", "what", "why", "how", "when", "where", "which",
    "write", "create", "build", "make", "tell", "need", "want", "also", "and", "but",
    "for", "with", "from", "into", "about", "after", "before", "there", "here", "then",
    "mnemora", "i", "my", "we", "you", "it", "is", "are", "do", "does", "did",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _topics(text: str) -> list[tuple[str, str]]:
    """Return (pattern_type, topic) pairs using a small transparent vocabulary."""
    lowered = text.casefold()
    found: dict[str, tuple[str, str]] = {}
    for term, (group, normalized) in _VOCAB.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered):
            found[normalized] = (_TYPE_BY_GROUP[group], normalized)
    for word in _CAPITALIZED.findall(text):
        normalized = word.casefold().strip(".+#-")
        if len(normalized) < 3 or normalized in _CAPITAL_STOP:
            continue
        found.setdefault(normalized, ("recurring_interest", normalized))
    return list(found.values())[:4]


def detect_patterns(db: Session, user_id: UUID, *, evidence_threshold: int = 2) -> int:
    cutoff = _utcnow() - timedelta(days=180)
    rows = db.execute(
        select(Message, Conversation.conversation_id)
        .join(Conversation, Conversation.conversation_id == Message.conversation_id)
        .where(
            Conversation.user_id == user_id,
            Message.role == "user",
            Message.status == "completed",
            Message.created_at >= cutoff,
        )
        .order_by(Message.created_at.desc())
        .limit(settings.adaptive_max_pattern_messages)
    ).all()
    grouped: dict[tuple[str, str], list[tuple[Message, UUID]]] = defaultdict(list)
    for message, conversation_id in reversed(rows):
        if contains_sensitive_information(message.content) or len(message.content.split()) < 3:
            continue
        for pattern_type, topic in _topics(message.content):
            grouped[(pattern_type, topic)].append((message, conversation_id))

    created_or_updated = 0
    now = _utcnow()
    for (pattern_type, topic), observations in grouped.items():
        conversation_ids = list(dict.fromkeys(str(item[1]) for item in observations))
        if len(observations) < evidence_threshold or len(conversation_ids) < 2:
            continue
        pattern = db.scalar(select(MemoryPattern).where(
            MemoryPattern.user_id == user_id,
            MemoryPattern.pattern_type == pattern_type,
            MemoryPattern.normalized_key == topic,
        ))
        if pattern is not None and pattern.status == "dismissed":
            continue
        confidence = min(0.95, 0.35 + 0.12 * len(observations) + 0.05 * (len(conversation_ids) - 1))
        message_ids = list(dict.fromkeys(str(item[0].message_id) for item in observations))[-20:]
        first = observations[0][0].created_at
        last = observations[-1][0].created_at
        if pattern is None:
            pattern = MemoryPattern(
                user_id=user_id,
                pattern_type=pattern_type,
                description=_DESCRIPTION.get(pattern_type, "Recurring pattern: {topic}.").format(
                    topic=topic, conversations=len(conversation_ids)
                ),
                normalized_key=topic,
                evidence_count=len(observations),
                confidence=confidence,
                supporting_conversation_ids=conversation_ids[-20:],
                supporting_message_ids=message_ids,
                first_observed_at=first,
                last_observed_at=last,
                status="candidate",
            )
            db.add(pattern)
        else:
            pattern.evidence_count = len(observations)
            pattern.confidence = confidence
            pattern.description = _DESCRIPTION.get(pattern_type, "Recurring pattern: {topic}.").format(
                topic=topic, conversations=len(conversation_ids)
            )
            pattern.supporting_conversation_ids = conversation_ids[-20:]
            pattern.supporting_message_ids = message_ids
            pattern.last_observed_at = last
            if pattern.status != "confirmed":
                pattern.status = "candidate"
            pattern.updated_at = now
        created_or_updated += 1
    db.commit()
    return created_or_updated


def pattern_types() -> tuple[str, ...]:
    return tuple(_DESCRIPTION.keys())

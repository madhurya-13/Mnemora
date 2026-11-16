"""Deterministic, evidence-based preference learning from eligible conversation text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.safety import contains_sensitive_information
from app.models.adaptive import UserPreference
from app.models.memory import Memory

_STOP = {
    "the", "a", "an", "and", "or", "for", "with", "without", "this", "that", "these",
    "those", "please", "user", "prefer", "prefers", "like", "likes", "want", "wants",
    "give", "gives", "using", "use", "used", "make", "makes", "should", "would", "could",
}


@dataclass(frozen=True)
class PreferenceSignal:
    category: str
    key: str
    description: str
    polarity: str = "positive"


_RULES: tuple[tuple[re.Pattern[str], PreferenceSignal], ...] = (
    (re.compile(r"\b(step[-\s]?by[-\s]?step|simple steps?|clear steps?)\b", re.I), PreferenceSignal("learning_style", "step_by_step", "Prefers step-by-step explanations.")),
    (re.compile(r"\b(beginner[-\s]?friendly|simple (?:to understand|language)|plain language|explain (?:it )?simply)\b", re.I), PreferenceSignal("learning_style", "beginner_friendly", "Prefers beginner-friendly explanations.")),
    (re.compile(r"\b(practical (?:code )?examples?|examples? (?:with|and) code|code examples?|worked examples?|(?:with|using) (?:an? )?examples?)\b", re.I), PreferenceSignal("learning_style", "practical_examples", "Prefers practical examples alongside explanations.")),
    (re.compile(r"\b(concise|brief|to the point|short answers?|only (?:the )?necessary steps)\b", re.I), PreferenceSignal("communication_style", "concise", "Prefers concise answers with only the necessary steps.", "negative")),
    (re.compile(r"\b(detailed|in[-\s]?depth|thorough|comprehensive|long[-\s]?form)\b", re.I), PreferenceSignal("communication_style", "detailed", "Prefers detailed, thorough explanations.", "negative")),
    (re.compile(r"\bpython\b", re.I), PreferenceSignal("programming", "python", "Prefers Python examples and implementations.")),
    (re.compile(r"\bjava\b(?![-\s]?script)", re.I), PreferenceSignal("programming", "java", "Prefers Java examples and implementations.")),
    (re.compile(r"\b(minimal dependencies|fewer dependencies|no unnecessary (?:helper )?functions|avoid unnecessary (?:helper )?functions)\b", re.I), PreferenceSignal("programming", "minimal_dependencies", "Prefers minimal dependencies and no unnecessary helper functions.")),
    (re.compile(r"\b(milestone[-\s]?based|phased (?:plan|implementation)|milestone plan)\b", re.I), PreferenceSignal("project_workflow", "milestone_plans", "Prefers milestone-based project plans.")),
    (re.compile(r"\b(testing instructions?|verification guide|how to test|acceptance checklist)\b", re.I), PreferenceSignal("project_workflow", "testing_guidance", "Prefers testing and verification instructions with implementation work.")),
    (re.compile(r"\b(dark (?:navy|theme)|violet|electric blue|subtle gradients?)\b", re.I), PreferenceSignal("ui_ux", "dark_violet_theme", "Prefers a dark navy interface with violet and electric-blue accents.")),
    (re.compile(r"\b(ui|ux|interface|dashboard|responsive|accessib(?:le|ility))\b", re.I), PreferenceSignal("ui_ux", "interface_quality", "Prefers polished, responsive and accessible interfaces.")),
    (re.compile(r"\b(summar(?:y|ies)|bullet points?|key points)\b", re.I), PreferenceSignal("content", "summaries", "Prefers concise summaries with key points.")),
)

_CONTEXT_SCOPED = re.compile(
    r"\b(for this (?:project|task|answer|request|conversation)|this time|for now|right now|in this (?:answer|reply|response)|today only)\b",
    re.I,
)
_OPPOSITES = {
    "communication_style:concise": "communication_style:detailed",
    "communication_style:detailed": "communication_style:concise",
    "programming:python": "programming:java",
    "programming:java": "programming:python",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def extract_signals(text: str) -> list[PreferenceSignal]:
    if not text or contains_sensitive_information(text) or _CONTEXT_SCOPED.search(text):
        return []
    found: dict[str, PreferenceSignal] = {}
    for pattern, signal in _RULES:
        if pattern.search(text):
            found[signal.key] = signal
    # Keep only explicit preference-like statements or clearly repeated style cues.
    if not found:
        return []
    if not re.search(r"\b(prefer|like|want|please|use|give|explain|keep|avoid|help)\b", text, re.I):
        # A bare technology mention is not a preference by itself.
        style_keys = {"step_by_step", "beginner_friendly", "practical_examples", "concise", "detailed", "summaries"}
        if not any(key in style_keys for key in found):
            return []
    return list(found.values())


def _confidence(count: int) -> float:
    return min(0.95, 0.35 + 0.15 * max(0, count - 1))


def _supporting_memory_ids(db: Session, user_id: UUID, signal: PreferenceSignal) -> list[str]:
    category_map = {
        "learning_style": {"education", "preferences"},
        "communication_style": {"preferences"},
        "programming": {"preferences", "projects", "education"},
        "technology": {"preferences", "projects"},
        "project_workflow": {"preferences", "projects", "goals"},
        "ui_ux": {"preferences", "projects"},
        "content": {"preferences"},
    }
    categories = category_map.get(signal.category, {"preferences"})
    tokens = {token for token in re.findall(r"[a-z0-9+#.]{3,}", signal.description.casefold()) if token not in _STOP}
    rows = db.scalars(select(Memory).where(
        Memory.user_id == user_id,
        Memory.approval_status == "approved",
        Memory.category.in_(categories),
    ).order_by(Memory.updated_at.desc()).limit(25)).all()
    matched = []
    for memory in rows:
        content_tokens = set(re.findall(r"[a-z0-9+#.]{3,}", memory.content.casefold()))
        if tokens.intersection(content_tokens):
            matched.append(str(memory.memory_id))
    return matched[:10]


def _merge_evidence(existing: list[dict], item: dict) -> list[dict]:
    merged = list(existing or [])
    if not any(entry.get("message_id") == item.get("message_id") for entry in merged):
        merged.append(item)
    return merged[-20:]


def learn_from_message(
    db: Session,
    user_id: UUID,
    text: str,
    *,
    conversation_id: UUID | None,
    message_id: UUID | None,
    confidence_threshold: float,
    evidence_threshold: int,
    require_user_review: bool,
) -> int:
    """Aggregate signals into candidates. One message can never become a confirmed preference."""
    signals = extract_signals(text)
    if not signals:
        return 0
    now = _utcnow()
    updated = 0
    for signal in signals:
        normalized_key = f"{signal.category}:{signal.key}"
        preference = db.scalar(select(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.normalized_key == normalized_key,
        ))
        if preference is not None and preference.status in {"rejected", "disabled"}:
            continue
        if preference is None:
            preference = UserPreference(
                user_id=user_id,
                category=signal.category,
                description=signal.description,
                normalized_key=normalized_key,
                confidence=_confidence(1),
                evidence_count=1,
                supporting_memory_ids=[],
                evidence=[{
                    "message_id": str(message_id) if message_id else None,
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "excerpt": " ".join(text.split())[:180],
                    "observed_at": now.isoformat(),
                }],
                status="candidate",
                first_observed_at=now,
                last_observed_at=now,
            )
            db.add(preference)
        else:
            preference.evidence_count += 1
            preference.last_observed_at = now
            preference.evidence = _merge_evidence(preference.evidence, {
                "message_id": str(message_id) if message_id else None,
                "conversation_id": str(conversation_id) if conversation_id else None,
                "excerpt": " ".join(text.split())[:180],
                "observed_at": now.isoformat(),
            })
            preference.confidence = _confidence(preference.evidence_count)
            if preference.status == "confirmed":
                preference.status = "confirmed"
            elif preference.evidence_count >= evidence_threshold and preference.confidence >= confidence_threshold and not require_user_review:
                preference.status = "confirmed"
        preference.supporting_memory_ids = _supporting_memory_ids(db, user_id, signal)

        opposite = _OPPOSITES.get(normalized_key)
        if opposite:
            contradictory = db.scalar(select(UserPreference).where(
                UserPreference.user_id == user_id,
                UserPreference.normalized_key == opposite,
                UserPreference.status.in_(("candidate", "confirmed")),
            ))
            if contradictory is not None:
                # Re-evaluate rather than silently replacing either preference.
                contradictory.confidence = max(0.2, round(contradictory.confidence - 0.10, 4))
                contradictory.status = "candidate"
                contradictory.updated_at = now
        updated += 1
    db.commit()
    return updated


def evidence_summary(preference: UserPreference) -> str:
    return f"{preference.evidence_count} observation(s); confidence {round(preference.confidence * 100)}%"


def relevant_terms(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9+#.]{3,}", text.casefold()) if token not in _STOP}


def signals_for(texts: Iterable[str]) -> list[PreferenceSignal]:
    found: dict[str, PreferenceSignal] = {}
    for text in texts:
        for signal in extract_signals(text):
            found[signal.key] = signal
    return list(found.values())

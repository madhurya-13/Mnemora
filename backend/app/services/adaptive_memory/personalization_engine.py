"""Relevance-filtered, token-limited personalization context for the existing chat pipeline."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.adaptive import UserPreference
from app.retrieval import query_analyzer
from app.services.adaptive_memory.adaptive_settings import get_adaptive_settings
from app.services.adaptive_memory.preference_learner import relevant_terms

_QUERY_HINTS = {
    "learning_style": {"explain", "learn", "teach", "understand", "tutorial", "guide", "concept", "how", "why"},
    "communication_style": {"explain", "answer", "summary", "summarize", "describe", "help", "write", "plan"},
    "programming": {"code", "python", "java", "function", "error", "debug", "implement", "framework", "api"},
    "technology": {"stack", "technology", "framework", "tool", "build", "project", "deploy"},
    "project_workflow": {"project", "milestone", "plan", "roadmap", "implement", "build", "test", "verify"},
    "ui_ux": {"ui", "ux", "design", "interface", "frontend", "dashboard", "responsive", "theme"},
    "content": {"write", "summarize", "summary", "rewrite", "draft", "content", "email"},
    "other": set(),
}


def _applicable(category: str, query_tokens: set[str]) -> bool:
    return bool(_QUERY_HINTS.get(category, set()).intersection(query_tokens))


def _relevance(preference: UserPreference, query_tokens: set[str], category_applicable: bool) -> float:
    description_tokens = relevant_terms(preference.description)
    overlap = len(description_tokens.intersection(query_tokens)) / max(1, len(description_tokens))
    score = 0.45 * overlap + 0.25 * (1.0 if category_applicable else 0.0) + 0.20 * preference.confidence
    score += 0.10 if preference.evidence_count >= 3 else 0.0
    return score


def select_preferences(db: Session, user_id: UUID, query: str) -> list[UserPreference]:
    row = get_adaptive_settings(db, user_id)
    if not row.personalization_enabled:
        return []
    analysis = query_analyzer.analyze_query(query)
    if analysis.intent == "general_knowledge":
        return []
    query_tokens = relevant_terms(query)
    preferences = db.scalars(select(UserPreference).where(
        UserPreference.user_id == user_id,
        UserPreference.status == "confirmed",
    )).all()
    scored = []
    for preference in preferences:
        applicable = _applicable(preference.category, query_tokens)
        description_tokens = relevant_terms(preference.description)
        overlap = len(description_tokens.intersection(query_tokens)) / max(1, len(description_tokens))
        # A preference must be topically relevant either by category or by content overlap.
        if not applicable and overlap == 0.0:
            continue
        score = _relevance(preference, query_tokens, applicable)
        if score >= 0.25:
            scored.append((score, preference))
    scored.sort(key=lambda item: (item[0], item[1].confidence), reverse=True)
    return [preference for _, preference in scored[: settings.adaptive_max_preferences_in_context]]


def build_personalization_context(db: Session, user_id: UUID, query: str) -> str | None:
    preferences = select_preferences(db, user_id, query)
    if not preferences:
        return None
    lines = [
        "RELEVANT USER PREFERENCES (user-approved; apply only when they help with this request):"
    ]
    for preference in preferences:
        category = preference.category.replace("_", " ").title()
        lines.append(f"- [{category}] {preference.description}")
    lines.append(
        "Follow the user's current explicit instructions if they conflict with these preferences. "
        "Do not mention this list unless it is directly useful, and do not personalize unrelated general knowledge."
    )
    return "\n".join(lines)


def personalization_ids(db: Session, user_id: UUID, query: str) -> list[str]:
    return [str(preference.preference_id) for preference in select_preferences(db, user_id, query)]

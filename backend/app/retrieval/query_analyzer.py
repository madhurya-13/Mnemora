"""Deterministic query understanding with a validated, conservative fallback."""

from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.memory import QueryAnalysisResponse

_GENERAL = re.compile(r"\b(capital of|who wrote|when did|define|what is the meaning of|how many planets|chemical symbol)\b", re.I)
_PERSONAL = re.compile(r"\b(my|me|i |i'm|i am|for me|about me|myself|the user|user's|user is|what do you know|what did i tell)\b", re.I)
_HISTORICAL = re.compile(r"\b(what did i tell|what did i say|remember when|what was i|what have i|earlier|previously|last time)\b", re.I)
_FOLLOW_UP = re.compile(r"\b(that|those|it|they|another one|more like|what about|and then)\b", re.I)
_STOP = {"the", "a", "an", "is", "are", "was", "were", "to", "of", "for", "me", "my", "i", "you", "what", "which", "how", "can", "could", "would", "should", "and", "or", "in", "on", "about", "do", "does", "did", "user"}


def _keywords(query: str) -> list[str]:
    return list(dict.fromkeys(word.lower() for word in re.findall(r"[a-zA-Z0-9+#.]{2,}", query) if word.lower() not in _STOP))[:12]


def _categories(query: str) -> list[str]:
    text = query.casefold()
    rules = {
        "education": ("study", "student", "course", "class", "school", "college", "university", "degree", "exam"),
        "career": ("career", "job", "portfolio", "resume", "work", "profession", "interview"),
        "interests": ("interest", "enjoy", "hobby", "like", "curious", "passion"),
        "preferences": ("prefer", "preference", "style", "favorite", "favourite", "likes"),
        "projects": ("project", "build", "building", "develop", "prototype", "app", "portfolio"),
        "goals": ("goal", "plan", "aim", "aspire", "want to", "objective"),
        "personal": ("about me", "my name", "my family", "personal", "where do i"),
        "temporary": ("deadline", "due date", "this week", "tomorrow", "upcoming"),
    }
    return [category for category, terms in rules.items() if any(term in text for term in terms)]


def _build(query: str, *, conservative: bool) -> QueryAnalysisResponse:
    text = query.strip()
    lowered = text.casefold()
    categories = _categories(text)
    historical = bool(_HISTORICAL.search(text))
    follow_up = bool(_FOLLOW_UP.search(text)) and len(_keywords(text)) <= 7
    recommendation = any(term in lowered for term in ("recommend", "suggest", "idea", "brainstorm", "what should", "for my"))
    planning = any(term in lowered for term in ("plan", "schedule", "roadmap", "next step"))
    personal = bool(_PERSONAL.search(text)) or bool(categories) or recommendation or historical
    if historical:
        intent, query_type, requires = "historical_conversation", "historical", True
    elif bool(_GENERAL.search(text)) and not personal:
        intent, query_type, requires = "general_knowledge", "factual", False
    elif recommendation:
        intent, query_type, requires = "personalized_recommendation", "recommendation", True
    elif planning:
        intent, query_type, requires = "personalized_planning", "planning", personal
    elif follow_up:
        intent, query_type, requires = "follow_up", "follow_up", conservative and personal
    elif categories or personal:
        intent, query_type, requires = "personal_information", "personal", True
    elif any(term in lowered for term in ("code", "debug", "error", "implement", "technical")):
        intent, query_type, requires = "technical_assistance", "general", conservative
    else:
        intent, query_type, requires = "general_question", "general", conservative
    return QueryAnalysisResponse(
        intent=intent, categories=categories, requires_personalization=personal,
        requires_memory=requires, query_type=query_type, keywords=_keywords(text),
        confidence=0.92 if categories or not conservative else 0.55,
    )


def fallback_analysis(query: str) -> QueryAnalysisResponse:
    """Prefer safe existing retrieval for ambiguous queries, except clear facts."""
    return _build(query, conservative=True)


def parse_analysis(raw: Any, query: str) -> QueryAnalysisResponse:
    """Validate structured output; malformed output uses the deterministic fallback."""
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return QueryAnalysisResponse.model_validate(value)
    except Exception:
        return fallback_analysis(query)


def analyze_query(query: str) -> QueryAnalysisResponse:
    """Classify without an LLM call; this stage is deterministic and inexpensive."""
    try:
        return _build(query, conservative=False)
    except Exception:
        return fallback_analysis(query)

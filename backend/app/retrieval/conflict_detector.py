"""Conservative conflict and redundancy cues; uncertain pairs go to user review."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ConflictAssessment:
    conflict_type: str
    summary: str


def _preference_value(text: str) -> str | None:
    match = re.search(r"\b(prefers?|preference is|likes?|enjoys?)\s+(.+?)[.!?]*$", text, re.I)
    return re.sub(r"[^a-z0-9+# ]", " ", match.group(2).casefold()).strip() if match else None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]{2,}", text.casefold())) - {"user", "the", "and", "with", "for", "from", "that"}


def detect_conflict(existing, new_content: str, new_category: str, *, semantic_similarity: float | None = None) -> ConflictAssessment | None:
    if existing.category != new_category:
        return None
    if new_category == "preferences":
        old_value, new_value = _preference_value(existing.content), _preference_value(new_content)
        if old_value and new_value and old_value != new_value:
            updated = bool(re.search(r"\b(now|instead|no longer|changed|used to|currently)\b", new_content, re.I))
            kind = "updated_information" if updated else "direct_contradiction"
            return ConflictAssessment(kind, "These preference memories may describe a change; review which should be active.")
    old, new = _tokens(existing.content), _tokens(new_content)
    union = old | new
    overlap = len(old & new) / len(union) if union else 0
    if semantic_similarity is not None and semantic_similarity >= 0.92:
        return ConflictAssessment("possible_duplicate", "These memories are semantically very similar and may be redundant.")
    if overlap >= 0.78:
        return ConflictAssessment("possible_duplicate", "These memories share substantial wording and may be redundant.")
    return None

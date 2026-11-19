"""Bounded, classified failure recovery. Irreversible actions are never retried blindly."""

from __future__ import annotations

from app.config import settings

TRANSIENT = "transient"
PERMANENT = "permanent"
TIMEOUT = "timeout"
RATE_LIMIT = "rate_limit"
NOT_CONFIGURED = "not_configured"
UNKNOWN = "unknown"

_RETRYABLE = {TRANSIENT, TIMEOUT, RATE_LIMIT, UNKNOWN}


def classify(error: str | None, error_kind: str | None = None) -> str:
    if error_kind in {TRANSIENT, PERMANENT, TIMEOUT, RATE_LIMIT, NOT_CONFIGURED}:
        return error_kind or UNKNOWN
    text = (error or "").casefold()
    if "timeout" in text or "timed out" in text:
        return TIMEOUT
    if "rate limit" in text or "429" in text:
        return RATE_LIMIT
    if "not configured" in text or "unavailable" in text:
        return NOT_CONFIGURED
    if "invalid" in text or "not allowed" in text or "rejected" in text or "permission" in text:
        return PERMANENT
    return UNKNOWN


def should_retry(
    classification: str,
    *,
    attempt: int,
    max_attempts: int,
    side_effects: bool,
) -> bool:
    """Only transient-class failures on side-effect-free tools are retried."""
    if attempt >= max_attempts:
        return False
    if side_effects:
        return False
    return classification in _RETRYABLE and classification != NOT_CONFIGURED


def backoff_seconds(attempt: int) -> float:
    base = max(0.0, settings.agent_retry_backoff_seconds)
    return min(base * (2 ** max(0, attempt - 1)), 5.0)


def fallback_input(tool_name: str, arguments: dict) -> dict | None:
    """Translate arguments to a compatible read-only fallback, or None."""
    if tool_name == "knowledge_graph_search":
        return {"query": str(arguments.get("query", ""))[:500], "limit": 6}
    return None


def describe_failure(tool_name: str, classification: str, attempts: int) -> str:
    labels = {
        TRANSIENT: "a temporary tool failure",
        TIMEOUT: "a tool timeout",
        RATE_LIMIT: "a provider rate limit",
        PERMANENT: "a permanent tool error",
        NOT_CONFIGURED: "missing tool configuration",
        UNKNOWN: "an unclassified tool error",
    }
    return (
        f"{tool_name} failed after {attempts} attempt(s) due to {labels.get(classification, 'an error')}. "
        "The failure was recorded and no output was invented."
    )

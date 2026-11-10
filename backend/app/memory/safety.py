"""Local guardrails for sensitive or credential-like memory candidates."""

import re

_SENSITIVE_PATTERNS = (
    re.compile(r"\b(password|passphrase|passcode|api[\s_-]*key|secret key|access token|refresh token|bearer token)\b", re.I),
    re.compile(r"\b(ssn|social security number|credit card|debit card|bank account|routing number|passport number)\b", re.I),
    re.compile(r"\b(diagnosed with|medical condition|prescribed medication|taking medication for|therapy for)\b", re.I),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{30,})\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
)


def contains_sensitive_information(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS)

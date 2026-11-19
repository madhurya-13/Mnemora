"""Read-only memory and preference tools backed by the Milestone 4-7 store."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.agents.agent_safety import sanitize_untrusted_text
from app.agents.agent_schemas import ToolContext, ToolResult
from app.agents.tools.registry import registry
from app.agents.tools.base_tool import ToolSpec
from app.config import settings
from app.models.adaptive import UserPreference
from app.models.memory import Memory

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "my",
    "i", "me", "is", "are", "was", "were", "what", "which", "how", "about",
}


def _tokens(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9+#.]{2,}", (text or "").casefold())
        if word not in _STOP
    }


def _memory_payload(memory: Memory) -> dict:
    return {
        "memory_id": str(memory.memory_id),
        "content": sanitize_untrusted_text(memory.content, limit=600),
        "category": memory.category,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "lifecycle_status": memory.lifecycle_status,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "source": memory.source,
    }


class MemorySearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=6, ge=1, le=20)


class PreferenceLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class MemoryAuditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=5, le=200)
    similarity_threshold: float = Field(default=0.86, ge=0.5, le=1.0)


def memory_search(context: ToolContext, payload: MemorySearchInput) -> ToolResult:
    query_tokens = _tokens(payload.query)
    statement = select(Memory).where(
        Memory.user_id == context.user_id,
        Memory.approval_status == "approved",
        Memory.lifecycle_status.notin_(("archived", "expired", "superseded")),
    )
    if payload.category:
        statement = statement.where(Memory.category == payload.category)
    statement = statement.order_by(Memory.updated_at.desc()).limit(200)
    rows = list(context.db.scalars(statement).all())

    scored: list[tuple[float, Memory]] = []
    for row in rows:
        overlap = len(query_tokens & _tokens(row.content))
        score = overlap * 2.0 + row.importance + row.confidence
        if overlap or not query_tokens:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], str(item[1].memory_id)))
    selected = scored[: payload.limit]
    items = [_memory_payload(row) for _, row in selected]
    return ToolResult(
        ok=True,
        summary=(
            f"Found {len(items)} approved memory item(s) for '{payload.query[:80]}' "
            f"from {len(rows)} approved candidate(s)."
        ),
        data={
            "items": items,
            "query": payload.query,
            "candidate_count": len(rows),
            "selected_count": len(items),
        },
        evidence=[item["memory_id"] for item in items],
    )


def preference_lookup(context: ToolContext, payload: PreferenceLookupInput) -> ToolResult:
    rows = list(
        context.db.scalars(
            select(UserPreference)
            .where(
                UserPreference.user_id == context.user_id,
                UserPreference.status == "confirmed",
            )
            .order_by(UserPreference.confidence.desc(), UserPreference.updated_at.desc())
            .limit(50)
        ).all()
    )
    query_tokens = _tokens(payload.query or "")
    items = []
    for row in rows:
        overlap = len(query_tokens & _tokens(f"{row.category} {row.description}"))
        if query_tokens and overlap == 0:
            continue
        items.append(
            {
                "preference_id": str(row.preference_id),
                "category": row.category,
                "description": sanitize_untrusted_text(row.description, limit=300),
                "confidence": row.confidence,
                "evidence_count": row.evidence_count,
                "status": row.status,
            }
        )
        if len(items) >= payload.limit:
            break
    return ToolResult(
        ok=True,
        summary=(
            f"Matched {len(items)} confirmed preference(s)."
            if items
            else "No confirmed preferences matched this objective."
        ),
        data={"items": items, "confirmed_total": len(rows)},
        evidence=[item["preference_id"] for item in items],
    )


def memory_audit(context: ToolContext, payload: MemoryAuditInput) -> ToolResult:
    rows = list(
        context.db.scalars(
            select(Memory)
            .where(Memory.user_id == context.user_id, Memory.approval_status == "approved")
            .order_by(Memory.updated_at.desc())
            .limit(payload.limit)
        ).all()
    )
    outdated = [
        _memory_payload(row)
        for row in rows
        if row.lifecycle_status in {"possibly_outdated", "expired", "superseded", "archived"}
    ]
    duplicates: list[dict] = []
    normalized = [
        (row, " ".join(re.findall(r"[a-z0-9]+", row.content.casefold()))) for row in rows
    ]
    for index, (row, text) in enumerate(normalized):
        for other, other_text in normalized[index + 1 :]:
            if row.category != other.category:
                continue
            if abs(len(text) - len(other_text)) > max(len(text), len(other_text)):
                continue
            similarity = SequenceMatcher(None, text, other_text).ratio()
            if similarity >= payload.similarity_threshold:
                duplicates.append(
                    {
                        "memory_id": str(row.memory_id),
                        "duplicate_of": str(other.memory_id),
                        "similarity": round(similarity, 3),
                        "category": row.category,
                        "preview": sanitize_untrusted_text(row.content, limit=160),
                    }
                )
    return ToolResult(
        ok=True,
        summary=(
            f"Audited {len(rows)} approved memories: {len(duplicates)} possible duplicate pair(s), "
            f"{len(outdated)} outdated or inactive record(s)."
        ),
        data={
            "audited_count": len(rows),
            "duplicates": duplicates[:20],
            "outdated": outdated[:20],
            "note": "Duplicate pairs are suggestions only; nothing was merged or modified.",
        },
        evidence=[str(row.memory_id) for row in rows[:20]],
    )


registry.register(
    ToolSpec(
        name="memory_search",
        description="Search the user's approved long-term memories with deterministic keyword ranking.",
        category="memory",
        permission="read_only",
        input_model=MemorySearchInput,
        handler=memory_search,
        output_schema={"type": "object", "properties": {"items": {"type": "array"}}},
    )
)
registry.register(
    ToolSpec(
        name="preference_lookup",
        description="Read confirmed user preferences produced by Milestone 7 adaptive learning.",
        category="memory",
        permission="read_only",
        input_model=PreferenceLookupInput,
        handler=preference_lookup,
    )
)
registry.register(
    ToolSpec(
        name="memory_audit",
        description="Audit approved memories for possible duplicates and outdated lifecycle states without changing them.",
        category="memory",
        permission="read_only",
        input_model=MemoryAuditInput,
        handler=memory_audit,
    )
)

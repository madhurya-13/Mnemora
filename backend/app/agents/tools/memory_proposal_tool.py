"""Sensitive tool: propose a memory candidate that still requires user approval."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.agents.agent_safety import sanitize_untrusted_text
from app.agents.agent_schemas import ToolContext, ToolResult
from app.agents.tools.base_tool import ToolSpec
from app.agents.tools.registry import registry
from app.memory.safety import contains_sensitive_information
from app.models.memory import Memory
from app.schemas.memory import MemoryCategory

_CATEGORIES = (
    "personal", "education", "career", "interests", "preferences", "projects", "goals", "temporary", "other",
)


class MemoryProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=5, max_length=500)
    category: MemoryCategory = "projects"
    importance: float = Field(default=0.6, ge=0, le=1)
    confidence: float = Field(default=0.6, ge=0, le=1)

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Memory proposal content cannot be blank.")
        return cleaned


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def memory_proposal(context: ToolContext, payload: MemoryProposalInput) -> ToolResult:
    content = sanitize_untrusted_text(payload.content, limit=500)
    if contains_sensitive_information(content):
        return ToolResult(
            ok=False,
            summary="The proposed memory was rejected because it contains sensitive information.",
            error="sensitive_content",
            error_kind="permanent",
        )
    for row in context.db.scalars(
        select(Memory).where(
            Memory.user_id == context.user_id,
            Memory.approval_status.in_(("pending", "approved")),
        )
    ).all():
        if _norm(row.content) == _norm(content):
            return ToolResult(
                ok=True,
                summary="An equivalent memory already exists; no duplicate was created.",
                data={
                    "memory_id": str(row.memory_id),
                    "approval_status": row.approval_status,
                    "created": False,
                },
                evidence=[str(row.memory_id)],
            )

    memory = Memory(
        user_id=context.user_id,
        content=content,
        category=payload.category if payload.category in _CATEGORIES else "other",
        importance=payload.importance,
        confidence=payload.confidence,
        memory_type="stable",
        source="agent",
        source_message_ids=[],
        approval_status="pending",
        vector_sync_status="not_required",
        lifecycle_status="active",
    )
    context.db.add(memory)
    context.db.commit()
    context.db.refresh(memory)
    return ToolResult(
        ok=True,
        summary="Created a pending memory candidate. It is not retrievable until you approve it.",
        data={
            "memory_id": str(memory.memory_id),
            "approval_status": memory.approval_status,
            "category": memory.category,
            "created": True,
            "note": "Approval happens on the Memory page; this tool never auto-approves.",
        },
        evidence=[str(memory.memory_id)],
    )


registry.register(
    ToolSpec(
        name="memory_proposal",
        description="Create one pending memory candidate for explicit user approval. Never auto-approves.",
        category="memory",
        permission="sensitive",
        input_model=MemoryProposalInput,
        handler=memory_proposal,
        side_effects=True,
    )
)

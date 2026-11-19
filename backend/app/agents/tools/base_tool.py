"""Tool contract: allowlisted tools with schemas, permissions and retry policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from app.agents.agent_schemas import (
    PERMISSIONS,
    PERMISSION_READ_ONLY,
    ToolContext,
    ToolResult,
)
from app.config import settings


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Static, auditable description of one allowlisted capability."""

    name: str
    description: str
    category: str
    permission: str
    input_model: type[BaseModel]
    handler: Callable[[ToolContext, BaseModel], ToolResult]
    side_effects: bool = False
    timeout_seconds: float = 0.0
    max_attempts: int = 0
    fallback: str | None = None
    enabled_check: Callable[[], bool] | None = None
    disabled_reason: str | None = None
    reversible: bool = True
    output_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.permission not in PERMISSIONS:
            raise ValueError(f"Unknown tool permission: {self.permission}")

    @property
    def timeout(self) -> float:
        return self.timeout_seconds or settings.agent_tool_timeout_seconds

    @property
    def attempts(self) -> int:
        return self.max_attempts or (settings.agent_max_tool_retries + 1)

    def enabled(self) -> bool:
        return bool(self.enabled_check()) if self.enabled_check else True

    @property
    def requires_approval(self) -> bool:
        if self.permission == "sensitive":
            return True
        if self.permission == "reversible":
            return not settings.agent_auto_approve_reversible
        return False

    def describe(self) -> dict[str, Any]:
        enabled = self.enabled()
        return {
            "tool_name": self.name,
            "description": self.description,
            "category": self.category,
            "permission": self.permission,
            "side_effects": self.side_effects,
            "approval_required": self.requires_approval,
            "enabled": enabled,
            "disabled_reason": None if enabled else (self.disabled_reason or "Not configured."),
            "timeout_seconds": self.timeout,
            "max_attempts": self.attempts,
            "fallback": self.fallback,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_schema or {"type": "object"},
        }


READ_ONLY = PERMISSION_READ_ONLY

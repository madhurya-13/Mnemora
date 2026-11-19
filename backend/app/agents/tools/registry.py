"""Central allowlist of agent tools; there is no dynamic or free-form invocation."""

from __future__ import annotations

from app.agents.agent_schemas import ToolNotAllowedError
from app.agents.tools.base_tool import ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"Duplicate tool registration: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def require(self, name: str, *, allow_disabled: bool = False) -> ToolSpec:
        spec = self.get(name)
        if spec is None:
            raise ToolNotAllowedError(f"Tool '{name}' is not registered.")
        if not allow_disabled and not spec.enabled():
            raise ToolNotAllowedError(
                f"Tool '{name}' is not configured: {spec.disabled_reason or 'unavailable'}."
            )
        return spec

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[ToolSpec]:
        return [self._tools[name] for name in self.names()]

    def enabled(self) -> list[ToolSpec]:
        return [spec for spec in self.all() if spec.enabled()]

    def describe(self) -> list[dict]:
        return [spec.describe() for spec in self.all()]

    def selectable_for(self, task_type: str) -> list[str]:
        from app.agents.tool_selector import TOOL_BY_TASK_TYPE

        name = TOOL_BY_TASK_TYPE.get(task_type)
        spec = self.get(name) if name else None
        return [name] if spec is not None else []


registry = ToolRegistry()

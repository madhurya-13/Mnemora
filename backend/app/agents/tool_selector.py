"""Deterministic task-type to tool mapping with schema validation and permission gates."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.agent_schemas import AgentValidationError, ToolNotAllowedError
from app.agents.tools.base_tool import ToolSpec
from app.agents.tools.registry import registry

TOOL_BY_TASK_TYPE: dict[str, str] = {
    "retrieve_memory": "memory_search",
    "retrieve_preferences": "preference_lookup",
    "retrieve_graph": "knowledge_graph_search",
    "analyze_project": "project_analysis",
    "analyze_document": "document_analysis",
    "analyze_memories": "memory_audit",
    "research": "web_research",
    "calculate": "calculator",
    "generate_report": "report_generation",
    "propose_memory": "memory_proposal",
}


def tool_for_task(task_type: str) -> str:
    try:
        return TOOL_BY_TASK_TYPE[task_type]
    except KeyError as error:
        raise ToolNotAllowedError(f"Task type '{task_type}' has no allowlisted tool.") from error


def select_tool(task_type: str) -> ToolSpec:
    """Return the single allowlisted tool for a task type.

    Selection is a fixed mapping, never a model choice, and a disabled tool is
    rejected rather than silently substituted.
    """
    name = tool_for_task(task_type)
    spec = registry.get(name)
    if spec is None:
        raise ToolNotAllowedError(f"Tool '{name}' is not registered.")
    if not spec.enabled():
        raise ToolNotAllowedError(
            f"Tool '{name}' is unavailable: {spec.disabled_reason or 'not configured'}."
        )
    return spec


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> BaseModel:
    try:
        return spec.input_model.model_validate(arguments or {})
    except ValidationError as error:
        first = error.errors()[0] if error.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ())) or "input"
        message = first.get("msg", "invalid arguments")
        raise AgentValidationError(f"{spec.name}: {location} — {message}") from error


def missing_required_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> list[str]:
    """Presence check used when a plan is edited.

    Types are validated again immediately before execution, so a malformed value
    still fails closed at run time. Editing only rejects a task that is obviously
    incomplete.
    """
    missing: list[str] = []
    for name, field in spec.input_model.model_fields.items():
        if field.is_required() and (name not in arguments or arguments[name] is None):
            missing.append(name)
    return missing


def prepare(task_type: str, arguments: dict[str, Any]) -> tuple[ToolSpec, BaseModel]:
    spec = select_tool(task_type)
    return spec, validate_arguments(spec, arguments)

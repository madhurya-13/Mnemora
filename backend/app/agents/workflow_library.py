"""Reusable workflow templates built only from registered, validated tools."""

from __future__ import annotations

import copy
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import agent_orchestrator
from app.agents import execution_state as state
from app.agents.agent_schemas import (
    AgentConflictError,
    AgentNotFoundError,
    AgentValidationError,
    PlannedPlan,
    PlannedTask,
)
from app.agents.tool_selector import TOOL_BY_TASK_TYPE
from app.agents.tools.registry import registry
from app.agents.monitoring import task_monitor
from app.config import settings
from app.models.agent import AgentExecution, WorkflowTemplate

_BUILTIN_WORKFLOWS: tuple[dict, ...] = (
    {
        "key": "project_audit",
        "name": "Project Audit Workflow",
        "description": (
            "Inspect the repository through allowlisted files, identify genuinely missing "
            "components and produce a prioritised completion roadmap."
        ),
        "objective_template": "Audit my project and prepare a completion roadmap.",
        "intent": "project_audit",
        "steps": [
            {
                "title": "Retrieve project memories",
                "description": "Read approved memories relevant to the project.",
                "task_type": "retrieve_memory",
                "expected_output": "Approved project memories with identifiers.",
                "input": {"query": "__objective__", "limit": 6},
                "dependencies": [],
            },
            {
                "title": "Retrieve knowledge-graph context",
                "description": "Traverse evidence-backed relationships connected to the project.",
                "task_type": "retrieve_graph",
                "expected_output": "Matched entities and supported graph paths.",
                "input": {"query": "__objective__", "max_depth": 2},
                "dependencies": [],
            },
            {
                "title": "Inspect repository architecture",
                "description": "Describe the current architecture from allowlisted repository evidence.",
                "task_type": "analyze_project",
                "expected_output": "Architecture findings with file evidence.",
                "input": {"mode": "architecture"},
                "dependencies": [0, 1],
            },
            {
                "title": "Identify missing implementation components",
                "description": "Report which expected assets are actually absent.",
                "task_type": "analyze_project",
                "expected_output": "Observed gaps separated from recommendations.",
                "input": {"mode": "missing_components"},
                "dependencies": [0, 1],
            },
            {
                "title": "Generate completion roadmap",
                "description": "Rank next steps grounded in the collected evidence.",
                "task_type": "generate_report",
                "expected_output": "A draft roadmap with evidence and limitations.",
                "input": {"title": "Completion roadmap", "include_limitations": True},
                "dependencies": [0, 1, 2, 3],
            },
        ],
    },
    {
        "key": "learning_plan",
        "name": "Learning Plan Workflow",
        "description": (
            "Use confirmed preferences and stored learning context to produce a staged study "
            "plan without inventing a skill level."
        ),
        "objective_template": "Create a learning plan based on my current skills and preferences.",
        "intent": "learning",
        "steps": [
            {
                "title": "Retrieve learning memories",
                "description": "Read approved memories about education, goals and interests.",
                "task_type": "retrieve_memory",
                "expected_output": "Relevant approved learning memories.",
                "input": {"query": "__objective__", "limit": 6},
                "dependencies": [],
            },
            {
                "title": "Retrieve confirmed preferences",
                "description": "Read confirmed preferences from adaptive learning.",
                "task_type": "retrieve_preferences",
                "expected_output": "Confirmed preferences with confidence values.",
                "input": {"query": "__objective__", "limit": 5},
                "dependencies": [],
            },
            {
                "title": "Generate structured study plan",
                "description": "Build a staged plan and state assumptions instead of inventing facts.",
                "task_type": "generate_report",
                "expected_output": "A staged study plan with evidence and assumptions.",
                "input": {"title": "Structured study plan", "include_limitations": True},
                "dependencies": [0, 1],
            },
        ],
    },
    {
        "key": "research",
        "name": "Research Workflow",
        "description": (
            "Collect sources from the configured search provider, keep every URL and produce "
            "a cited report that separates evidence from conclusions."
        ),
        "objective_template": "Research a topic and produce a cited summary.",
        "intent": "research",
        "steps": [
            {
                "title": "Retrieve related memories",
                "description": "Read approved memories related to the research question.",
                "task_type": "retrieve_memory",
                "expected_output": "Relevant approved memories.",
                "input": {"query": "__objective__", "limit": 6},
                "dependencies": [],
            },
            {
                "title": "Collect external sources",
                "description": "Query the configured provider and retain source URLs.",
                "task_type": "research",
                "expected_output": "Source titles, URLs and snippets.",
                "input": {"query": "__objective__", "max_results": 4},
                "dependencies": [],
            },
            {
                "title": "Generate cited report",
                "description": "Report only evidence-backed findings and keep citations.",
                "task_type": "generate_report",
                "expected_output": "A cited draft report with limitations.",
                "input": {"title": "Cited research report", "include_limitations": True},
                "dependencies": [0, 1],
            },
        ],
    },
    {
        "key": "memory_review",
        "name": "Memory Review Workflow",
        "description": (
            "Audit approved memories for duplicates and outdated lifecycle states, then present "
            "corrections for review without changing any memory automatically."
        ),
        "objective_template": "Review my memories for duplicates and outdated information.",
        "intent": "memory_review",
        "steps": [
            {
                "title": "Audit approved memories",
                "description": "Find possible duplicate pairs and outdated records.",
                "task_type": "analyze_memories",
                "expected_output": "Duplicate suggestions and outdated records.",
                "input": {"limit": 60, "similarity_threshold": 0.86},
                "dependencies": [],
            },
            {
                "title": "Retrieve confirmed preferences",
                "description": "Include confirmed preferences as review context.",
                "task_type": "retrieve_preferences",
                "expected_output": "Confirmed preferences with confidence values.",
                "input": {"query": "__objective__", "limit": 5},
                "dependencies": [],
            },
            {
                "title": "Present proposed corrections",
                "description": "Describe corrections for the user to apply manually.",
                "task_type": "generate_report",
                "expected_output": "A review report with proposed corrections.",
                "input": {"title": "Memory review report", "include_limitations": True},
                "dependencies": [0, 1],
            },
        ],
    },
)

_BUILTIN_BY_NAME = {item["name"]: item for item in _BUILTIN_WORKFLOWS}


def _available_tools(steps: list[dict]) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for step in steps:
        tool_name = TOOL_BY_TASK_TYPE.get(str(step.get("task_type", "")))
        spec = registry.get(tool_name) if tool_name else None
        if spec is None or not spec.enabled():
            missing.append(tool_name or str(step.get("task_type", "unknown")))
    return (not missing, sorted(set(missing)))


def ensure_builtins(db: Session, user_id: UUID) -> None:
    """Seed the builtin library once per user without overwriting user edits."""
    existing = {
        row.name
        for row in db.scalars(
            select(WorkflowTemplate).where(WorkflowTemplate.user_id == user_id)
        ).all()
    }
    created = False
    for definition in _BUILTIN_WORKFLOWS:
        if definition["name"] in existing:
            continue
        db.add(
            WorkflowTemplate(
                user_id=user_id,
                name=definition["name"],
                description=definition["description"],
                objective_template=definition["objective_template"],
                intent=definition["intent"],
                steps=copy.deepcopy(definition["steps"]),
                status="active",
                source="builtin",
            )
        )
        created = True
    if created:
        db.commit()


def _validate_steps(steps: list[dict]) -> list[dict]:
    if not steps:
        raise AgentValidationError("A workflow needs at least one step.")
    if len(steps) > settings.agent_max_tasks_per_plan:
        raise AgentValidationError(
            f"A workflow can contain at most {settings.agent_max_tasks_per_plan} steps."
        )
    prepared: list[dict] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise AgentValidationError("Each workflow step must be an object.")
        task_type = str(step.get("task_type", "")).strip()
        tool_name = TOOL_BY_TASK_TYPE.get(task_type)
        if tool_name is None:
            raise AgentValidationError(f"Step {index + 1}: '{task_type}' has no allowlisted tool.")
        spec = registry.require(tool_name)
        payload = copy.deepcopy(step.get("input") or {})
        if not isinstance(payload, dict):
            raise AgentValidationError(f"Step {index + 1}: input must be an object.")
        try:
            spec.input_model.model_validate(
                _materialize_payload(task_type, payload, "workflow objective")
            )
        except ValidationError as error:
            first = error.errors()[0] if error.errors() else {}
            location = ".".join(str(part) for part in first.get("loc", ())) or "input"
            raise AgentValidationError(
                f"Step {index + 1} ({tool_name}): {location} — "
                f"{first.get('msg', 'invalid parameters')}"
            ) from error
        dependencies = step.get("dependencies") or []
        if not isinstance(dependencies, list):
            raise AgentValidationError(f"Step {index + 1}: dependencies must be a list.")
        for dependency in dependencies:
            if not isinstance(dependency, int) or not 0 <= dependency < index:
                raise AgentValidationError(
                    f"Step {index + 1}: dependencies must reference earlier steps."
                )
        prepared.append(
            {
                "title": str(step.get("title", "")).strip()[:200] or f"Step {index + 1}",
                "description": str(step.get("description", "")).strip()[:1000],
                "task_type": task_type,
                "assigned_tool": tool_name,
                "expected_output": str(step.get("expected_output", "")).strip()[:500],
                "input": payload,
                "dependencies": sorted({int(value) for value in dependencies}),
            }
        )
    return prepared


def _materialize_payload(task_type: str, payload: dict, objective: str) -> dict:
    materialized: dict = {}
    for key, value in payload.items():
        if value == "__objective__":
            materialized[key] = objective[:500]
        else:
            materialized[key] = copy.deepcopy(value)
    if task_type in {"retrieve_memory", "retrieve_graph", "retrieve_preferences"} and not materialized.get(
        "query"
    ):
        materialized["query"] = objective[:500]
    if task_type in {"research"} and not materialized.get("query"):
        materialized["query"] = objective[:300]
    if task_type == "propose_memory" and not materialized.get("content"):
        materialized["content"] = objective[:500]
    if task_type == "analyze_document" and not materialized.get("question"):
        materialized["question"] = objective[:300]
    if task_type == "generate_report":
        title = str(materialized.get("title") or "").strip()
        materialized["title"] = (title or f"Report: {objective[:120]}")[:160]
    return materialized


def get_workflow(db: Session, user_id: UUID, workflow_id: UUID) -> WorkflowTemplate:
    ensure_builtins(db, user_id)
    template = db.get(WorkflowTemplate, workflow_id)
    if template is None or template.user_id != user_id:
        raise AgentNotFoundError("Workflow not found.")
    return template


def list_workflows(
    db: Session, user_id: UUID, *, status_filter: str | None = None
) -> list[dict]:
    ensure_builtins(db, user_id)
    statement = select(WorkflowTemplate).where(WorkflowTemplate.user_id == user_id)
    if status_filter:
        statement = statement.where(WorkflowTemplate.status == status_filter)
    templates = list(
        db.scalars(statement.order_by(WorkflowTemplate.updated_at.desc())).all()
    )
    items = []
    for template in templates:
        last_execution = db.scalar(
            select(AgentExecution)
            .where(
                AgentExecution.user_id == user_id,
                AgentExecution.workflow_id == template.workflow_id,
            )
            .order_by(AgentExecution.created_at.desc())
        )
        available, missing = _available_tools(list(template.steps or []))
        payload = task_monitor.workflow_payload(template, last_execution=last_execution)
        payload["available"] = available
        payload["missing_tools"] = missing
        payload["editable"] = template.source != "builtin"
        items.append(payload)
    return items


def create_workflow(
    db: Session,
    user_id: UUID,
    *,
    name: str,
    description: str,
    objective_template: str,
    intent: str,
    steps: list[dict],
    status: str = "active",
) -> WorkflowTemplate:
    ensure_builtins(db, user_id)
    name = " ".join(name.split())[:120]
    if not name:
        raise AgentValidationError("A workflow needs a name.")
    existing = db.scalar(
        select(WorkflowTemplate).where(
            WorkflowTemplate.user_id == user_id, WorkflowTemplate.name == name
        )
    )
    if existing is not None:
        raise AgentConflictError("A workflow with that name already exists.")
    prepared = _validate_steps(steps)
    template = WorkflowTemplate(
        user_id=user_id,
        name=name,
        description=description[:500],
        objective_template=(objective_template or name)[:2000],
        intent=(intent or "generic")[:40],
        steps=prepared,
        status=status if status in {"suggested", "active", "archived"} else "active",
        source="user",
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_workflow(
    db: Session,
    user_id: UUID,
    workflow_id: UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    objective_template: str | None = None,
    intent: str | None = None,
    steps: list[dict] | None = None,
    status: str | None = None,
) -> WorkflowTemplate:
    template = get_workflow(db, user_id, workflow_id)
    if name is not None and name.strip() and name.strip() != template.name:
        clash = db.scalar(
            select(WorkflowTemplate).where(
                WorkflowTemplate.user_id == user_id,
                WorkflowTemplate.name == name.strip()[:120],
                WorkflowTemplate.workflow_id != template.workflow_id,
            )
        )
        if clash is not None:
            raise AgentConflictError("Another workflow already uses that name.")
        template.name = name.strip()[:120]
    if description is not None:
        template.description = description[:500]
    if objective_template is not None:
        template.objective_template = objective_template[:2000]
    if intent is not None:
        template.intent = intent[:40]
    if steps is not None:
        template.steps = _validate_steps(steps)
    if status is not None:
        if status not in {"suggested", "active", "archived"}:
            raise AgentValidationError("Workflow status must be suggested, active or archived.")
        template.status = status
    template.updated_at = state.utcnow()
    db.commit()
    db.refresh(template)
    return template


def duplicate_workflow(
    db: Session, user_id: UUID, workflow_id: UUID, *, name: str | None = None
) -> WorkflowTemplate:
    source = get_workflow(db, user_id, workflow_id)
    base = (name or f"{source.name} (copy)")[:120]
    candidate = base
    counter = 2
    while db.scalar(
        select(WorkflowTemplate).where(
            WorkflowTemplate.user_id == user_id, WorkflowTemplate.name == candidate
        )
    ) is not None:
        suffix = f" {counter}"
        candidate = base[: 120 - len(suffix)] + suffix
        counter += 1
        if counter > 50:
            raise AgentConflictError("Could not find a free workflow name.")
    template = WorkflowTemplate(
        user_id=user_id,
        name=candidate,
        description=source.description,
        objective_template=source.objective_template,
        intent=source.intent,
        steps=copy.deepcopy(source.steps),
        status="active",
        source="user",
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def delete_workflow(db: Session, user_id: UUID, workflow_id: UUID) -> None:
    template = get_workflow(db, user_id, workflow_id)
    if template.source == "builtin":
        raise AgentConflictError("Builtin workflows cannot be deleted; archive them instead.")
    db.delete(template)
    db.commit()


def execute_workflow(
    db: Session,
    user_id: UUID,
    workflow_id: UUID,
    *,
    objective: str | None = None,
) -> AgentExecution:
    template = get_workflow(db, user_id, workflow_id)
    if template.status == "archived":
        raise AgentConflictError("This workflow is archived; restore it before executing.")
    available, missing = _available_tools(list(template.steps or []))
    if not available:
        raise AgentConflictError(
            "This workflow needs unconfigured tool(s): " + ", ".join(missing)
        )
    goal = " ".join((objective or template.objective_template or template.name).split())
    planned_tasks: list[PlannedTask] = []
    for step in template.steps or []:
        task_type = str(step.get("task_type", ""))
        tool_name = TOOL_BY_TASK_TYPE.get(task_type)
        if tool_name is None:
            raise AgentConflictError(
                f"Workflow step '{step.get('title', '')}' no longer maps to an allowlisted tool."
            )
        spec = registry.require(tool_name, allow_disabled=True)
        payload = _materialize_payload(task_type, dict(step.get("input") or {}), goal)
        planned_tasks.append(
            PlannedTask(
                title=str(step.get("title", "Step"))[:200],
                description=str(step.get("description", ""))[:1000],
                task_type=task_type,
                assigned_tool=tool_name,
                expected_output=str(step.get("expected_output", ""))[:500],
                input=payload,
                dependencies=[int(value) for value in step.get("dependencies", [])],
                approval_required=spec.requires_approval,
            )
        )
    planned = PlannedPlan(
        title=f"{template.name}: {goal[:90]}"[:190],
        objective=goal,
        description=(
            f"Reusable workflow '{template.name}' with {len(planned_tasks)} validated step(s). "
            "Sensitive steps still require per-action approval."
        ),
        intent=template.intent,
        priority="normal",
        estimated_complexity=(
            "low" if len(planned_tasks) <= 2 else ("moderate" if len(planned_tasks) <= 5 else "high")
        ),
        tasks=planned_tasks,
        clarifications=[],
        warnings=[f"Tool '{name}' is not configured and will fail if reached." for name in missing],
        context_summary={
            "workflow_id": str(template.workflow_id),
            "workflow_name": template.name,
            "retrieval_summary": "Reusable workflow; no plan-time memory retrieval was performed.",
        },
    )
    plan = agent_orchestrator._persist_plan(
        db, user_id, planned, workflow_id=template.workflow_id, source="workflow"
    )
    plan.status = state.PLAN_APPROVED
    if template.status == "suggested":
        template.status = "active"
    db.commit()
    return agent_orchestrator.start_execution(db, user_id, plan.plan_id)

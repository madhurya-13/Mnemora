"""Memory-aware context assembly and verified-outcome learning.

Context is read from the existing records only: approved memories, confirmed
preferences, evidence-backed graph paths, prior executions and saved workflows.
Learning is conservative: it proposes a workflow template for confirmation and,
at most, one pending memory candidate that the user must approve.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.agent_schemas import AgentContext
from app.agents.execution_state import PLAN_COMPLETED, PLAN_PARTIALLY_COMPLETED
from app.config import settings
from app.models.adaptive import UserPreference
from app.models.agent import AgentExecution, AgentPlan, AgentTask, WorkflowTemplate
from app.models.memory import Memory
from app.memory.safety import contains_sensitive_information

logger = logging.getLogger(__name__)

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "my",
    "me", "i", "is", "are", "was", "were", "what", "which", "how", "about", "help",
    "create", "make", "prepare", "please", "current", "my", "project", "plan",
}

_INTENT_CATEGORIES: dict[str, set[str]] = {
    "learning": {"education", "interests", "goals", "preferences", "skills"},
    "project_audit": {"projects", "goals", "preferences"},
    "deployment": {"projects", "goals"},
    "research": {"interests", "education", "projects"},
    "memory_review": {"personal", "education", "career", "interests", "preferences", "projects", "goals", "other"},
    "generic": {"projects", "goals", "preferences"},
}


def _tokens(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9+#.]{2,}", (text or "").casefold())
        if word not in _STOP
    }


def _memory_row(row: Memory) -> dict:
    return {
        "memory_id": str(row.memory_id),
        "content": row.content,
        "category": row.category,
        "importance": row.importance,
        "confidence": row.confidence,
        "lifecycle_status": row.lifecycle_status,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "source": row.source,
    }


def build_context(db: Session, user_id: UUID, objective: str, intent: str = "generic") -> AgentContext:
    """Assemble bounded, relevance-filtered context with source references."""
    context = AgentContext()
    tokens = _tokens(objective)
    categories = _INTENT_CATEGORIES.get(intent, _INTENT_CATEGORIES["generic"])

    rows = list(
        db.scalars(
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.approval_status == "approved",
                Memory.lifecycle_status.in_(("active", "possibly_outdated")),
            )
            .order_by(Memory.updated_at.desc())
            .limit(300)
        ).all()
    )
    scored: list[tuple[float, Memory]] = []
    for row in rows:
        overlap = len(tokens & _tokens(row.content))
        category_match = row.category in categories
        if overlap or (category_match and len(tokens) <= 2):
            score = overlap * 2 + (1.0 if category_match else 0) + row.importance
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], str(item[1].memory_id)))
    context.memories = [_memory_row(row) for _, row in scored[: settings.agent_context_max_memories]]
    context.projects = sorted(
        {
            item["content"][:120]
            for item in context.memories
            if item["category"] == "projects"
        }
    )[:6]

    preferences = list(
        db.scalars(
            select(UserPreference)
            .where(UserPreference.user_id == user_id, UserPreference.status == "confirmed")
            .order_by(UserPreference.confidence.desc())
            .limit(40)
        ).all()
    )
    selected_preferences = []
    for preference in preferences:
        label = f"{preference.category} {preference.description}"
        if tokens & _tokens(label) or len(tokens) <= 2:
            selected_preferences.append(
                {
                    "preference_id": str(preference.preference_id),
                    "category": preference.category,
                    "description": preference.description,
                    "confidence": preference.confidence,
                }
            )
        if len(selected_preferences) >= 5:
            break
    context.preferences = selected_preferences

    if settings.knowledge_graph_enabled:
        try:
            from app.knowledge_graph import graph_engine

            result = graph_engine.search(
                db, user_id, objective, max_depth=min(2, settings.graph_max_depth)
            )
            context.graph_entities = [
                {
                    "entity_id": node.get("id"),
                    "label": node.get("label"),
                    "entity_type": node.get("entity_type"),
                    "status": node.get("status"),
                }
                for node in (result.get("matched_entities") or [])[: settings.agent_context_max_graph_facts]
            ]
            context.graph_paths = [
                " → ".join(path.get("labels", []))
                for path in (result.get("paths") or [])[: settings.agent_context_max_graph_facts]
            ]
            context.projects = sorted(
                set(context.projects)
                | {
                    str(node.get("label"))
                    for node in (result.get("nodes") or [])
                    if node.get("entity_type") == "project" and node.get("status") == "active"
                }
            )[:8]
        except Exception as error:  # graph context is optional, never fatal
            logger.warning("Agent graph context skipped (%s).", type(error).__name__)
            context.warnings.append("Knowledge-graph context was unavailable for this plan.")

    executions = list(
        db.scalars(
            select(AgentExecution)
            .where(AgentExecution.user_id == user_id)
            .order_by(AgentExecution.created_at.desc())
            .limit(20)
        ).all()
    )
    prior = []
    for execution in executions:
        plan = db.get(AgentPlan, execution.plan_id)
        if plan is None:
            continue
        prior.append(
            {
                "execution_id": str(execution.execution_id),
                "plan_title": plan.title,
                "status": execution.status,
                "progress": execution.progress,
                "created_at": execution.created_at.isoformat() if execution.created_at else None,
            }
        )
        if len(prior) >= 5:
            break
    context.prior_executions = prior

    context.workflows = [
        {"workflow_id": str(row.workflow_id), "name": row.name, "status": row.status}
        for row in db.scalars(
            select(WorkflowTemplate)
            .where(
                WorkflowTemplate.user_id == user_id,
                WorkflowTemplate.status.in_(("active", "suggested")),
            )
            .order_by(WorkflowTemplate.updated_at.desc())
            .limit(10)
        ).all()
    ]
    return context


def _recent_signatures(db: Session, user_id: UUID, intent: str, tools: list[str]) -> int:
    """Count prior executions with the same verified tool sequence."""
    count = 0
    executions = db.scalars(
        select(AgentExecution)
        .where(
            AgentExecution.user_id == user_id,
            AgentExecution.status.in_(("completed", "partially_completed")),
        )
        .order_by(AgentExecution.created_at.desc())
        .limit(50)
    ).all()
    for execution in executions:
        plan = db.get(AgentPlan, execution.plan_id)
        if plan is None or plan.intent != intent:
            continue
        tasks = db.scalars(
            select(AgentTask)
            .where(AgentTask.plan_id == plan.plan_id, AgentTask.status == "completed")
            .order_by(AgentTask.sequence)
        ).all()
        if [task.assigned_tool for task in tasks] == tools:
            count += 1
    return count


def learn_from_execution(db: Session, user_id: UUID, execution: AgentExecution) -> dict:
    """Record verified outcomes and propose a reusable workflow; never auto-enable it."""
    if not settings.agent_learning_enabled:
        return {"enabled": False, "reason": "AGENT learning is disabled."}
    plan = db.get(AgentPlan, execution.plan_id)
    if plan is None or plan.user_id != user_id:
        return {"enabled": False, "reason": "Plan not found."}
    if execution.status not in {"completed", "partially_completed"}:
        return {
            "enabled": True,
            "learned": False,
            "reason": "Execution did not complete successfully.",
            "workflow_suggestion": None,
            "memory_proposal": None,
        }

    tasks = list(
        db.scalars(
            select(AgentTask)
            .where(AgentTask.plan_id == plan.plan_id)
            .order_by(AgentTask.sequence)
        ).all()
    )
    verified = [
        task
        for task in tasks
        if task.status == "completed" and task.verification_status in {"verified", "partially_verified"}
    ]
    if not verified:
        return {
            "enabled": True,
            "learned": False,
            "reason": "No verified task outcome to learn from.",
            "workflow_suggestion": None,
            "memory_proposal": None,
        }

    tools = [task.assigned_tool or task.task_type for task in verified]
    usage = {
        tool: sum(1 for task in verified if (task.assigned_tool or task.task_type) == tool)
        for tool in sorted(set(tools))
    }
    learning: dict = {
        "enabled": True,
        "learned": True,
        "verified_tasks": len(verified),
        "tool_usage": usage,
        "workflow_suggestion": None,
        "memory_proposal": None,
        "note": "Only completed, verified tasks contributed to learning.",
    }

    threshold = settings.agent_pattern_threshold
    repeats = _recent_signatures(db, user_id, plan.intent, tools)
    if repeats >= threshold:
        name = f"{plan.title[:96]} (learned)"[:120]
        existing = db.scalar(
            select(WorkflowTemplate).where(
                WorkflowTemplate.user_id == user_id, WorkflowTemplate.name == name
            )
        )
        if existing is None:
            steps = [
                {
                    "title": task.title,
                    "description": task.description,
                    "task_type": task.task_type,
                    "assigned_tool": task.assigned_tool,
                    "expected_output": task.expected_output,
                }
                for task in verified
            ]
            template = WorkflowTemplate(
                user_id=user_id,
                name=name,
                description=(
                    f"Suggested from {repeats + 1} similar verified execution(s) of the "
                    f"'{plan.intent}' intent."
                )[:500],
                objective_template=plan.objective[:2000],
                intent=plan.intent,
                steps=steps,
                status="suggested",
                source="learned",
            )
            db.add(template)
            db.commit()
            learning["workflow_suggestion"] = {
                "workflow_id": str(template.workflow_id),
                "name": template.name,
                "status": template.status,
                "requires_confirmation": True,
            }

    already_captured = any(
        task.assigned_tool == "memory_proposal" and task.status == "completed" for task in tasks
    )
    if (
        execution.status == PLAN_COMPLETED
        and plan.status in {PLAN_COMPLETED, PLAN_PARTIALLY_COMPLETED}
        and not already_captured
    ):
        content = (
            f"Agent workflow '{plan.title[:120]}' completed {len(verified)} verified task(s) "
            f"using {', '.join(sorted(usage))}."
        )
        if not contains_sensitive_information(content):
            normalized = re.sub(r"[^a-z0-9]+", " ", content.casefold()).strip()
            duplicate = next(
                (
                    row
                    for row in db.scalars(
                        select(Memory).where(
                            Memory.user_id == user_id,
                            Memory.approval_status.in_(("pending", "approved")),
                        )
                    ).all()
                    if re.sub(r"[^a-z0-9]+", " ", row.content.casefold()).strip() == normalized
                ),
                None,
            )
            if duplicate is None:
                memory = Memory(
                    user_id=user_id,
                    content=content[:500],
                    category="projects",
                    importance=0.55,
                    confidence=0.6,
                    memory_type="stable",
                    source="agent",
                    source_message_ids=[],
                    approval_status="pending",
                    vector_sync_status="not_required",
                    lifecycle_status="active",
                )
                db.add(memory)
                db.commit()
                db.refresh(memory)
                learning["memory_proposal"] = {
                    "memory_id": str(memory.memory_id),
                    "approval_status": memory.approval_status,
                    "requires_approval": True,
                }
            else:
                learning["memory_proposal"] = {
                    "memory_id": str(duplicate.memory_id),
                    "approval_status": duplicate.approval_status,
                    "requires_approval": duplicate.approval_status != "approved",
                    "existing": True,
                }

    execution.learning = learning
    db.commit()
    return learning

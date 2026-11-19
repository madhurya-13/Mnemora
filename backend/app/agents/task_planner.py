"""Deterministic objective analysis and plan construction.

The planner is rule-based and provider-free. It never invents entities, completed
work or durations, and it only proposes tasks whose tools are registered and
enabled. Missing essential information is returned as clarification questions.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.agent_schemas import AgentContext, PlannedPlan, PlannedTask
from app.agents.tool_selector import TOOL_BY_TASK_TYPE
from app.agents.tools.registry import registry
from app.config import settings

_INTENTS = (
    "deployment",
    "learning",
    "research",
    "memory_review",
    "memory_capture",
    "project_audit",
    "calculation",
    "generic",
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "my",
    "me", "i", "is", "are", "was", "were", "what", "which", "how", "help", "please",
    "current", "project", "plan", "create", "make", "prepare", "identify", "based",
    "using", "about", "from", "that", "this", "should", "would", "could", "can",
}

_DEPLOYMENT_WORDS = ("deploy", "deployment", "release", "production", "ship", "render", "vercel")
_LEARNING_WORDS = ("learn", "learning", "study", "skill", "course", "tutorial", "practice", "curriculum")
_RESEARCH_WORDS = ("research", "compare sources", "look up", "find information", "investigate", "sources")
_MEMORY_CAPTURE_WORDS = ("remember this", "save this", "store this", "propose a memory", "memorise", "memorize")
_MEMORY_REVIEW_WORDS = ("memory review", "review my memories", "duplicate memories", "outdated memories", "audit my memories")
_AUDIT_WORDS = ("analyze", "analyse", "audit", "roadmap", "missing", "inspect", "completion", "review my project", "improvement")


def detect_intent(objective: str) -> str:
    text = " ".join((objective or "").casefold().split())
    if any(word in text for word in _MEMORY_CAPTURE_WORDS):
        return "memory_capture"
    if any(word in text for word in _MEMORY_REVIEW_WORDS):
        return "memory_review"
    if any(word in text for word in _DEPLOYMENT_WORDS):
        return "deployment"
    if any(re.search(rf"\b{re.escape(word)}\b", text) for word in _LEARNING_WORDS):
        return "learning"
    if any(word in text for word in _RESEARCH_WORDS):
        return "research"
    if any(word in text for word in _AUDIT_WORDS):
        return "project_audit"
    if re.search(r"\d\s*[-+*/%]\s*\d|\bcalculate\b|\bhow many days\b|\bdays between\b", text):
        return "calculation"
    return "generic"


def _content_tokens(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9+#.]{3,}", (text or "").casefold())
        if word not in _STOPWORDS
    }


def _project_in_objective(objective: str, projects: list[str]) -> str | None:
    lowered = objective.casefold()
    for project in projects:
        cleaned = re.sub(r"\s+", " ", project).strip()
        if cleaned and cleaned.casefold() in lowered:
            return cleaned[:120]
    return None


def _title_for(objective: str, intent: str, project: str | None) -> str:
    pretty = {
        "deployment": "Deployment readiness",
        "learning": "Learning plan",
        "research": "Research plan",
        "memory_review": "Memory review",
        "memory_capture": "Memory capture",
        "project_audit": "Project audit",
        "calculation": "Calculation",
        "generic": "Task plan",
    }[intent]
    subject = project or " ".join(objective.split())[:70]
    return f"{pretty}: {subject}"[:190]


def _tool_available(task_type: str) -> bool:
    name = TOOL_BY_TASK_TYPE.get(task_type)
    spec = registry.get(name) if name else None
    return spec is not None and spec.enabled()


def _task(
    title: str,
    description: str,
    task_type: str,
    expected_output: str,
    *,
    payload: dict[str, Any] | None = None,
    dependencies: list[int] | None = None,
) -> PlannedTask:
    tool = TOOL_BY_TASK_TYPE[task_type]
    spec = registry.get(tool)
    return PlannedTask(
        title=title[:200],
        description=description[:1000],
        task_type=task_type,
        assigned_tool=tool,
        expected_output=expected_output[:500],
        input=payload or {},
        dependencies=dependencies or [],
        approval_required=bool(spec and spec.requires_approval),
    )


def _clarification(question_id: str, question: str, options: list[str] | None = None) -> dict:
    return {"id": question_id, "question": question, "options": options or []}


def _resolve_project(objective: str, context: AgentContext) -> tuple[str | None, list[dict]]:
    clarifications: list[dict] = []
    named = _project_in_objective(objective, context.projects)
    if named:
        return named, clarifications
    mentions_my_project = re.search(r"\bmy\b[\w\s-]{0,20}\b(project|app|application|repo)\b", objective, re.I)
    if not mentions_my_project:
        return None, clarifications
    if len(context.projects) == 1:
        return context.projects[0], clarifications
    if len(context.projects) > 1:
        clarifications.append(
            _clarification(
                "project_scope",
                "Which project should this plan target?",
                context.projects[:6],
            )
        )
    else:
        clarifications.append(
            _clarification(
                "project_scope",
                "I could not find a project in your approved memories. Which project should this plan target?",
            )
        )
    return None, clarifications


def _retrieval_tasks(objective: str, project: str | None, context: AgentContext) -> list[PlannedTask]:
    query = project or objective
    tasks = [
        _task(
            "Retrieve relevant approved memories",
            "Search approved long-term memories and confirmed project context for this objective.",
            "retrieve_memory",
            "A ranked list of approved memory items with identifiers.",
            payload={"query": query[:500], "limit": 6},
        )
    ]
    if _tool_available("retrieve_preferences"):
        tasks.append(
            _task(
                "Retrieve confirmed preferences",
                "Read confirmed preferences from adaptive learning that could affect this plan.",
                "retrieve_preferences",
                "Confirmed preferences with confidence values, or an explicit empty result.",
                payload={"query": objective[:500], "limit": 5},
            )
        )
    if _tool_available("retrieve_graph") and settings.knowledge_graph_enabled:
        tasks.append(
            _task(
                "Retrieve knowledge-graph context",
                "Traverse active, evidence-backed graph relationships relevant to the objective.",
                "retrieve_graph",
                "Matched entities and evidence-supported graph paths.",
                payload={"query": objective[:500], "max_depth": 2},
            )
        )
    return tasks


def _document_task(documents: list[dict], question: str) -> PlannedTask:
    return _task(
        "Analyse supplied documents",
        "Summarise the explicitly supplied documents as untrusted evidence and compare shared terms.",
        "analyze_document",
        "Extractive summaries, keywords and a warning if instruction-like text is present.",
        payload={"documents": documents, "question": question[:300]},
    )


def _report_task(title: str, description: str, dependencies: list[int]) -> PlannedTask:
    return _task(
        title,
        description,
        "generate_report",
        "A structured draft report containing objective, evidence, findings, recommendations and limitations.",
        payload={"title": title[:160], "include_limitations": True},
        dependencies=dependencies,
    )


def build_plan(
    objective: str,
    context: AgentContext,
    documents: list[dict] | None = None,
) -> PlannedPlan:
    objective = " ".join((objective or "").split())
    intent = detect_intent(objective)
    documents = documents or []
    clarifications: list[dict] = []
    warnings: list[str] = list(context.warnings)
    project, project_clarifications = _resolve_project(objective, context)
    clarifications.extend(project_clarifications)

    if len(objective) < 12 or not _content_tokens(objective):
        clarifications.append(
            _clarification(
                "objective_detail",
                "What concrete outcome should this plan produce?",
            )
        )

    tasks: list[PlannedTask] = []

    if intent == "learning":
        has_baseline = bool(context.preferences) or any(
            item["category"] in {"education", "interests", "goals"} for item in context.memories
        )
        if not has_baseline and re.search(r"current skills|my skills|skill level", objective, re.I):
            clarifications.append(
                _clarification(
                    "skill_baseline",
                    "No confirmed skills or preferences were found. Which skills should the plan assume?",
                )
            )
        tasks.extend(_retrieval_tasks(objective, project, context))
        tasks.append(
            _report_task(
                "Generate structured study plan",
                "Build a staged learning plan from retrieved context, stating assumptions instead of inventing a skill level.",
                list(range(len(tasks))),
            )
        )

    elif intent == "deployment":
        tasks.extend(_retrieval_tasks(objective, project, context))
        inspection_modes = [
            ("architecture", "Inspect existing project architecture"),
            ("deployment", "Identify deployment requirements"),
            ("environment", "Check environment configuration"),
            ("database", "Identify database requirements"),
            ("frontend", "Review frontend build configuration"),
        ]
        if _tool_available("analyze_project"):
            base = list(range(len(tasks)))
            for mode, title in inspection_modes:
                tasks.append(
                    _task(
                        title,
                        "Read only allowlisted repository files and report observed facts separately from recommendations.",
                        "analyze_project",
                        "Observed findings with evidence paths plus separate recommendations.",
                        payload={"mode": mode, "project_name": project},
                        dependencies=base,
                    )
                )
        else:
            warnings.append(
                "Repository inspection is disabled (AGENT_PROJECT_ROOT). The plan uses memory and graph evidence only."
            )
        tasks.append(
            _report_task(
                "Prepare deployment instructions and readiness checklist",
                "Summarise observed configuration evidence and separate recommendations from verified facts.",
                list(range(len(tasks))),
            )
        )

    elif intent == "project_audit":
        tasks.extend(_retrieval_tasks(objective, project, context))
        base = list(range(len(tasks)))
        if _tool_available("analyze_project"):
            tasks.append(
                _task(
                    "Inspect repository architecture",
                    "Read allowlisted manifests and directory names to describe the current architecture.",
                    "analyze_project",
                    "Architecture findings with file evidence.",
                    payload={"mode": "architecture", "project_name": project},
                    dependencies=base,
                )
            )
            tasks.append(
                _task(
                    "Identify missing implementation components",
                    "Check for optional and required project assets and report only what is actually absent.",
                    "analyze_project",
                    "Separate observed findings and recommendations.",
                    payload={"mode": "missing_components", "project_name": project},
                    dependencies=base,
                )
            )
        else:
            warnings.append(
                "Repository inspection is disabled (AGENT_PROJECT_ROOT). Missing-component detection uses stored context only."
            )
        report_dependencies = [index for index, task in enumerate(tasks) if task.task_type != "generate_report"]
        tasks.append(
            _report_task(
                "Generate prioritised completion roadmap",
                "Rank concrete next steps that are grounded in the retrieved memory, graph and repository evidence.",
                report_dependencies,
            )
        )

    elif intent == "research":
        tasks.extend(_retrieval_tasks(objective, project, context))
        if _tool_available("research"):
            tasks.append(
                _task(
                    "Collect external sources",
                    "Query the configured search provider and retain source URLs.",
                    "research",
                    "Source titles, URLs and snippets from the configured provider.",
                    payload={"query": objective[:300], "max_results": 4},
                )
            )
        elif documents:
            tasks.append(_document_task(documents, objective))
        else:
            clarifications.append(
                _clarification(
                    "research_source",
                    "External search is not configured. Paste source text as documents or configure "
                    "AGENT_WEB_SEARCH_PROVIDER and AGENT_WEB_SEARCH_API_KEY.",
                )
            )
        if documents and _tool_available("analyze_document") and not any(
            task.task_type == "analyze_document" for task in tasks
        ):
            tasks.append(_document_task(documents, objective))
        tasks.append(
            _report_task(
                "Generate cited research report",
                "Distinguish evidence-backed findings from unsupported conclusions and keep source references.",
                list(range(len(tasks))),
            )
        )

    elif intent == "memory_review":
        tasks.append(
            _task(
                "Audit approved memories",
                "Identify possible duplicates, outdated lifecycle states and records that may need correction.",
                "analyze_memories",
                "Suggested duplicate pairs and outdated records; no automatic changes.",
                payload={"limit": 60, "similarity_threshold": 0.86},
            )
        )
        tasks.extend(_retrieval_tasks(objective, project, context))
        tasks.append(
            _report_task(
                "Present proposed memory corrections",
                "Describe proposed corrections for user review. No memory is modified by this plan.",
                list(range(len(tasks))),
            )
        )

    elif intent == "memory_capture":
        tasks.append(
            _task(
                "Retrieve related memories",
                "Check whether an equivalent memory already exists before proposing a new one.",
                "retrieve_memory",
                "Approved memories related to this capture request.",
                payload={"query": project or objective[:500], "limit": 6},
            )
        )
        tasks.append(
            _task(
                "Propose a memory for approval",
                "Create one pending memory candidate from the user's own statement. The tool cannot approve it.",
                "propose_memory",
                "A pending memory identifier that is not retrievable until approved.",
                payload={
                    "content": objective[:500],
                    "category": "projects" if project else "other",
                    "importance": 0.6,
                    "confidence": 0.6,
                },
                dependencies=[0],
            )
        )

    else:
        tasks.extend(_retrieval_tasks(objective, project, context))
        if documents and _tool_available("analyze_document"):
            tasks.append(_document_task(documents, objective))
        if re.search(r"\d\s*[-+*/%]\s*\d|\bcalculate\b", objective):
            expression = re.search(r"\d[\d\s()+\-*/%.]*", objective)
            tasks.append(
                _task(
                    "Evaluate the arithmetic request",
                    "Evaluate a bounded arithmetic expression without executing code.",
                    "calculate",
                    "A numeric result that can be checked.",
                    payload={
                        "expression": (
                            expression.group(0).strip() if expression else "0"
                        )[:200]
                    },
                )
            )
        tasks.append(
            _report_task(
                "Summarise the outcome",
                "Summarise verified task results and clearly state any missing evidence.",
                list(range(len(tasks))),
            )
        )

    if not tasks:
        tasks.append(
            _task(
                "Retrieve relevant memories",
                "Search approved memories for context relevant to the objective.",
                "retrieve_memory",
                "A ranked list of approved memory items.",
                payload={"query": objective[:500], "limit": 6},
            )
        )

    tasks = tasks[: settings.agent_max_tasks_per_plan]
    for task in tasks:
        if task.assigned_tool not in registry.names():
            warnings.append(f"Tool '{task.assigned_tool}' is not registered; the plan cannot run as-is.")

    priority = "normal"
    if re.search(r"\burgent\b|\basap\b|\bimmediately\b", objective, re.I):
        priority = "urgent"
    elif re.search(r"\bimportant\b|\bdeadline\b|\bhigh priority\b", objective, re.I):
        priority = "high"
    complexity = "low" if len(tasks) <= 2 else ("moderate" if len(tasks) <= 5 else "high")

    description = (
        f"{len(tasks)} task(s) planned for the '{intent}' intent. Context: {context.retrieval_summary()}. "
        "Every step uses a registered tool; sensitive steps require explicit approval."
    )
    return PlannedPlan(
        title=_title_for(objective, intent, project),
        objective=objective,
        description=description,
        intent=intent,
        priority=priority,
        estimated_complexity=complexity,
        tasks=tasks,
        clarifications=clarifications,
        warnings=warnings,
        context_summary={
            "memory_ids": context.evidence_ids()[:8],
            "preference_ids": [item["preference_id"] for item in context.preferences][:5],
            "graph_entities": context.graph_entities[:8],
            "graph_paths": context.graph_paths[:5],
            "projects": context.projects[:6],
            "prior_executions": context.prior_executions,
            "workflows": context.workflows,
            "retrieval_summary": context.retrieval_summary(),
        },
    )

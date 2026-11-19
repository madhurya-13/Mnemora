"""Draft report generation from verified upstream task results only."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agents.agent_safety import sanitize_untrusted_text, truncate_result
from app.agents.agent_schemas import ToolContext, ToolResult
from app.agents.tools.base_tool import ToolSpec
from app.agents.tools.registry import registry

_REQUIRED_SECTIONS = ("## Objective", "## Evidence", "## Findings", "## Recommendations")


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=160)
    include_limitations: bool = True


def _bullet(lines: list[str], empty: str = "- None recorded.") -> str:
    return "\n".join(lines) if lines else empty


def report_generation(context: ToolContext, payload: ReportInput) -> ToolResult:
    upstream = context.upstream_results or []
    completed = [item for item in upstream if item.get("status") == "completed"]
    if not completed:
        return ToolResult(
            ok=False,
            summary="No verified upstream results were available, so no report was generated.",
            error="A report requires at least one completed upstream task.",
            error_kind="permanent",
        )

    evidence_lines: list[str] = []
    finding_lines: list[str] = []
    recommendation_lines: list[str] = []
    limitations: list[str] = []
    for item in completed:
        title = item.get("title", item.get("task_type", "Task"))
        summary = sanitize_untrusted_text(str(item.get("summary", "")), limit=1200)
        finding_lines.append(f"### {title}\n- {summary}")
        for source in item.get("evidence", [])[:10]:
            evidence_lines.append(f"- `{sanitize_untrusted_text(str(source), limit=200)}` ({title})")
        data = item.get("data") or {}
        for recommendation in (data.get("recommendations") or [])[:8]:
            item_text = sanitize_untrusted_text(str(recommendation.get("item", "")), limit=240)
            reason = sanitize_untrusted_text(str(recommendation.get("reason", "")), limit=240)
            severity = sanitize_untrusted_text(str(recommendation.get("severity", "")), limit=20)
            recommendation_lines.append(f"- **{severity or 'info'}** · {item_text} — {reason}")
        for limitation in (data.get("limitations") or [])[:5]:
            limitations.append(f"- {sanitize_untrusted_text(str(limitation), limit=300)}")
        if not item.get("evidence"):
            limitations.append(f"- {title} produced no external evidence references.")

    body = [
        f"# {payload.title}",
        "",
        "## Objective",
        sanitize_untrusted_text(context.plan_objective or "Not recorded.", limit=600),
        "",
        "## Evidence",
        _bullet(evidence_lines, "- No evidence identifiers were returned by the upstream tools."),
        "",
        "## Findings",
        _bullet(finding_lines),
        "",
        "## Recommendations",
        _bullet(recommendation_lines, "- No recommendations were produced."),
        "",
        "## Verification",
        "\n".join(
            f"- {item.get('title', item.get('task_type'))}: {item.get('verification_status', 'pending')}"
            for item in completed
        ),
        "",
        "## Limitations",
        _bullet(
            [*limitations, "- Generated from stored tool output; no external action was performed."],
        ),
    ]
    report = truncate_result("\n".join(body))
    return ToolResult(
        ok=True,
        summary=f"Drafted a {len(report)}-character report from {len(completed)} completed task result(s).",
        data={
            "report": report,
            "sections": list(_REQUIRED_SECTIONS) + ["## Verification", "## Limitations"],
            "source_tasks": [item.get("task_id") for item in completed if item.get("task_id")],
            "evidence_count": len(evidence_lines),
            "recommendation_count": len(recommendation_lines),
            "limitations": limitations,
            "note": "This is a draft stored with the execution; it is not published or sent anywhere.",
        },
        evidence=evidence_lines[:20],
    )


registry.register(
    ToolSpec(
        name="report_generation",
        description="Draft a structured report from completed and verified upstream task results.",
        category="planning",
        permission="reversible",
        input_model=ReportInput,
        handler=report_generation,
        side_effects=True,
    )
)

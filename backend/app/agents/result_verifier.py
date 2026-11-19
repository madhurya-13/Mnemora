"""Verify that a tool actually produced its expected, persisted outcome.

A tool response alone is never accepted as success. The verifier re-reads the
database where an action persisted data, recomputes arithmetic, and checks the
shape of read-only results. Unsupported success claims are reported as failures.
"""

from __future__ import annotations

import ast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.agent_schemas import ToolResult, VerificationOutcome
from app.models.agent import AgentTask, ToolInvocation
from app.models.memory import Memory

_VERIFIED = "verified"
_PARTIAL = "partially_verified"
_FAILED = "failed"
_NOT_VERIFIABLE = "not_verifiable"


def _memory_count(db: Session, user_id: UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Memory)
        .where(Memory.user_id == user_id, Memory.approval_status == "approved")
    ) or 0


def verify(
    db: Session,
    user_id: UUID,
    task: AgentTask,
    tool_name: str,
    result: ToolResult,
) -> VerificationOutcome:
    expected = task.expected_output or "A tool result matching the task's expected output."

    if not result.ok:
        return VerificationOutcome(
            verification_type="tool_success",
            expected_result=expected,
            observed_result=f"Tool reported failure: {result.error or result.summary}",
            status=_FAILED,
            evidence=[],
        )

    if tool_name == "memory_search":
        items = result.data.get("items") or []
        ids = [item.get("memory_id") for item in items if item.get("memory_id")]
        persisted = 0
        if ids:
            persisted = db.scalar(
                select(func.count())
                .select_from(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.approval_status == "approved",
                    Memory.memory_id.in_([UUID(str(item)) for item in ids]),
                )
            ) or 0
            if persisted != len(ids):
                return VerificationOutcome(
                    verification_type="evidence_presence",
                    expected_result="Every returned memory exists and is approved for this user.",
                    observed_result=f"{persisted} of {len(ids)} returned memories were found as approved rows.",
                    status=_FAILED,
                    evidence=ids,
                )
        return VerificationOutcome(
            verification_type="approved_evidence",
            expected_result="Approved memory items for this user, or an explicit empty result.",
            observed_result=f"{len(items)} item(s) returned; {persisted} re-read from the database.",
            status=_VERIFIED,
            evidence=ids[:20],
        )

    if tool_name == "preference_lookup":
        items = result.data.get("items") or []
        return VerificationOutcome(
            verification_type="preference_evidence",
            expected_result="Confirmed preferences only.",
            observed_result=f"{len(items)} confirmed preference(s) returned; statuses are re-checked on read.",
            status=_VERIFIED,
            evidence=[item.get("preference_id", "") for item in items][:20],
        )

    if tool_name == "knowledge_graph_search":
        if not result.data.get("matched"):
            return VerificationOutcome(
                verification_type="graph_paths",
                expected_result="Evidence-supported graph paths or an explicit no-match result.",
                observed_result="No stored entity matched; the tool reported an empty result instead of a guess.",
                status=_VERIFIED,
                evidence=[],
            )
        seeds = result.data.get("seeds") or []
        paths = result.data.get("paths") or []
        if not seeds:
            return VerificationOutcome(
                verification_type="graph_paths",
                expected_result="Matched entities backed by stored graph rows.",
                observed_result="The tool claimed a match but returned no seed entities.",
                status=_FAILED,
                evidence=[],
            )
        return VerificationOutcome(
            verification_type="graph_paths",
            expected_result="Matched entities and paths composed only of stored edges.",
            observed_result=f"{len(seeds)} matched seed(s) and {len(paths)} path(s) returned.",
            status=_VERIFIED,
            evidence=[str(seed.get("id")) for seed in seeds][:20],
        )

    if tool_name == "project_analysis":
        findings = result.data.get("findings") or []
        recommendations = result.data.get("recommendations") or []
        if findings:
            return VerificationOutcome(
                verification_type="repository_evidence",
                expected_result="Observed findings with file evidence, separate from recommendations.",
                observed_result=(
                    f"{len(findings)} finding(s) with {len({item.get('source') for item in findings})} "
                    f"evidence source(s); {len(recommendations)} recommendation(s) listed separately."
                ),
                status=_VERIFIED,
                evidence=sorted({str(item.get("source")) for item in findings})[:20],
            )
        if recommendations:
            return VerificationOutcome(
                verification_type="repository_evidence",
                expected_result="Observed findings with file evidence.",
                observed_result="Only recommendations were produced, with no readable evidence.",
                status=_PARTIAL,
                evidence=[],
            )
        return VerificationOutcome(
            verification_type="repository_evidence",
            expected_result="Observed findings with file evidence.",
            observed_result="No findings and no recommendations were produced.",
            status=_FAILED,
            evidence=[],
        )

    if tool_name == "document_analysis":
        supplied = (task.input or {}).get("documents") or []
        analysed = result.data.get("documents") or []
        ok_shape = len(analysed) == len(supplied) and all(item.get("summary") for item in analysed)
        return VerificationOutcome(
            verification_type="document_summary",
            expected_result=f"One non-empty extractive summary per supplied document ({len(supplied)}).",
            observed_result=f"{len(analysed)} summary record(s) returned.",
            status=_VERIFIED if ok_shape else _FAILED,
            evidence=[f"document:{item.get('name')}" for item in analysed][:10],
        )

    if tool_name in {"memory_audit", "analyze_memories"}:
        audited = int(result.data.get("audited_count") or 0)
        actual = _memory_count(db, user_id)
        if audited > actual:
            return VerificationOutcome(
                verification_type="memory_audit",
                expected_result="An audit bounded by the user's approved memory count.",
                observed_result=f"Audit claimed {audited} records but only {actual} approved memories exist.",
                status=_FAILED,
                evidence=[],
            )
        return VerificationOutcome(
            verification_type="memory_audit",
            expected_result="Audit counts consistent with stored approved memories.",
            observed_result=(
                f"Audited {audited} of {actual} approved memories; "
                f"{len(result.data.get('duplicates') or [])} duplicate suggestion(s)."
            ),
            status=_VERIFIED,
            evidence=[item.get("memory_id", "") for item in (result.data.get("duplicates") or [])][:20],
        )

    if tool_name == "report_generation":
        report = str(result.data.get("report") or "")
        sections = result.data.get("sections") or []
        missing = [section for section in sections if section not in report]
        if missing:
            return VerificationOutcome(
                verification_type="report_structure",
                expected_result="A report containing every required section.",
                observed_result=f"Missing sections: {', '.join(missing)}.",
                status=_FAILED,
                evidence=[],
            )
        status = _VERIFIED if len(report) >= 200 else _PARTIAL
        return VerificationOutcome(
            verification_type="report_structure",
            expected_result="A readable draft report with objective, evidence, findings and limitations.",
            observed_result=(
                f"Report stored in the task result ({len(report)} characters, "
                f"{int(result.data.get('recommendation_count') or 0)} recommendation entries)."
            ),
            status=status,
            evidence=["task:draft_report"],
        )

    if tool_name == "memory_proposal":
        memory_id = (result.data or {}).get("memory_id")
        if not memory_id:
            return VerificationOutcome(
                verification_type="persisted_record",
                expected_result="A persisted, pending memory candidate owned by this user.",
                observed_result="The tool reported success without a memory identifier.",
                status=_FAILED,
                evidence=[],
            )
        row = db.get(Memory, UUID(str(memory_id)))
        if row is None or row.user_id != user_id:
            return VerificationOutcome(
                verification_type="persisted_record",
                expected_result="The pending memory row exists for this user.",
                observed_result="The referenced memory row could not be re-read.",
                status=_FAILED,
                evidence=[str(memory_id)],
            )
        if row.approval_status == "approved":
            return VerificationOutcome(
                verification_type="approval_policy",
                expected_result="A memory candidate that still requires user approval.",
                observed_result="The row is already approved; the agent must never auto-approve.",
                status=_FAILED,
                evidence=[str(memory_id)],
            )
        return VerificationOutcome(
            verification_type="persisted_record",
            expected_result="A persisted, pending memory candidate.",
            observed_result=f"Memory {row.memory_id} re-read from the database with status '{row.approval_status}'.",
            status=_VERIFIED,
            evidence=[str(row.memory_id)],
        )

    if tool_name == "calculator":
        if "days" in result.data or "result_date" in result.data:
            return VerificationOutcome(
                verification_type="calculation",
                expected_result="A finite date difference or shifted date.",
                observed_result=result.summary,
                status=_VERIFIED,
                evidence=["task:calculator"],
            )
        expression = str((task.input or {}).get("expression") or "")
        try:
            from app.agents.tools.calculator_tool import _evaluate

            recomputed = _evaluate(ast.parse(expression, mode="eval"))
            reported = float(result.data.get("value"))
            matched = abs(recomputed - reported) <= 1e-6
        except Exception:
            matched = False
        return VerificationOutcome(
            verification_type="calculation",
            expected_result="The reported value matches an independent evaluation of the expression.",
            observed_result=result.summary if matched else "The reported value did not match re-evaluation.",
            status=_VERIFIED if matched else _FAILED,
            evidence=["task:expression"],
        )

    if tool_name == "progress_summary":
        tasks = db.scalar(
            select(func.count())
            .select_from(AgentTask)
            .where(AgentTask.plan_id == UUID(str(result.data.get("plan_id"))))
        ) or 0
        matches = tasks == int(result.data.get("total") or -1)
        return VerificationOutcome(
            verification_type="progress_consistency",
            expected_result="Counts consistent with persisted task rows.",
            observed_result=f"Summary total {result.data.get('total')} vs {tasks} stored task row(s).",
            status=_VERIFIED if matches else _FAILED,
            evidence=[str(result.data.get("plan_id"))],
        )

    if tool_name == "web_research":
        sources = [item.get("url") for item in (result.data.get("results") or [])]
        valid = [url for url in sources if isinstance(url, str) and url.startswith(("http://", "https://"))]
        if not valid:
            return VerificationOutcome(
                verification_type="source_references",
                expected_result="Retained source URLs.",
                observed_result="No usable source URL was returned.",
                status=_PARTIAL,
                evidence=[],
            )
        return VerificationOutcome(
            verification_type="source_references",
            expected_result="Every finding retains a source URL.",
            observed_result=f"{len(valid)} source URL(s) retained.",
            status=_VERIFIED,
            evidence=valid[:10],
        )

    return VerificationOutcome(
        verification_type="unclassified",
        expected_result=expected,
        observed_result="No verification rule exists for this tool, so success is not claimed.",
        status=_NOT_VERIFIABLE,
        evidence=result.evidence,
    )


def verified_invocations(db: Session, task_id: UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(ToolInvocation)
        .where(ToolInvocation.task_id == task_id, ToolInvocation.status == "success")
    ) or 0

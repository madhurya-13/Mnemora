"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ban,
  Check,
  ChevronRight,
  Clock3,
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
  Terminal,
  X,
} from "lucide-react";
import {
  approveAgentAction,
  cancelAgentExecution,
  getAgentExecution,
  listAgentApprovals,
  listAgentEvents,
  listAgentExecutions,
  listAgentInvocations,
  listAgentVerifications,
  pauseAgentExecution,
  rejectAgentAction,
  resumeAgentExecution,
  type AgentAnalytics,
  type AgentApproval,
  type AgentEvent,
  type AgentExecution,
  type AgentInvocation,
  type AgentVerification,
} from "@/lib/agents";
import { ApiError } from "@/lib/api";
import { Alert, EmptyState, KeyValue, Panel, ProgressBar, Spinner, StatusPill, cx, formatDateTime, formatDuration, humanize } from "@/components/agents/ui";

type Props = {
  analytics: AgentAnalytics | null;
  focusExecutionId: string | null;
  onFocusHandled: () => void;
  onChanged: () => void;
};

type DetailTab = "steps" | "activity" | "verification" | "tool calls";

const EXECUTION_FILTERS = [
  { value: "", label: "All" },
  { value: "awaiting_approval", label: "Awaiting approval" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "partially_completed", label: "Partial" },
  { value: "failed", label: "Failed" },
];

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "The execution request could not be completed.";
}

function isActive(execution: AgentExecution | null): boolean {
  return !!execution && ["created", "planning", "executing", "awaiting_approval"].includes(execution.status);
}

function durationBetween(start: string | null, end: string | null): string {
  if (!start) return "—";
  const startTime = new Date(start).getTime();
  const endTime = end ? new Date(end).getTime() : Date.now();
  if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || endTime < startTime) return "—";
  return formatDuration(endTime - startTime);
}

export default function ExecutionsPanel({ analytics, focusExecutionId, onFocusHandled, onChanged }: Props) {
  const [executions, setExecutions] = useState<AgentExecution[]>([]);
  const [approvals, setApprovals] = useState<AgentApproval[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentExecution | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [verifications, setVerifications] = useState<AgentVerification[]>([]);
  const [invocations, setInvocations] = useState<AgentInvocation[]>([]);
  const [filter, setFilter] = useState("");
  const [tab, setTab] = useState<DetailTab>("steps");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const loadList = useCallback(async () => {
    try {
      const [executionPage, approvalPage] = await Promise.all([
        listAgentExecutions({ status: filter || undefined, limit: 50 }),
        listAgentApprovals({ limit: 100 }),
      ]);
      setExecutions(executionPage.items);
      setApprovals(approvalPage.items);
      setSelectedId((current) => {
        if (current && executionPage.items.some((item) => item.execution_id === current)) return current;
        return executionPage.items[0]?.execution_id ?? null;
      });
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  const loadDetail = useCallback(async (executionId: string) => {
    setDetailLoading(true);
    try {
      const [execution, eventPage, verificationPage, invocationRows] = await Promise.all([
        getAgentExecution(executionId),
        listAgentEvents(executionId),
        listAgentVerifications(executionId),
        listAgentInvocations(executionId),
      ]);
      setDetail(execution);
      setEvents([...eventPage.items].sort((left, right) => left.sequence - right.sequence));
      setVerifications(verificationPage.items);
      setInvocations(invocationRows);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadList();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadList]);

  useEffect(() => {
    if (!focusExecutionId) return;
    const timer = window.setTimeout(() => {
      setSelectedId(focusExecutionId);
      onFocusHandled();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [focusExecutionId, onFocusHandled]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!selectedId) {
        setDetail(null);
        setEvents([]);
        setVerifications([]);
        setInvocations([]);
        return;
      }
      void loadDetail(selectedId);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selectedId, loadDetail]);

  useEffect(() => {
    const active = isActive(detail) || detail?.status === "paused";
    if (!active) return;
    const timer = window.setInterval(() => {
      void loadList();
      if (selectedId) void loadDetail(selectedId);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [detail, loadList, loadDetail, selectedId]);

  const pendingApprovals = useMemo(
    () => approvals.filter((item) => item.status === "pending" && !item.expired),
    [approvals],
  );
  const executionApprovals = useMemo(
    () => approvals.filter((item) => item.execution_id === selectedId),
    [approvals, selectedId],
  );

  async function reload(executionId?: string) {
    await loadList();
    const target = executionId ?? selectedId;
    if (target) await loadDetail(target);
    onChanged();
  }

  async function pause() {
    if (!detail) return;
    setBusy("pause");
    setError(null);
    try {
      const execution = await pauseAgentExecution(detail.execution_id);
      setNotice("Pause requested. The run loop stops at the next task boundary; the current tool call is not interrupted.");
      setDetail(execution);
      await reload(execution.execution_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function resume(executionId?: string) {
    const target = executionId ?? detail?.execution_id;
    if (!target) return;
    setBusy("resume");
    setError(null);
    try {
      const execution = await resumeAgentExecution(target);
      setNotice(
        execution.status === "awaiting_approval"
          ? "Execution is waiting for another approval decision."
          : `Execution resumed and finished with status: ${execution.status}.`,
      );
      setDetail(execution);
      await reload(execution.execution_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function cancel() {
    if (!detail) return;
    setBusy("cancel");
    setError(null);
    try {
      const execution = await cancelAgentExecution(detail.execution_id);
      setNotice("Cancellation accepted. Completed results are preserved; no further tasks will run.");
      setDetail(execution);
      await reload(execution.execution_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function decide(approval: AgentApproval, approve: boolean) {
    setBusy(approval.approval_id);
    setError(null);
    setNotice(null);
    try {
      if (approve) {
        await approveAgentAction(approval.approval_id, notes[approval.approval_id]);
      } else {
        await rejectAgentAction(approval.approval_id, notes[approval.approval_id]);
      }
      setNotice(
        approve
          ? "Action approved once. Resuming the execution now; the approval cannot be reused."
          : "Action rejected. The task will not run; the execution is resuming so unrelated steps can continue.",
      );
      await resume(approval.execution_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.6fr)]">
      <div className="space-y-4">
        <Panel
          title="Executions"
          description={`${analytics?.active_executions ?? 0} active — ${pendingApprovals.length} action(s) waiting for a decision.`}
          action={
            <button type="button" onClick={() => void reload()} className="rounded-lg p-1.5 text-slate-500 hover:text-violet-200" aria-label="Refresh executions">
              <RefreshCw size={14} />
            </button>
          }
        >
          <div className="mb-3 flex flex-wrap gap-1.5">
            {EXECUTION_FILTERS.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setFilter(item.value)}
                className={cx(
                  "rounded-full border px-2.5 py-1 text-[10px] transition",
                  filter === item.value
                    ? "border-violet-300/30 bg-violet-300/10 text-violet-100"
                    : "border-white/[0.06] text-slate-500 hover:text-slate-300",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          {loading ? (
            <Spinner label="Loading executions…" />
          ) : executions.length === 0 ? (
            <EmptyState>No executions in this view. Approve a plan and run it from the Planner tab.</EmptyState>
          ) : (
            <ul className="space-y-1.5">
              {executions.map((execution) => {
                const waiting = approvals.filter(
                  (item) => item.execution_id === execution.execution_id && item.status === "pending",
                ).length;
                return (
                  <li key={execution.execution_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(execution.execution_id)}
                      className={cx(
                        "w-full rounded-xl border px-3 py-2.5 text-left transition",
                        selectedId === execution.execution_id
                          ? "border-violet-300/30 bg-violet-300/[0.07]"
                          : "border-white/[0.05] hover:border-white/[0.12] hover:bg-white/[0.02]",
                      )}
                    >
                      <div className="flex items-start gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs font-medium text-slate-100">{execution.plan_title ?? "Execution"}</p>
                          <p className="mt-0.5 text-[10px] text-slate-600">{formatDateTime(execution.created_at)}</p>
                        </div>
                        <StatusPill status={execution.status} />
                      </div>
                      <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-600">
                        <span>{execution.progress}%</span>
                        <span>•</span>
                        <span>{execution.task_counts.completed}/{execution.task_counts.total} steps</span>
                        {waiting > 0 && <span className="text-amber-300/80">{waiting} approval</span>}
                        <ChevronRight size={12} className="ml-auto" />
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel title="Pending approvals" description="Each approval is bound to one task's exact parameters, expires, and can be consumed once.">
          {pendingApprovals.length === 0 ? (
            <EmptyState>No actions are waiting for approval.</EmptyState>
          ) : (
            <ul className="space-y-2">
              {pendingApprovals.map((approval) => (
                <li key={approval.approval_id} className="rounded-xl border border-amber-300/20 bg-amber-300/[0.04] p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-[11px] font-medium text-amber-100">{approval.action_summary}</p>
                      <p className="mt-1 text-[10px] leading-4 text-amber-100/70">{approval.reason}</p>
                    </div>
                    <StatusPill status={approval.expired ? "expired" : approval.status} />
                  </div>
                  <div className="mt-2 space-y-1 text-[9px] leading-4 text-amber-100/60">
                    <p>Tool: {approval.tool_name}</p>
                    <p>Impact: {approval.expected_impact}</p>
                    <p>Reversible: {approval.reversible ? "yes" : "no"} • Expires: {formatDateTime(approval.expires_at)}</p>
                    {approval.data_involved.length > 0 && <p>Data: {approval.data_involved.join(", ")}</p>}
                  </div>
                  <input
                    value={notes[approval.approval_id] ?? ""}
                    onChange={(event) => setNotes((current) => ({ ...current, [approval.approval_id]: event.target.value }))}
                    placeholder="Optional decision note"
                    className="mt-2 w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[10px] text-slate-100"
                  />
                  <details className="mt-1.5">
                    <summary className="cursor-pointer text-[9px] text-amber-100/60">Exact parameters</summary>
                    <pre className="mt-1 max-h-32 overflow-auto rounded-lg border border-white/[0.06] bg-black/25 p-2 text-[9px] leading-4 text-slate-400">
                      {JSON.stringify(approval.parameters, null, 2)}
                    </pre>
                  </details>
                  <div className="mt-2 flex gap-1.5">
                    <button
                      type="button"
                      onClick={() => void decide(approval, true)}
                      disabled={busy !== null || approval.expired}
                      className="inline-flex flex-1 items-center justify-center gap-1 rounded-lg border border-emerald-300/25 bg-emerald-300/10 px-2 py-1.5 text-[10px] text-emerald-100 disabled:opacity-40"
                    >
                      {busy === approval.approval_id ? <LoaderCircle size={11} className="animate-spin" /> : <Check size={11} />} Approve once
                    </button>
                    <button
                      type="button"
                      onClick={() => void decide(approval, false)}
                      disabled={busy !== null || approval.expired}
                      className="inline-flex flex-1 items-center justify-center gap-1 rounded-lg border border-rose-300/25 bg-rose-300/10 px-2 py-1.5 text-[10px] text-rose-100 disabled:opacity-40"
                    >
                      <Ban size={11} /> Reject
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="space-y-3">
        {error && <Alert tone="error">{error}</Alert>}
        {notice && <Alert tone="success">{notice}</Alert>}
        {detailLoading ? (
          <Panel><Spinner label="Loading execution…" /></Panel>
        ) : !detail ? (
          <Panel><EmptyState>Select an execution to inspect its steps, events, verification and tool calls.</EmptyState></Panel>
        ) : (
          <>
            <Panel
              title={detail.plan_title ?? "Execution"}
              description={`Execution ${detail.execution_id}`}
              action={<StatusPill status={detail.status} />}
            >
              <div className="space-y-3">
                <ProgressBar value={detail.progress} label="Execution progress" definition={detail.progress_definition} />
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <KeyValue label="Completed">{detail.task_counts.completed}/{detail.task_counts.total}</KeyValue>
                  <KeyValue label="Failed">{detail.task_counts.failed}</KeyValue>
                  <KeyValue label="Waiting">{detail.task_counts.awaiting_approval}</KeyValue>
                  <KeyValue label="Elapsed">{durationBetween(detail.started_at, detail.finished_at)}</KeyValue>
                </dl>
                {detail.error && <Alert tone="error">{detail.error}</Alert>}
                {detail.current_task && (
                  <div className="rounded-xl border border-violet-300/15 bg-violet-300/[0.04] px-3 py-2 text-[10px] text-violet-100">
                    Current step: {detail.current_task.title}
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  {detail.status === "executing" && (
                    <button type="button" onClick={() => void pause()} disabled={busy !== null} className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.1] px-3 py-1.5 text-[11px] text-slate-200 disabled:opacity-40">
                      <Pause size={12} /> Pause
                    </button>
                  )}
                  {(detail.status === "paused" || detail.status === "awaiting_approval") && (
                    <button
                      type="button"
                      onClick={() => void resume()}
                      disabled={busy !== null || (detail.status === "awaiting_approval" && pendingApprovals.some((item) => item.execution_id === detail.execution_id))}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-violet-300/25 bg-violet-300/10 px-3 py-1.5 text-[11px] text-violet-100 disabled:opacity-40"
                    >
                      <Play size={12} /> Resume
                    </button>
                  )}
                  {isActive(detail) && (
                    <button type="button" onClick={() => void cancel()} disabled={busy !== null} className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-rose-300/20 px-3 py-1.5 text-[11px] text-rose-200 disabled:opacity-40">
                      <X size={12} /> Cancel
                    </button>
                  )}
                </div>
                {detail.status === "awaiting_approval" && pendingApprovals.some((item) => item.execution_id === detail.execution_id) && (
                  <Alert tone="info">
                    Approve or reject the pending action first. Approving automatically resumes this execution exactly once.
                  </Alert>
                )}
              </div>
            </Panel>

            <Panel title="Verification and learning" description="Success is claimed only when the verifier re-checks the persisted result.">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-white/[0.06] p-3">
                  <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-slate-200"><ShieldCheck size={13} className="text-emerald-300" /> Verified outcomes</p>
                  {verifications.length === 0 ? (
                    <p className="text-[10px] text-slate-500">No verification records yet.</p>
                  ) : (
                    <ul className="space-y-1.5">
                      {verifications.map((verification) => (
                        <li key={verification.verification_id} className="flex items-start gap-2 text-[10px] leading-4 text-slate-400">
                          <StatusPill status={verification.status} />
                          <span className="min-w-0 flex-1">{verification.observed_result}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="rounded-xl border border-white/[0.06] p-3">
                  <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-slate-200"><Activity size={13} className="text-violet-300" /> Learning record</p>
                  {Object.keys(detail.learning).length === 0 ? (
                    <p className="text-[10px] text-slate-500">No learning recorded for this execution.</p>
                  ) : (
                    <pre className="max-h-40 overflow-auto rounded-lg bg-black/25 p-2 text-[9px] leading-4 text-slate-400">{JSON.stringify(detail.learning, null, 2)}</pre>
                  )}
                </div>
              </div>
            </Panel>

            <Panel
              title="Run detail"
              description="Steps are the source of truth; events and tool calls are an audit trail."
              action={
                <div className="flex flex-wrap gap-1">
                  {(["steps", "activity", "verification", "tool calls"] as DetailTab[]).map((item) => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => setTab(item)}
                      className={cx(
                        "rounded-full border px-2 py-0.5 text-[9px] capitalize",
                        tab === item ? "border-violet-300/30 bg-violet-300/10 text-violet-100" : "border-white/[0.06] text-slate-500",
                      )}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              }
            >
              {tab === "steps" && (
                <ol className="space-y-2">
                  {detail.tasks.map((task) => (
                    <li key={task.task_id} className="rounded-xl border border-white/[0.06] bg-white/[0.015] p-3">
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 text-[10px] text-slate-600">{task.sequence + 1}.</span>
                        <div className="min-w-0 flex-1">
                          <p className="text-[11px] font-medium text-slate-100">{task.title}</p>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[9px] text-slate-600">
                            <span>{task.assigned_tool ?? task.task_type}</span>
                            {task.execution_attempts > 0 && <span>• {task.execution_attempts}/{task.max_attempts} attempts</span>}
                            {task.completed_at && <span>• {formatDateTime(task.completed_at)}</span>}
                          </div>
                          {task.error && <p className="mt-1.5 text-[10px] leading-4 text-rose-200">{task.error}</p>}
                          {typeof task.result?.summary === "string" && <p className="mt-1.5 text-[10px] leading-4 text-slate-400">{task.result.summary}</p>}
                          {task.approval && <p className="mt-1.5 text-[9px] text-amber-200/80">Approval: {task.approval.status}</p>}
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <StatusPill status={task.status} />
                          <StatusPill status={task.verification_status} />
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
              {tab === "activity" && (
                events.length === 0 ? <EmptyState>No events recorded.</EmptyState> : (
                  <ol className="space-y-2">
                    {events.map((event) => (
                      <li key={event.event_id} className="flex gap-2 text-[10px] leading-4">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-300/50" />
                        <div className="min-w-0 flex-1">
                          <p className="text-slate-300">{event.message}</p>
                          <p className="mt-0.5 flex items-center gap-1.5 text-[9px] text-slate-600">
                            <Clock3 size={9} /> {formatDateTime(event.created_at)} • {humanize(event.event_type)}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ol>
                )
              )}
              {tab === "verification" && (
                verifications.length === 0 ? <EmptyState>No verification records.</EmptyState> : (
                  <ul className="space-y-2">
                    {verifications.map((verification) => (
                      <li key={verification.verification_id} className="rounded-xl border border-white/[0.06] p-3 text-[10px] leading-4">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-300">{verification.verification_type}</span>
                          <StatusPill status={verification.status} />
                        </div>
                        <p className="mt-1 text-slate-500">Expected: {verification.expected_result}</p>
                        <p className="text-slate-400">Observed: {verification.observed_result}</p>
                        {verification.evidence.length > 0 && <p className="mt-1 text-[9px] text-slate-600">Evidence: {verification.evidence.join(", ")}</p>}
                      </li>
                    ))}
                  </ul>
                )
              )}
              {tab === "tool calls" && (
                invocations.length === 0 ? <EmptyState>No tool calls recorded.</EmptyState> : (
                  <ul className="space-y-2">
                    {invocations.map((invocation) => (
                      <li key={invocation.invocation_id} className="rounded-xl border border-white/[0.06] p-3">
                        <div className="flex items-center justify-between gap-2">
                          <p className="flex items-center gap-1.5 text-[10px] text-slate-300"><Terminal size={11} /> {invocation.tool_name}</p>
                          <StatusPill status={invocation.status} />
                        </div>
                        <p className="mt-1 text-[9px] text-slate-600">
                          {invocation.attempts} attempt(s) • {formatDuration(invocation.duration_ms)} • {formatDateTime(invocation.created_at)}
                        </p>
                        {invocation.error && <p className="mt-1 text-[10px] leading-4 text-rose-200">{invocation.error}</p>}
                        <details className="mt-1.5">
                          <summary className="cursor-pointer text-[9px] text-slate-500">Arguments and output preview</summary>
                          <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-black/25 p-2 text-[9px] leading-4 text-slate-400">
                            {JSON.stringify({ arguments: invocation.arguments_preview, output: invocation.output_preview }, null, 2)}
                          </pre>
                        </details>
                      </li>
                    ))}
                  </ul>
                )
              )}
            </Panel>

            {executionApprovals.length > 0 && (
              <Panel title="Approval history for this execution" description="Approvals are parameter-bound and single-use; a changed task invalidates its approval.">
                <ul className="space-y-1.5">
                  {executionApprovals.map((approval) => (
                    <li key={approval.approval_id} className="flex items-start gap-2 rounded-lg border border-white/[0.06] px-3 py-2 text-[10px] leading-4">
                      <StatusPill status={approval.expired ? "expired" : approval.status} />
                      <span className="min-w-0 flex-1 text-slate-400">{approval.action_summary}</span>
                      <span className="shrink-0 text-[9px] text-slate-600">{formatDateTime(approval.decided_at ?? approval.created_at)}</span>
                    </li>
                  ))}
                </ul>
              </Panel>
            )}
          </>
        )}
        {analytics && analytics.failed_verifications > 0 && (
          <Alert tone="error">
            <span className="inline-flex items-center gap-1.5"><AlertTriangle size={12} /> {analytics.failed_verifications} task result(s) failed verification and are not counted as successful.</span>
          </Alert>
        )}
      </div>
    </div>
  );
}

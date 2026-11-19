"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Bot,
  Brain,
  CheckCircle2,
  Clock3,
  ListChecks,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Workflow,
} from "lucide-react";
import {
  getAgentAnalytics,
  type AgentAnalytics,
} from "@/lib/agents";
import { ApiError } from "@/lib/api";
import { Alert, EmptyState, KeyValue, Panel, Spinner, StatusPill, cx, formatDateTime, humanize } from "@/components/agents/ui";
import PlannerPanel from "@/components/agents/PlannerPanel";
import ExecutionsPanel from "@/components/agents/ExecutionsPanel";
import CatalogPanel from "@/components/agents/CatalogPanel";

type Tab = "overview" | "planner" | "executions" | "catalog";

const TABS: { value: Tab; label: string; icon: typeof Bot }[] = [
  { value: "overview", label: "Overview", icon: Activity },
  { value: "planner", label: "Planner", icon: ListChecks },
  { value: "executions", label: "Executions", icon: Bot },
  { value: "catalog", label: "Tools & workflows", icon: Workflow },
];

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Could not reach the agent service.";
}

export default function AgentsDashboard() {
  const [tab, setTab] = useState<Tab>("overview");
  const [analytics, setAnalytics] = useState<AgentAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [focusExecutionId, setFocusExecutionId] = useState<string | null>(null);

  const refreshAnalytics = useCallback(async () => {
    try {
      const payload = await getAgentAnalytics();
      setAnalytics(payload);
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshAnalytics();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshAnalytics]);

  useEffect(() => {
    const timer = window.setInterval(() => void refreshAnalytics(), 15000);
    return () => window.clearInterval(timer);
  }, [refreshAnalytics]);

  function openExecution(executionId: string) {
    setFocusExecutionId(executionId);
    setTab("executions");
  }

  return (
    <div className="min-h-screen bg-[#080a12] text-slate-100">
      <div className="mx-auto w-full max-w-[1500px] px-4 pb-16 pt-5 sm:px-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <Link
              href="/"
              className="mt-0.5 grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] text-slate-400 transition hover:border-violet-300/25 hover:text-violet-200"
              aria-label="Back to chat"
            >
              <ArrowLeft size={16} />
            </Link>
            <div>
              <p className="flex items-center gap-2 text-[10px] uppercase tracking-[0.24em] text-violet-300/70">
                <Brain size={12} /> MNEMORA
              </p>
              <h1 className="mt-1 flex items-center gap-2 text-xl font-semibold text-slate-50">
                <Bot size={20} className="text-violet-300" /> Agent Control Center
              </h1>
              <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">
                Deterministic planning, allowlisted tools, single-use approvals, verified outcomes and bounded recovery.
                Progress and success are computed only from persisted task states.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refreshAnalytics()}
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.08] px-3 py-2 text-[11px] text-slate-300 transition hover:border-violet-300/25 hover:text-violet-100"
            >
              <RefreshCw size={13} /> Refresh
            </button>
            <Link
              href="/graph"
              className="hidden items-center gap-1.5 rounded-xl border border-white/[0.06] px-3 py-2 text-[11px] text-slate-400 transition hover:text-blue-100 sm:inline-flex"
            >
              Knowledge graph
            </Link>
            <Link
              href="/memory"
              className="hidden items-center gap-1.5 rounded-xl border border-white/[0.06] px-3 py-2 text-[11px] text-slate-400 transition hover:text-violet-100 sm:inline-flex"
            >
              Memory
            </Link>
          </div>
        </header>

        <nav className="mt-5 flex flex-wrap gap-1.5 border-b border-white/[0.06] pb-2">
          {TABS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.value}
                type="button"
                onClick={() => setTab(item.value)}
                className={cx(
                  "inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-[11px] transition",
                  tab === item.value
                    ? "bg-violet-300/[0.09] text-violet-100"
                    : "text-slate-500 hover:bg-white/[0.03] hover:text-slate-300",
                )}
              >
                <Icon size={13} /> {item.label}
                {item.value === "executions" && (analytics?.pending_approvals ?? 0) > 0 && (
                  <span className="rounded-full bg-amber-300/15 px-1.5 py-0.5 text-[9px] text-amber-200">
                    {analytics?.pending_approvals}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <main className="pt-4">
          {error && (
            <div className="mb-4">
              <Alert tone="error">{error}</Alert>
            </div>
          )}

          {tab === "overview" && (
            <Overview analytics={analytics} loading={loading} onNavigate={setTab} />
          )}

          {tab === "planner" && (
            <PlannerPanel
              analytics={analytics}
              onChanged={() => void refreshAnalytics()}
              onOpenExecution={openExecution}
            />
          )}

          {tab === "executions" && (
            <ExecutionsPanel
              analytics={analytics}
              focusExecutionId={focusExecutionId}
              onFocusHandled={() => setFocusExecutionId(null)}
              onChanged={() => void refreshAnalytics()}
            />
          )}

          {tab === "catalog" && (
            <CatalogPanel
              onChanged={() => void refreshAnalytics()}
              onOpenExecution={openExecution}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function Overview({
  analytics,
  loading,
  onNavigate,
}: {
  analytics: AgentAnalytics | null;
  loading: boolean;
  onNavigate: (tab: Tab) => void;
}) {
  if (loading && !analytics) {
    return (
      <Panel>
        <Spinner label="Loading agent activity…" />
      </Panel>
    );
  }

  if (!analytics) {
    return (
      <Panel>
        <EmptyState>The agent service is not reachable. Start the backend and refresh.</EmptyState>
      </Panel>
    );
  }

  const cards = [
    {
      label: "Success rate",
      value:
        analytics.success_rate_percent === null ? "—" : `${analytics.success_rate_percent}%`,
      hint: `${analytics.completed_executions} completed of ${analytics.terminal_executions} finished runs`,
      icon: CheckCircle2,
    },
    {
      label: "Active executions",
      value: String(analytics.active_executions),
      hint: `${analytics.total_executions} total execution(s) recorded`,
      icon: Activity,
    },
    {
      label: "Awaiting approval",
      value: String(analytics.pending_approvals),
      hint: `${analytics.plans_waiting_for_approval} plan(s) approved and ready to run`,
      icon: ShieldAlert,
    },
    {
      label: "Verified tasks",
      value: String(analytics.verified_tasks),
      hint: `${analytics.partially_verified_tasks} partial, ${analytics.failed_verifications} failed verification`,
      icon: ListChecks,
    },
    {
      label: "Workflows",
      value: String(analytics.workflow_count),
      hint: `${analytics.suggested_workflows} learned suggestion(s) awaiting review`,
      icon: Workflow,
    },
    {
      label: "Plans",
      value: String(analytics.total_plans),
      hint: `${analytics.failed_executions} failed execution(s)`,
      icon: Sparkles,
    },
  ];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className="rounded-2xl border border-white/[0.07] bg-[#0d101a]/90 p-4 shadow-[0_18px_60px_rgba(3,5,12,0.35)]"
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{card.label}</span>
                <Icon size={14} className="text-violet-300/80" />
              </div>
              <p className="mt-2 text-2xl font-semibold text-slate-50">{card.value}</p>
              <p className="mt-1 text-[10px] leading-4 text-slate-500">{card.hint}</p>
            </div>
          );
        })}
      </div>

      {analytics.success_rate_definition && (
        <p className="px-1 text-[10px] leading-4 text-slate-600">{analytics.success_rate_definition}</p>
      )}

      {(analytics.failed_verifications > 0 || analytics.pending_approvals > 0) && (
        <Alert tone={analytics.failed_verifications > 0 ? "error" : "info"}>
          {analytics.failed_verifications > 0 ? (
            <span className="inline-flex items-center gap-1.5">
              <AlertTriangle size={12} /> {analytics.failed_verifications} result(s) failed verification and are
              explicitly excluded from success counts.
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5">
              <Clock3 size={12} /> {analytics.pending_approvals} sensitive action(s) are waiting for a decision.
            </span>
          )}
        </Alert>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Panel
          title="Recent task activity"
          description="Every row is a persisted task state, including verification outcome."
          action={
            <button
              type="button"
              onClick={() => onNavigate("executions")}
              className="text-[10px] text-violet-300/80 hover:text-violet-200"
            >
              Open executions
            </button>
          }
        >
          {analytics.recent_tasks.length === 0 ? (
            <EmptyState>No tasks yet. Create a plan in the Planner tab.</EmptyState>
          ) : (
            <ul className="space-y-1.5">
              {analytics.recent_tasks.map((task) => (
                <li
                  key={task.task_id}
                  className="rounded-xl border border-white/[0.06] bg-white/[0.015] px-3 py-2"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-[11px] text-slate-200">{task.title}</p>
                      <p className="mt-0.5 text-[9px] text-slate-600">
                        {task.plan_title ?? "Plan"} • {task.assigned_tool ?? "no tool"} •{" "}
                        {formatDateTime(task.updated_at)}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <StatusPill status={task.status} />
                      <StatusPill status={task.verification_status} />
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="Tool usage" description="Counts come from completed tool invocations only.">
            {analytics.tool_usage.length === 0 ? (
              <EmptyState>No tool invocations yet.</EmptyState>
            ) : (
              <ul className="space-y-1.5">
                {analytics.tool_usage.map((tool) => {
                  const total = tool.success + tool.failure;
                  const percent = total > 0 ? Math.round((tool.success / total) * 100) : 0;
                  return (
                    <li key={tool.tool_name}>
                      <div className="mb-1 flex items-center justify-between text-[10px] text-slate-400">
                        <span className="truncate">{tool.tool_name}</span>
                        <span className="text-slate-500">
                          {tool.success} ok / {tool.failure} failed
                        </span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-violet-400"
                          style={{ width: `${percent}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          <Panel
            title="Recent events"
            description="Append-only execution audit trail."
            action={
              <button
                type="button"
                onClick={() => onNavigate("executions")}
                className="text-[10px] text-violet-300/80 hover:text-violet-200"
              >
                View all
              </button>
            }
          >
            {analytics.recent_events.length === 0 ? (
              <EmptyState>No events recorded.</EmptyState>
            ) : (
              <ul className="max-h-64 space-y-1.5 overflow-auto">
                {analytics.recent_events.map((event) => (
                  <li key={event.event_id} className="flex gap-2 text-[10px] leading-4">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-300/50" />
                    <div className="min-w-0 flex-1">
                      <p className="text-slate-300">{event.message}</p>
                      <p className="text-[9px] text-slate-600">
                        {humanize(event.event_type)} • {formatDateTime(event.created_at)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>

      <Panel title="Capability boundaries" description="These guarantees are enforced in the backend, not by UI convention.">
        <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KeyValue label="Tool access">Allowlisted registry only</KeyValue>
          <KeyValue label="Approvals">Single-use, parameter-bound, expiring</KeyValue>
          <KeyValue label="Retries">Bounded; never blind for side effects</KeyValue>
          <KeyValue label="Progress">Persisted task states only</KeyValue>
          <KeyValue label="Restart">Queued work is never auto-rerun</KeyValue>
          <KeyValue label="Learning">Completed and verified tasks only</KeyValue>
          <KeyValue label="Isolation">Owner-scoped rows and lookups</KeyValue>
          <KeyValue label="Memory writes">Stay pending until approved</KeyValue>
        </dl>
      </Panel>
    </div>
  );
}

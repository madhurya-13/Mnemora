"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronRight,
  ClipboardList,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  X,
} from "lucide-react";
import {
  AGENT_TASK_TYPES,
  approveAgentPlan,
  archiveAgentPlan,
  createAgentPlan,
  executeAgentPlan,
  getAgentPlan,
  listAgentPlans,
  updateAgentPlan,
  type AgentAnalytics,
  type AgentPlan,
  type AgentTask,
  type AgentTaskType,
  type PlanTaskInput,
} from "@/lib/agents";
import { ApiError } from "@/lib/api";
import { Alert, EmptyState, KeyValue, Panel, ProgressBar, Spinner, StatusPill, cx } from "@/components/agents/ui";

type Props = {
  analytics: AgentAnalytics | null;
  onChanged: () => void;
  onOpenExecution: (executionId: string) => void;
};

type EditTask = {
  title: string;
  description: string;
  task_type: AgentTaskType;
  expected_output: string;
  dependencies: string;
  input: string;
};

const PLAN_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "All plans" },
  { value: "needs_clarification", label: "Clarification" },
  { value: "approved", label: "Ready to run" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "archived", label: "Archived" },
];

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "The plan request could not be completed.";
}

function taskSummary(task: AgentTask): string | null {
  const result = task.result;
  if (!result) return null;
  const summary = result.summary;
  return typeof summary === "string" && summary ? summary : null;
}

function toEditTask(task: AgentTask): EditTask {
  return {
    title: task.title,
    description: task.description,
    task_type: task.task_type,
    expected_output: task.expected_output,
    dependencies: task.dependencies.join(", "),
    input: JSON.stringify(task.input ?? {}, null, 2),
  };
}

function planEditable(plan: AgentPlan): boolean {
  return ["draft", "needs_clarification", "approved"].includes(plan.status);
}

export default function PlannerPanel({ analytics, onChanged, onOpenExecution }: Props) {
  const [plans, setPlans] = useState<AgentPlan[]>([]);
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [objective, setObjective] = useState("");
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("normal");
  const [documents, setDocuments] = useState<{ name: string; text: string }[]>([]);

  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editPriority, setEditPriority] = useState("normal");
  const [editTasks, setEditTasks] = useState<EditTask[]>([]);

  const loadPlans = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await listAgentPlans({ status: filter || undefined, limit: 50 });
      setPlans(payload.items);
      setSelectedId((current) => {
        if (current && payload.items.some((item) => item.plan_id === current)) return current;
        return payload.items[0]?.plan_id ?? null;
      });
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadPlans();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadPlans]);

  const loadDetail = useCallback(async (planId: string) => {
    setDetailLoading(true);
    try {
      const plan = await getAgentPlan(planId);
      setDetail(plan);
      setAnswers((current) => {
        const next = { ...current };
        for (const clarification of plan.clarifications) {
          if (!(clarification.id in next) && clarification.options?.length) {
            next[clarification.id] = clarification.options[0];
          }
        }
        return next;
      });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!selectedId) {
        setDetail(null);
        return;
      }
      void loadDetail(selectedId);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selectedId, loadDetail]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!detail) {
        setEditing(false);
        return;
      }
      setEditTitle(detail.title);
      setEditDescription(detail.description);
      setEditPriority(detail.priority);
      setEditTasks(detail.tasks.map(toEditTask));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [detail]);

  async function refreshAll(planId?: string) {
    await loadPlans();
    const target = planId ?? selectedId;
    if (target) await loadDetail(target);
    onChanged();
  }

  async function submitCreate() {
    if (objective.trim().length < 3) {
      setError("Describe the objective before creating a plan.");
      return;
    }
    setBusy("create");
    setError(null);
    setNotice(null);
    try {
      const plan = await createAgentPlan({
        objective: objective.trim(),
        title: title.trim() || undefined,
        priority,
        documents: documents.filter((item) => item.name.trim() && item.text.trim()),
      });
      setObjective("");
      setTitle("");
      setDocuments([]);
      setSelectedId(plan.plan_id);
      setNotice(`Plan created: ${plan.title}. Review the steps, then approve and execute.`);
      await refreshAll(plan.plan_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function submitApproval() {
    if (!detail) return;
    setBusy("approve");
    setError(null);
    try {
      const payload = detail.clarifications.map((item) => ({
        id: item.id,
        answer: (answers[item.id] || "").trim(),
      }));
      if (payload.some((item) => !item.answer)) {
        setError("Answer every clarification question before approving.");
        return;
      }
      const plan = await approveAgentPlan(detail.plan_id, payload);
      setDetail(plan);
      if (plan.status === "needs_clarification") {
        setNotice("Some clarification answers are still missing.");
      } else {
        setNotice("Plan approved. Execute it when you are ready.");
      }
      await refreshAll(plan.plan_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function submitExecute() {
    if (!detail) return;
    setBusy("execute");
    setError(null);
    setNotice(null);
    try {
      const execution = await executeAgentPlan(detail.plan_id);
      setNotice(
        execution.status === "awaiting_approval"
          ? "Execution paused for approval. Open the execution to approve the pending action."
          : `Execution finished with status: ${execution.status}.`,
      );
      await refreshAll(detail.plan_id);
      onOpenExecution(execution.execution_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function submitArchive() {
    if (!detail) return;
    setBusy("archive");
    setError(null);
    try {
      const plan = await archiveAgentPlan(detail.plan_id);
      setDetail(plan);
      setNotice("Plan archived. It remains readable and is never executed again.");
      await refreshAll(plan.plan_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function submitEdit() {
    if (!detail) return;
    const tasks: PlanTaskInput[] = [];
    for (let index = 0; index < editTasks.length; index += 1) {
      const task = editTasks[index];
      let parsed: Record<string, unknown>;
      try {
        const value = JSON.parse(task.input || "{}");
        if (typeof value !== "object" || value === null || Array.isArray(value)) {
          throw new Error("Tool arguments must be a JSON object.");
        }
        parsed = value as Record<string, unknown>;
      } catch {
        setError(`Task ${index + 1} has invalid JSON tool arguments.`);
        return;
      }
      const dependencies = task.dependencies
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean)
        .map((item) => Number(item));
      if (dependencies.some((item) => !Number.isInteger(item))) {
        setError(`Task ${index + 1} has a non-numeric dependency.`);
        return;
      }
      tasks.push({
        title: task.title.trim() || `Step ${index + 1}`,
        description: task.description,
        task_type: task.task_type,
        expected_output: task.expected_output,
        input: parsed,
        dependencies,
      });
    }
    setBusy("save");
    setError(null);
    try {
      const plan = await updateAgentPlan(detail.plan_id, {
        title: editTitle.trim() || detail.title,
        description: editDescription,
        priority: editPriority,
        tasks,
      });
      setDetail(plan);
      setEditing(false);
      setNotice("Plan updated. Tool arguments are validated again before execution.");
      await refreshAll(plan.plan_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  const pendingApprovals = analytics?.pending_approvals ?? 0;
  const planCounts = useMemo(
    () => ({
      total: analytics?.total_plans ?? plans.length,
      ready: analytics?.plans_waiting_for_approval ?? 0,
    }),
    [analytics, plans.length],
  );

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.55fr)]">
      <div className="space-y-4">
        <Panel
          title="Plan an objective"
          description="The planner is deterministic: it maps each step to one allowlisted tool and never invents entities, sources or completed work."
        >
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1.5 block text-[11px] text-slate-400">Objective</span>
              <textarea
                value={objective}
                onChange={(event) => setObjective(event.target.value)}
                rows={4}
                maxLength={2000}
                placeholder="e.g. Prepare MNEMORA for deployment and list the remaining gaps."
                className="w-full resize-y rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2.5 text-xs leading-5 text-slate-100 outline-none placeholder:text-slate-600 focus:border-violet-300/40"
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-[11px] text-slate-400">Title (optional)</span>
                <input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  maxLength={200}
                  placeholder="Short plan title"
                  className="w-full rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2 text-xs text-slate-100 outline-none placeholder:text-slate-600 focus:border-violet-300/40"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[11px] text-slate-400">Priority</span>
                <select
                  value={priority}
                  onChange={(event) => setPriority(event.target.value)}
                  className="w-full rounded-xl border border-white/[0.08] bg-[#10131e] px-3 py-2 text-xs text-slate-100 outline-none focus:border-violet-300/40"
                >
                  <option value="low">Low</option>
                  <option value="normal">Normal</option>
                  <option value="high">High</option>
                  <option value="urgent">Urgent</option>
                </select>
              </label>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.015] p-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-400">Documents (optional, treated as untrusted data)</span>
                <button
                  type="button"
                  onClick={() => setDocuments((current) => (current.length >= 3 ? current : [...current, { name: "", text: "" }]))}
                  disabled={documents.length >= 3}
                  className="inline-flex items-center gap-1 text-[10px] text-violet-300 disabled:opacity-40"
                >
                  <Plus size={12} /> Add document
                </button>
              </div>
              {documents.length === 0 && (
                <p className="mt-2 text-[10px] leading-4 text-slate-600">
                  Up to three documents. Instruction-like text inside them is summarised as data and never executed.
                </p>
              )}
              <div className="mt-2 space-y-2">
                {documents.map((document, index) => (
                  <div key={index} className="rounded-lg border border-white/[0.06] p-2">
                    <div className="flex gap-2">
                      <input
                        value={document.name}
                        onChange={(event) =>
                          setDocuments((current) =>
                            current.map((item, position) =>
                              position === index ? { ...item, name: event.target.value } : item,
                            ),
                          )
                        }
                        placeholder={`notes-${index + 1}.txt`}
                        className="w-40 rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100 outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => setDocuments((current) => current.filter((_, position) => position !== index))}
                        className="ml-auto rounded-lg border border-white/[0.06] px-2 py-1 text-slate-500 hover:text-rose-200"
                        aria-label="Remove document"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                    <textarea
                      value={document.text}
                      onChange={(event) =>
                        setDocuments((current) =>
                          current.map((item, position) =>
                            position === index ? { ...item, text: event.target.value } : item,
                          ),
                        )
                      }
                      rows={3}
                      placeholder="Paste source text"
                      className="mt-2 w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] leading-5 text-slate-100 outline-none"
                    />
                  </div>
                ))}
              </div>
            </div>
            <button
              type="button"
              onClick={() => void submitCreate()}
              disabled={busy !== null}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-violet-300/25 bg-gradient-to-r from-violet-500/20 to-blue-500/10 px-3 py-2.5 text-xs font-medium text-violet-100 transition hover:border-violet-200/40 disabled:opacity-50"
            >
              {busy === "create" ? <LoaderCircle size={14} className="animate-spin" /> : <ClipboardList size={14} />}
              Create plan
            </button>
          </div>
        </Panel>

        <Panel
          title="Plans"
          description={`${planCounts.total} plan(s) — ${planCounts.ready} approved and waiting to run.`}
          action={
            <button type="button" onClick={() => void loadPlans()} className="rounded-lg p-1.5 text-slate-500 hover:text-violet-200" aria-label="Refresh plans">
              <RefreshCw size={14} />
            </button>
          }
        >
          <div className="mb-3 flex flex-wrap gap-1.5">
            {PLAN_FILTERS.map((item) => (
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
            <Spinner label="Loading plans…" />
          ) : plans.length === 0 ? (
            <EmptyState>No plans in this view. Create one above to get started.</EmptyState>
          ) : (
            <ul className="space-y-1.5">
              {plans.map((plan) => (
                <li key={plan.plan_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(plan.plan_id)}
                    className={cx(
                      "w-full rounded-xl border px-3 py-2.5 text-left transition",
                      selectedId === plan.plan_id
                        ? "border-violet-300/30 bg-violet-300/[0.07]"
                        : "border-white/[0.05] hover:border-white/[0.12] hover:bg-white/[0.02]",
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-slate-100">{plan.title}</p>
                        <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-500">{plan.objective}</p>
                      </div>
                      <StatusPill status={plan.status} />
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-600">
                      <span>{plan.intent}</span>
                      <span>•</span>
                      <span>{plan.task_count} steps</span>
                      <span>•</span>
                      <span>{plan.progress}% complete</span>
                      <ChevronRight size={12} className="ml-auto" />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="space-y-3">
        {error && <Alert tone="error">{error}</Alert>}
        {notice && <Alert tone="success">{notice}</Alert>}
        {pendingApprovals > 0 && (
          <Alert tone="info">
            {pendingApprovals} action(s) are waiting for approval. Sensitive tools never run without an explicit,
            single-use decision.
          </Alert>
        )}
        {detailLoading ? (
          <Panel><Spinner label="Loading plan details…" /></Panel>
        ) : !detail ? (
          <Panel>
            <EmptyState>Select a plan to review its steps, approve it and monitor execution.</EmptyState>
          </Panel>
        ) : (
          <>
            <Panel
              title={detail.title}
              description={detail.description}
              action={<StatusPill status={detail.status} />}
            >
              <div className="space-y-3">
                <ProgressBar value={detail.progress} label="Plan progress" definition="Completed steps ÷ total steps, from persisted task states." />
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <KeyValue label="Intent">{detail.intent}</KeyValue>
                  <KeyValue label="Priority">{detail.priority}</KeyValue>
                  <KeyValue label="Complexity">{detail.estimated_complexity}</KeyValue>
                  <KeyValue label="Source">{detail.source}</KeyValue>
                </dl>
                {detail.error && <Alert tone="error">{detail.error}</Alert>}
                {detail.warnings.length > 0 && (
                  <Alert tone="info">
                    <ul className="list-disc space-y-1 pl-4">
                      {detail.warnings.map((warning) => <li key={warning}>{warning}</li>)}
                    </ul>
                  </Alert>
                )}
                {detail.clarifications.length > 0 && (
                  <div className="rounded-xl border border-amber-300/20 bg-amber-300/[0.05] p-3">
                    <p className="text-[11px] font-medium text-amber-100">Clarification required</p>
                    <div className="mt-2 space-y-2">
                      {detail.clarifications.map((item) => (
                        <label key={item.id} className="block">
                          <span className="mb-1 block text-[10px] leading-4 text-amber-100/80">{item.question}</span>
                          {item.options && item.options.length > 0 ? (
                            <select
                              value={answers[item.id] ?? item.options[0]}
                              onChange={(event) => setAnswers((current) => ({ ...current, [item.id]: event.target.value }))}
                              className="w-full rounded-lg border border-white/[0.1] bg-[#10131e] px-2 py-1.5 text-[11px] text-slate-100"
                            >
                              {item.options.map((option) => <option key={option} value={option}>{option}</option>)}
                            </select>
                          ) : (
                            <input
                              value={answers[item.id] ?? ""}
                              onChange={(event) => setAnswers((current) => ({ ...current, [item.id]: event.target.value }))}
                              className="w-full rounded-lg border border-white/[0.1] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100"
                            />
                          )}
                        </label>
                      ))}
                    </div>
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  {["draft", "needs_clarification"].includes(detail.status) && (
                    <button
                      type="button"
                      onClick={() => void submitApproval()}
                      disabled={busy !== null}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300/25 bg-emerald-300/10 px-3 py-1.5 text-[11px] text-emerald-100 disabled:opacity-40"
                    >
                      <Check size={13} /> Approve plan
                    </button>
                  )}
                  {detail.status === "approved" && (
                    <button
                      type="button"
                      onClick={() => void submitExecute()}
                      disabled={busy !== null}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-violet-300/25 bg-violet-300/10 px-3 py-1.5 text-[11px] text-violet-100 disabled:opacity-40"
                    >
                      <Play size={13} /> Execute
                    </button>
                  )}
                  {planEditable(detail) && (
                    <button
                      type="button"
                      onClick={() => setEditing((current) => !current)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-3 py-1.5 text-[11px] text-slate-300"
                    >
                      <Pencil size={13} /> {editing ? "Close editor" : "Edit plan"}
                    </button>
                  )}
                  {detail.status !== "archived" && detail.status !== "running" && (
                    <button
                      type="button"
                      onClick={() => void submitArchive()}
                      disabled={busy !== null}
                      className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-white/[0.06] px-3 py-1.5 text-[11px] text-slate-500 hover:text-rose-200 disabled:opacity-40"
                    >
                      <X size={13} /> Archive
                    </button>
                  )}
                </div>
              </div>
            </Panel>

            {editing && (
              <Panel title="Edit plan" description="Task types map to fixed tools. Tool arguments are validated before execution; the backend rejects unknown tools and forward dependencies.">
                <div className="space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block">
                      <span className="mb-1 block text-[10px] text-slate-500">Title</span>
                      <input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-100" />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[10px] text-slate-500">Priority</span>
                      <select value={editPriority} onChange={(event) => setEditPriority(event.target.value)} className="w-full rounded-lg border border-white/[0.08] bg-[#10131e] px-2.5 py-1.5 text-[11px] text-slate-100">
                        <option value="low">Low</option>
                        <option value="normal">Normal</option>
                        <option value="high">High</option>
                        <option value="urgent">Urgent</option>
                      </select>
                    </label>
                  </div>
                  <label className="block">
                    <span className="mb-1 block text-[10px] text-slate-500">Description</span>
                    <textarea value={editDescription} onChange={(event) => setEditDescription(event.target.value)} rows={2} className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-100" />
                  </label>
                  <div className="space-y-2">
                    {editTasks.map((task, index) => (
                      <details key={index} className="rounded-xl border border-white/[0.06] bg-white/[0.015] p-3" open={index === 0}>
                        <summary className="cursor-pointer text-[11px] font-medium text-slate-200">
                          {index + 1}. {task.title || "Untitled task"}
                        </summary>
                        <div className="mt-2 space-y-2">
                          <div className="grid gap-2 sm:grid-cols-2">
                            <input value={task.title} onChange={(event) => setEditTasks((current) => current.map((item, position) => position === index ? { ...item, title: event.target.value } : item))} placeholder="Task title" className="rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
                            <select value={task.task_type} onChange={(event) => setEditTasks((current) => current.map((item, position) => position === index ? { ...item, task_type: event.target.value as AgentTaskType } : item))} className="rounded-lg border border-white/[0.08] bg-[#10131e] px-2 py-1.5 text-[11px] text-slate-100">
                              {AGENT_TASK_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label} ({item.tool})</option>)}
                            </select>
                          </div>
                          <input value={task.expected_output} onChange={(event) => setEditTasks((current) => current.map((item, position) => position === index ? { ...item, expected_output: event.target.value } : item))} placeholder="Expected output" className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
                          <div className="grid gap-2 sm:grid-cols-[1fr_140px]">
                            <textarea value={task.input} onChange={(event) => setEditTasks((current) => current.map((item, position) => position === index ? { ...item, input: event.target.value } : item))} rows={4} spellCheck={false} className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 font-mono text-[10px] leading-4 text-slate-200" />
                            <div>
                              <label className="block text-[10px] text-slate-500">Dependencies</label>
                              <input value={task.dependencies} onChange={(event) => setEditTasks((current) => current.map((item, position) => position === index ? { ...item, dependencies: event.target.value } : item))} placeholder="0, 1" className="mt-1 w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
                              <p className="mt-1 text-[9px] text-slate-600">Earlier step indexes only.</p>
                            </div>
                          </div>
                        </div>
                      </details>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <button type="button" onClick={() => void submitEdit()} disabled={busy !== null} className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300/25 bg-emerald-300/10 px-3 py-1.5 text-[11px] text-emerald-100 disabled:opacity-40">
                      <Save size={13} /> Save changes
                    </button>
                    <button type="button" onClick={() => setEditing(false)} className="rounded-lg border border-white/[0.08] px-3 py-1.5 text-[11px] text-slate-400">Cancel</button>
                  </div>
                </div>
              </Panel>
            )}

            <Panel title="Steps" description={`${detail.completed_count} of ${detail.task_count} steps completed. Unfinished steps never claim success."`}>
              <ol className="space-y-2">
                {detail.tasks.map((task) => (
                  <li key={task.task_id} className="rounded-xl border border-white/[0.06] bg-white/[0.015] p-3">
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border border-white/10 text-[10px] text-slate-400">{task.sequence + 1}</span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[11px] font-medium text-slate-100">{task.title}</p>
                        <p className="mt-0.5 text-[10px] leading-4 text-slate-500">{task.description}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[9px] text-slate-600">
                          <span className="rounded border border-white/[0.06] px-1.5 py-0.5">{task.task_type}</span>
                          <span className="rounded border border-white/[0.06] px-1.5 py-0.5">{task.assigned_tool ?? "no tool"}</span>
                          {task.dependencies.length > 0 && <span>after {task.dependencies.map((item) => item + 1).join(", ")}</span>}
                          {task.approval_required && <span className="text-amber-300/80">approval required</span>}
                          {task.execution_attempts > 0 && <span>attempts {task.execution_attempts}/{task.max_attempts}</span>}
                        </div>
                        {task.error && <p className="mt-1.5 rounded-lg border border-rose-300/15 bg-rose-300/[0.05] px-2 py-1 text-[10px] leading-4 text-rose-200">{task.error}</p>}
                        {taskSummary(task) && <p className="mt-1.5 text-[10px] leading-4 text-slate-400">{taskSummary(task)}</p>}
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <StatusPill status={task.status} />
                        <StatusPill status={task.verification_status} />
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            </Panel>

            <Panel title="Context used" description="Only approved memories, confirmed preferences and stored graph edges are assembled. Nothing here is invented.">
              <pre className="max-h-64 overflow-auto rounded-xl border border-white/[0.06] bg-black/25 p-3 text-[10px] leading-5 text-slate-400">
                {JSON.stringify(detail.context, null, 2)}
              </pre>
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  Blocks,
  Copy,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Wrench,
} from "lucide-react";
import {
  AGENT_TASK_TYPES,
  createAgentWorkflow,
  deleteAgentWorkflow,
  duplicateAgentWorkflow,
  executeAgentWorkflow,
  listAgentTools,
  listAgentWorkflows,
  updateAgentWorkflow,
  type AgentTool,
  type AgentWorkflow,
  type AgentTaskType,
} from "@/lib/agents";
import { ApiError } from "@/lib/api";
import { Alert, EmptyState, Panel, Spinner, StatusPill, cx, formatDateTime } from "@/components/agents/ui";

type Props = {
  onChanged: () => void;
  onOpenExecution: (executionId: string) => void;
};

const WORKFLOW_FILTERS = [
  { value: "", label: "All" },
  { value: "active", label: "Active" },
  { value: "suggested", label: "Suggested" },
  { value: "archived", label: "Archived" },
];

type StepDraft = {
  title: string;
  task_type: AgentTaskType;
  expected_output: string;
  input: string;
  dependencies: string;
};

const EMPTY_STEP: StepDraft = {
  title: "",
  task_type: "retrieve_memory",
  expected_output: "",
  input: "{}",
  dependencies: "",
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function stepToJson(step: StepDraft, index: number) {
  let input: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(step.input || "{}");
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("input must be an object");
    }
    input = parsed as Record<string, unknown>;
  } catch {
    throw new Error(`Step ${index + 1}: tool arguments must be a JSON object.`);
  }
  const dependencies = step.dependencies
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number(item));
  if (dependencies.some((item) => !Number.isInteger(item) || item < 0 || item >= index)) {
    throw new Error(`Step ${index + 1}: dependencies must be earlier step indexes.`);
  }
  return {
    title: step.title.trim() || `Step ${index + 1}`,
    task_type: step.task_type,
    expected_output: step.expected_output.trim(),
    input,
    dependencies,
  };
}

export default function CatalogPanel({ onChanged, onOpenExecution }: Props) {
  const [tools, setTools] = useState<AgentTool[]>([]);
  const [workflows, setWorkflows] = useState<AgentWorkflow[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [objectiveTemplate, setObjectiveTemplate] = useState("");
  const [intent, setIntent] = useState("generic");
  const [steps, setSteps] = useState<StepDraft[]>([{ ...EMPTY_STEP }]);
  const [objectiveInputs, setObjectiveInputs] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [toolRows, workflowRows] = await Promise.all([
        listAgentTools(),
        listAgentWorkflows({ status: filter || undefined }),
      ]);
      setTools(toolRows);
      setWorkflows(workflowRows);
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const enabledCount = useMemo(() => tools.filter((tool) => tool.enabled).length, [tools]);

  async function createWorkflow() {
    setError(null);
    setNotice(null);
    if (!name.trim()) {
      setError("Give the workflow a name.");
      return;
    }
    let payloadSteps;
    try {
      payloadSteps = steps.map((step, index) => stepToJson(step, index));
    } catch (caught) {
      setError(errorMessage(caught));
      return;
    }
    setBusy("create");
    try {
      const workflow = await createAgentWorkflow({
        name: name.trim(),
        description: description.trim(),
        objective_template: objectiveTemplate.trim(),
        intent: intent.trim() || "generic",
        steps: payloadSteps,
      });
      setNotice(`Workflow "${workflow.name}" created. Executing it creates a plan you review and approve.`);
      setName("");
      setDescription("");
      setObjectiveTemplate("");
      setIntent("generic");
      setSteps([{ ...EMPTY_STEP }]);
      setCreating(false);
      await load();
      onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function execute(workflow: AgentWorkflow) {
    setBusy(workflow.workflow_id);
    setError(null);
    setNotice(null);
    try {
      const objective = (objectiveInputs[workflow.workflow_id] || "").trim() || workflow.objective_template || undefined;
      const execution = await executeAgentWorkflow(workflow.workflow_id, objective);
      setNotice(
        execution.status === "awaiting_approval"
          ? "Workflow started and paused for an approval. Open the execution to decide."
          : `Workflow finished with status: ${execution.status}.`,
      );
      await load();
      onChanged();
      onOpenExecution(execution.execution_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function duplicate(workflow: AgentWorkflow) {
    setBusy(workflow.workflow_id);
    setError(null);
    try {
      const copy = await duplicateAgentWorkflow(workflow.workflow_id);
      setNotice(`Duplicated as "${copy.name}". Edit it from the workflow list.`);
      await load();
      onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function toggleArchive(workflow: AgentWorkflow) {
    setBusy(workflow.workflow_id);
    setError(null);
    try {
      const next = workflow.status === "archived" ? "active" : "archived";
      await updateAgentWorkflow(workflow.workflow_id, { status: next });
      setNotice(next === "archived" ? "Workflow archived. It can no longer be executed." : "Workflow restored.");
      await load();
      onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function remove(workflow: AgentWorkflow) {
    setBusy(workflow.workflow_id);
    setError(null);
    try {
      await deleteAgentWorkflow(workflow.workflow_id);
      setNotice(`Workflow "${workflow.name}" deleted.`);
      await load();
      onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <Panel
          title="Tool registry"
          description={`${enabledCount} of ${tools.length} allowlisted tools are currently available. Task types map to exactly one tool; there is no free-form tool choice and no shell or database access.`}
          action={
            <button type="button" onClick={() => void load()} className="rounded-lg p-1.5 text-slate-500 hover:text-violet-200" aria-label="Refresh tools">
              <RefreshCw size={14} />
            </button>
          }
        >
          {loading ? (
            <Spinner label="Loading tools…" />
          ) : (
            <ul className="space-y-1.5">
              {tools.map((tool) => (
                <li key={tool.tool_name} className="rounded-xl border border-white/[0.06] bg-white/[0.015] p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="flex items-center gap-1.5 text-[11px] font-medium text-slate-100">
                        <Wrench size={11} className="text-violet-300" /> {tool.tool_name}
                      </p>
                      <p className="mt-1 text-[10px] leading-4 text-slate-500">{tool.description}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <StatusPill status={tool.enabled ? "active" : "disabled"} />
                      {tool.approval_required && <StatusPill status="awaiting_approval" />}
                    </div>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5 text-[9px] text-slate-600">
                    <span className="rounded border border-white/[0.06] px-1.5 py-0.5">{tool.permission}</span>
                    <span className="rounded border border-white/[0.06] px-1.5 py-0.5">{tool.category}</span>
                    <span className="rounded border border-white/[0.06] px-1.5 py-0.5">
                      {tool.side_effects ? "side effects" : "read only"}
                    </span>
                    <span className="rounded border border-white/[0.06] px-1.5 py-0.5">
                      {tool.stats.success} ok / {tool.stats.failure} failed
                    </span>
                  </div>
                  {!tool.enabled && tool.disabled_reason && (
                    <p className="mt-1.5 text-[10px] leading-4 text-amber-200/80">{tool.disabled_reason}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          title="Reusable workflows"
          description="Builtin workflows are seeded per user and cannot be deleted. Learned workflows arrive as suggestions; executing one always creates a plan you can inspect."
          action={
            <button
              type="button"
              onClick={() => setCreating((current) => !current)}
              className="inline-flex items-center gap-1 rounded-lg border border-violet-300/25 bg-violet-300/10 px-2.5 py-1.5 text-[10px] text-violet-100"
            >
              <Plus size={12} /> New workflow
            </button>
          }
        >
          {creating && (
            <div className="mb-3 space-y-2 rounded-xl border border-violet-300/20 bg-violet-300/[0.03] p-3">
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-[10px] text-slate-500">Name</span>
                  <input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
                </label>
                <label className="block">
                  <span className="mb-1 block text-[10px] text-slate-500">Intent</span>
                  <input value={intent} onChange={(event) => setIntent(event.target.value)} maxLength={40} className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
                </label>
              </div>
              <label className="block">
                <span className="mb-1 block text-[10px] text-slate-500">Description</span>
                <input value={description} onChange={(event) => setDescription(event.target.value)} maxLength={500} className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
              </label>
              <label className="block">
                <span className="mb-1 block text-[10px] text-slate-500">Objective template</span>
                <input value={objectiveTemplate} onChange={(event) => setObjectiveTemplate(event.target.value)} maxLength={2000} placeholder="Used when no objective is supplied at execution time." className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
              </label>
              <div className="space-y-2">
                {steps.map((step, index) => (
                  <div key={index} className="rounded-lg border border-white/[0.07] bg-black/20 p-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-slate-400">Step {index + 1}</span>
                      <button
                        type="button"
                        onClick={() => setSteps((current) => current.filter((_, position) => position !== index))}
                        disabled={steps.length === 1}
                        className="text-slate-500 hover:text-rose-200 disabled:opacity-30"
                        aria-label="Remove step"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                    <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
                      <input value={step.title} onChange={(event) => setSteps((current) => current.map((item, position) => (position === index ? { ...item, title: event.target.value } : item)))} placeholder="Step title" className="rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
                      <select value={step.task_type} onChange={(event) => setSteps((current) => current.map((item, position) => (position === index ? { ...item, task_type: event.target.value as AgentTaskType } : item)))} className="rounded-lg border border-white/[0.08] bg-[#10131e] px-2 py-1.5 text-[11px] text-slate-100">
                        {AGENT_TASK_TYPES.map((item) => (
                          <option key={item.value} value={item.value}>{item.label} ({item.tool})</option>
                        ))}
                      </select>
                    </div>
                    <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_120px]">
                      <textarea value={step.input} onChange={(event) => setSteps((current) => current.map((item, position) => (position === index ? { ...item, input: event.target.value } : item)))} rows={3} spellCheck={false} placeholder='{"query": "..."}' className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 font-mono text-[10px] leading-4 text-slate-200" />
                      <div>
                        <input value={step.dependencies} onChange={(event) => setSteps((current) => current.map((item, position) => (position === index ? { ...item, dependencies: event.target.value } : item)))} placeholder="Dependencies" className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
                        <input value={step.expected_output} onChange={(event) => setSteps((current) => current.map((item, position) => (position === index ? { ...item, expected_output: event.target.value } : item)))} placeholder="Expected output" className="mt-2 w-full rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[11px] text-slate-100" />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => setSteps((current) => [...current, { ...EMPTY_STEP }])} disabled={steps.length >= 20} className="inline-flex items-center gap-1 rounded-lg border border-white/[0.08] px-2.5 py-1.5 text-[10px] text-slate-300 disabled:opacity-40">
                  <Plus size={11} /> Add step
                </button>
                <button type="button" onClick={() => void createWorkflow()} disabled={busy !== null} className="inline-flex items-center gap-1 rounded-lg border border-emerald-300/25 bg-emerald-300/10 px-2.5 py-1.5 text-[10px] text-emerald-100 disabled:opacity-40">
                  {busy === "create" ? <LoaderCircle size={11} className="animate-spin" /> : <Blocks size={11} />} Create workflow
                </button>
              </div>
            </div>
          )}

          <div className="mb-3 flex flex-wrap gap-1.5">
            {WORKFLOW_FILTERS.map((item) => (
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
            <Spinner label="Loading workflows…" />
          ) : workflows.length === 0 ? (
            <EmptyState>No workflows in this view.</EmptyState>
          ) : (
            <ul className="space-y-2">
              {workflows.map((workflow) => (
                <li key={workflow.workflow_id} className="rounded-xl border border-white/[0.06] bg-white/[0.015] p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[11px] font-medium text-slate-100">{workflow.name}</p>
                      <p className="mt-1 text-[10px] leading-4 text-slate-500">{workflow.description}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <StatusPill status={workflow.status} />
                      <span className="text-[9px] text-slate-600">{workflow.source}</span>
                    </div>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5 text-[9px] text-slate-600">
                    <span className="rounded border border-white/[0.06] px-1.5 py-0.5">{workflow.steps.length} steps</span>
                    <span className="rounded border border-white/[0.06] px-1.5 py-0.5">{workflow.intent}</span>
                    <span className="rounded border border-white/[0.06] px-1.5 py-0.5">
                      {workflow.success_count} ok / {workflow.failure_count} failed
                    </span>
                    {workflow.last_executed_at && (
                      <span className="rounded border border-white/[0.06] px-1.5 py-0.5">
                        last run {formatDateTime(workflow.last_executed_at)}
                      </span>
                    )}
                  </div>
                  {!workflow.available && (
                    <p className="mt-1.5 text-[10px] leading-4 text-amber-200/80">
                      Needs unconfigured tool(s): {workflow.missing_tools.join(", ") || "unknown"}
                    </p>
                  )}
                  <details className="mt-1.5">
                    <summary className="cursor-pointer text-[9px] text-slate-500">Steps</summary>
                    <pre className="mt-1 max-h-44 overflow-auto rounded-lg bg-black/25 p-2 text-[9px] leading-4 text-slate-400">
                      {JSON.stringify(workflow.steps, null, 2)}
                    </pre>
                  </details>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {workflow.status !== "archived" && (
                      <>
                        <input
                          value={objectiveInputs[workflow.workflow_id] ?? ""}
                          onChange={(event) => setObjectiveInputs((current) => ({ ...current, [workflow.workflow_id]: event.target.value }))}
                          placeholder={workflow.objective_template || "Optional objective override"}
                          maxLength={2000}
                          className="min-w-0 flex-1 rounded-lg border border-white/[0.08] bg-black/20 px-2 py-1.5 text-[10px] text-slate-100"
                        />
                        <button
                          type="button"
                          onClick={() => void execute(workflow)}
                          disabled={busy !== null || !workflow.available}
                          className="inline-flex items-center gap-1 rounded-lg border border-violet-300/25 bg-violet-300/10 px-2.5 py-1.5 text-[10px] text-violet-100 disabled:opacity-40"
                        >
                          {busy === workflow.workflow_id ? <LoaderCircle size={11} className="animate-spin" /> : <Play size={11} />} Execute
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      onClick={() => void duplicate(workflow)}
                      disabled={busy !== null}
                      className="inline-flex items-center gap-1 rounded-lg border border-white/[0.08] px-2 py-1.5 text-[10px] text-slate-300 disabled:opacity-40"
                    >
                      <Copy size={11} /> Duplicate
                    </button>
                    <button
                      type="button"
                      onClick={() => void toggleArchive(workflow)}
                      disabled={busy !== null}
                      className="inline-flex items-center gap-1 rounded-lg border border-white/[0.08] px-2 py-1.5 text-[10px] text-slate-300 disabled:opacity-40"
                    >
                      {workflow.status === "archived" ? <ArchiveRestore size={11} /> : <Archive size={11} />}
                      {workflow.status === "archived" ? "Restore" : "Archive"}
                    </button>
                    {workflow.editable && (
                      <button
                        type="button"
                        onClick={() => void remove(workflow)}
                        disabled={busy !== null}
                        className="inline-flex items-center gap-1 rounded-lg border border-rose-300/20 px-2 py-1.5 text-[10px] text-rose-200 disabled:opacity-40"
                      >
                        <Trash2 size={11} /> Delete
                      </button>
                    )}
                  </div>
                  {workflow.status === "suggested" && (
                    <p className="mt-1.5 flex items-center gap-1 text-[9px] text-sky-200/70">
                      <ShieldCheck size={9} /> Learned from a verified execution — review before relying on it.
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

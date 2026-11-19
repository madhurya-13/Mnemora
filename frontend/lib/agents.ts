import { requestJson } from "@/lib/api";

export type AgentTaskType =
  | "retrieve_memory"
  | "retrieve_preferences"
  | "retrieve_graph"
  | "analyze_project"
  | "analyze_document"
  | "analyze_memories"
  | "research"
  | "calculate"
  | "generate_report"
  | "propose_memory";

export const AGENT_TASK_TYPES: { value: AgentTaskType; label: string; tool: string }[] = [
  { value: "retrieve_memory", label: "Retrieve memories", tool: "memory_search" },
  { value: "retrieve_preferences", label: "Retrieve preferences", tool: "preference_lookup" },
  { value: "retrieve_graph", label: "Retrieve graph context", tool: "knowledge_graph_search" },
  { value: "analyze_project", label: "Inspect repository", tool: "project_analysis" },
  { value: "analyze_document", label: "Analyse documents", tool: "document_analysis" },
  { value: "analyze_memories", label: "Audit memories", tool: "memory_audit" },
  { value: "research", label: "Web research", tool: "web_research" },
  { value: "calculate", label: "Calculate", tool: "calculator" },
  { value: "generate_report", label: "Generate report", tool: "report_generation" },
  { value: "propose_memory", label: "Propose memory", tool: "memory_proposal" },
];

export type AgentPlanStatus =
  | "draft"
  | "needs_clarification"
  | "approved"
  | "running"
  | "completed"
  | "partially_completed"
  | "failed"
  | "cancelled"
  | "archived";

export type AgentExecutionStatus =
  | "created"
  | "planning"
  | "awaiting_approval"
  | "executing"
  | "paused"
  | "completed"
  | "partially_completed"
  | "failed"
  | "cancelled";

export type AgentTaskStatus =
  | "pending"
  | "ready"
  | "awaiting_approval"
  | "running"
  | "completed"
  | "failed"
  | "skipped"
  | "cancelled";

export type AgentVerificationStatus =
  | "pending"
  | "verified"
  | "partially_verified"
  | "failed"
  | "not_verifiable";

export type AgentApproval = {
  approval_id: string;
  execution_id: string;
  task_id: string;
  tool_name: string;
  action_summary: string;
  reason: string;
  expected_impact: string;
  data_involved: string[];
  reversible: boolean;
  parameters: Record<string, unknown>;
  parameters_hash: string;
  status: "pending" | "approved" | "rejected" | "expired" | "consumed";
  decision_note: string | null;
  expires_at: string | null;
  decided_at: string | null;
  created_at: string | null;
  expired: boolean;
};

export type AgentVerification = {
  verification_id: string;
  execution_id: string;
  task_id: string;
  verification_type: string;
  expected_result: string;
  observed_result: string;
  status: AgentVerificationStatus;
  evidence: string[];
  verified_at: string | null;
};

export type AgentTask = {
  task_id: string;
  plan_id: string;
  sequence: number;
  title: string;
  description: string;
  task_type: AgentTaskType;
  assigned_tool: string | null;
  dependencies: number[];
  input: Record<string, unknown>;
  expected_output: string;
  status: AgentTaskStatus;
  approval_required: boolean;
  approval_policy: string;
  execution_attempts: number;
  max_attempts: number;
  result: Record<string, unknown> | null;
  error: string | null;
  verification_status: AgentVerificationStatus;
  verified_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  approval: AgentApproval | null;
  verifications: AgentVerification[];
};

export type AgentClarification = {
  id: string;
  question: string;
  options?: string[];
};

export type AgentPlan = {
  plan_id: string;
  workflow_id: string | null;
  title: string;
  objective: string;
  description: string;
  intent: string;
  priority: string;
  estimated_complexity: string;
  status: AgentPlanStatus;
  source: string;
  context: Record<string, unknown>;
  clarifications: AgentClarification[];
  clarification_answers: { id: string; answer: string }[];
  warnings: string[];
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
  task_count: number;
  completed_count: number;
  progress: number;
  tasks: AgentTask[];
};

export type AgentExecution = {
  execution_id: string;
  plan_id: string;
  workflow_id: string | null;
  status: AgentExecutionStatus;
  progress: number;
  progress_definition: string;
  current_task_id: string | null;
  error: string | null;
  cancel_requested: boolean;
  learning: Record<string, unknown>;
  context: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
  last_heartbeat_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  plan_title: string | null;
  plan_status: string | null;
  plan: AgentPlan | null;
  task_counts: {
    total: number;
    completed: number;
    failed: number;
    pending: number;
    awaiting_approval: number;
  };
  tasks: AgentTask[];
  current_task: AgentTask | null;
};

export type AgentEvent = {
  event_id: string;
  execution_id: string;
  task_id: string | null;
  event_type: string;
  message: string;
  payload: Record<string, unknown>;
  sequence: number;
  created_at: string | null;
};

export type AgentInvocation = {
  invocation_id: string;
  tool_name: string;
  status: string;
  attempts: number;
  duration_ms: number;
  error: string | null;
  task_id: string | null;
  created_at: string | null;
  arguments_preview: Record<string, unknown>;
  output_preview: Record<string, unknown>;
};

export type AgentTool = {
  tool_name: string;
  description: string;
  category: string;
  permission: string;
  side_effects: boolean;
  approval_required: boolean;
  enabled: boolean;
  disabled_reason: string | null;
  timeout_seconds: number;
  max_attempts: number;
  fallback: string | null;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  stats: {
    success: number;
    failure: number;
    last_invoked_at: string | null;
    recent_invocations: AgentInvocation[];
  };
};

export type AgentWorkflow = {
  workflow_id: string;
  name: string;
  description: string;
  objective_template: string;
  intent: string;
  steps: {
    title: string;
    description?: string;
    task_type: AgentTaskType;
    assigned_tool?: string;
    expected_output?: string;
    input?: Record<string, unknown>;
    dependencies?: number[];
  }[];
  status: "suggested" | "active" | "archived";
  source: string;
  success_count: number;
  failure_count: number;
  last_executed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  last_execution: {
    execution_id: string;
    status: AgentExecutionStatus;
    progress: number;
    created_at: string | null;
  } | null;
  available: boolean;
  missing_tools: string[];
  editable: boolean;
};

export type AgentAnalytics = {
  total_executions: number;
  active_executions: number;
  completed_executions: number;
  failed_executions: number;
  cancelled_executions: number;
  terminal_executions: number;
  success_rate_percent: number | null;
  success_rate_definition: string;
  total_plans: number;
  plans_waiting_for_approval: number;
  pending_approvals: number;
  workflow_count: number;
  suggested_workflows: number;
  verified_tasks: number;
  partially_verified_tasks: number;
  failed_verifications: number;
  tool_usage: { tool_name: string; success: number; failure: number }[];
  recent_tasks: {
    task_id: string;
    plan_id: string;
    plan_title: string | null;
    title: string;
    status: AgentTaskStatus;
    verification_status: AgentVerificationStatus;
    assigned_tool: string | null;
    updated_at: string | null;
  }[];
  recent_events: AgentEvent[];
};

export type AgentPage<T> = { items: T[]; total: number };

type QueryValue = string | number | boolean | undefined;

function queryString(params: Record<string, QueryValue> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  return search.toString();
}

export type PlanDocument = { name: string; text: string };

export type PlanTaskInput = {
  title: string;
  description?: string;
  task_type: AgentTaskType;
  expected_output?: string;
  input?: Record<string, unknown>;
  dependencies?: number[];
};

export const getAgentAnalytics = () => requestJson<AgentAnalytics>("/api/v1/agents/analytics");

export const listAgentPlans = (params: { status?: string; limit?: number; offset?: number } = {}) =>
  requestJson<AgentPage<AgentPlan>>(`/api/v1/agents/plans?${queryString(params)}`);

export const getAgentPlan = (planId: string) =>
  requestJson<AgentPlan>(`/api/v1/agents/plans/${encodeURIComponent(planId)}`);

export const createAgentPlan = (input: {
  objective: string;
  title?: string;
  priority?: string;
  documents?: PlanDocument[];
}) =>
  requestJson<AgentPlan>("/api/v1/agents/plan", {
    method: "POST",
    body: JSON.stringify(input),
  });

export const updateAgentPlan = (
  planId: string,
  input: {
    title?: string;
    description?: string;
    priority?: string;
    tasks?: PlanTaskInput[];
  },
) =>
  requestJson<AgentPlan>(`/api/v1/agents/plans/${encodeURIComponent(planId)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });

export const approveAgentPlan = (planId: string, answers: { id: string; answer: string }[] = []) =>
  requestJson<AgentPlan>(`/api/v1/agents/plans/${encodeURIComponent(planId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });

export const archiveAgentPlan = (planId: string) =>
  requestJson<AgentPlan>(`/api/v1/agents/plans/${encodeURIComponent(planId)}`, {
    method: "DELETE",
  });

export const executeAgentPlan = (planId: string) =>
  requestJson<AgentExecution>("/api/v1/agents/execute", {
    method: "POST",
    body: JSON.stringify({ plan_id: planId }),
  });

export const listAgentExecutions = (
  params: { status?: string; limit?: number; offset?: number } = {},
) => requestJson<AgentPage<AgentExecution>>(`/api/v1/agents/executions?${queryString(params)}`);

export const getAgentExecution = (executionId: string) =>
  requestJson<AgentExecution>(`/api/v1/agents/executions/${encodeURIComponent(executionId)}`);

export const pauseAgentExecution = (executionId: string) =>
  requestJson<AgentExecution>(`/api/v1/agents/executions/${encodeURIComponent(executionId)}/pause`, {
    method: "POST",
  });

export const resumeAgentExecution = (executionId: string) =>
  requestJson<AgentExecution>(`/api/v1/agents/executions/${encodeURIComponent(executionId)}/resume`, {
    method: "POST",
  });

export const cancelAgentExecution = (executionId: string) =>
  requestJson<AgentExecution>(`/api/v1/agents/executions/${encodeURIComponent(executionId)}/cancel`, {
    method: "POST",
  });

export const listAgentEvents = (executionId: string) =>
  requestJson<AgentPage<AgentEvent>>(
    `/api/v1/agents/executions/${encodeURIComponent(executionId)}/events?limit=300`,
  );

export const listAgentVerifications = (executionId: string) =>
  requestJson<AgentPage<AgentVerification>>(
    `/api/v1/agents/executions/${encodeURIComponent(executionId)}/verification`,
  );

export const listAgentInvocations = (executionId: string) =>
  requestJson<AgentInvocation[]>(
    `/api/v1/agents/executions/${encodeURIComponent(executionId)}/invocations?limit=200`,
  );

export const listAgentTools = () => requestJson<AgentTool[]>("/api/v1/agents/tools");

export const listAgentApprovals = (
  params: { status?: string; limit?: number; offset?: number } = {},
) => requestJson<AgentPage<AgentApproval>>(`/api/v1/agents/approvals?${queryString(params)}`);

export const approveAgentAction = (approvalId: string, note?: string) =>
  requestJson<AgentApproval>(`/api/v1/agents/approvals/${encodeURIComponent(approvalId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ note: note || null }),
  });

export const rejectAgentAction = (approvalId: string, note?: string) =>
  requestJson<AgentApproval>(`/api/v1/agents/approvals/${encodeURIComponent(approvalId)}/reject`, {
    method: "POST",
    body: JSON.stringify({ note: note || null }),
  });

export const listAgentWorkflows = (params: { status?: string } = {}) =>
  requestJson<AgentWorkflow[]>(`/api/v1/agents/workflows?${queryString(params)}`);

export const createAgentWorkflow = (input: {
  name: string;
  description?: string;
  objective_template?: string;
  intent?: string;
  steps: {
    title: string;
    description?: string;
    task_type: AgentTaskType;
    expected_output?: string;
    input?: Record<string, unknown>;
    dependencies?: number[];
  }[];
  status?: "active" | "suggested" | "archived";
}) =>
  requestJson<AgentWorkflow>("/api/v1/agents/workflows", {
    method: "POST",
    body: JSON.stringify(input),
  });

export const updateAgentWorkflow = (
  workflowId: string,
  input: {
    name?: string;
    description?: string;
    objective_template?: string;
    intent?: string;
    steps?: {
      title: string;
      description?: string;
      task_type: AgentTaskType;
      expected_output?: string;
      input?: Record<string, unknown>;
      dependencies?: number[];
    }[];
    status?: "active" | "suggested" | "archived";
  },
) =>
  requestJson<AgentWorkflow>(`/api/v1/agents/workflows/${encodeURIComponent(workflowId)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });

export const duplicateAgentWorkflow = (workflowId: string, name?: string) =>
  requestJson<AgentWorkflow>(
    `/api/v1/agents/workflows/${encodeURIComponent(workflowId)}/duplicate`,
    { method: "POST", body: JSON.stringify({ name: name || null }) },
  );

export const deleteAgentWorkflow = (workflowId: string) =>
  requestJson<void>(`/api/v1/agents/workflows/${encodeURIComponent(workflowId)}`, {
    method: "DELETE",
  });

export const executeAgentWorkflow = (workflowId: string, objective?: string) =>
  requestJson<AgentExecution>(
    `/api/v1/agents/workflows/${encodeURIComponent(workflowId)}/execute`,
    { method: "POST", body: JSON.stringify({ objective: objective || null }) },
  );

export const AGENT_ACTIVE_STATUSES: AgentExecutionStatus[] = [
  "created",
  "planning",
  "executing",
  "awaiting_approval",
  "paused",
];

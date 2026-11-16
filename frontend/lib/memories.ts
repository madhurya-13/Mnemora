import { requestJson } from "@/lib/api";

export type MemoryCategory = "personal" | "education" | "career" | "interests" | "preferences" | "projects" | "goals" | "temporary" | "other";
export type Memory = {
  memory_id: string;
  content: string;
  category: MemoryCategory;
  importance: number;
  confidence: number;
  memory_type: "stable" | "temporary";
  source: string;
  source_conversation_id: string | null;
  source_message_ids: string[];
  approval_status: "pending" | "approved" | "rejected";
  lifecycle_status: "active" | "possibly_outdated" | "superseded" | "expired" | "archived" | "pending_review";
  utility_score: number;
  last_evaluated_at: string | null;
  similar_memory_id: string | null;
  vector_sync_status: "not_required" | "pending" | "synced" | "failed";
  created_at: string;
  updated_at: string;
  last_accessed_at: string | null;
  expires_at: string | null;
};
export type MemoryPage = { items: Memory[]; total: number; limit: number; offset: number };
export type MemoryStats = {
  total: number;
  approved: number;
  pending: number;
  rejected: number;
  vector_sync_pending: number;
  extraction_jobs_pending: number;
  extraction_jobs_failed: number;
  semantic_search_available: boolean;
  vector_index_available: boolean;
  automatic_save_enabled: boolean;
  categories: Record<string, number>;
  recently_updated: Memory[];
};
export type MemorySearchResult = { memory: Memory; similarity: number; relevance: number; keyword_score: number; recency_score: number; retrieval_reason: string; score_components: Record<string, number> };
export type MemorySearchResponse = { query: string; results: MemorySearchResult[] };
export type MemoryConflict = { conflict_id: string; conflict_type: string; status: string; summary: string; resolution: string | null; created_at: string; resolved_at: string | null; existing_memory: Memory; new_memory: Memory };
export type RetrievalStats = { retrieval_count: number; selected_count: number; excluded_count: number; average_latency_ms: number; recently_retrieved: Memory[]; recently_accessed: Memory[]; high_importance: Memory[]; category_distribution: Record<string, number>; recent_events: { event_id: string; intent: string; query_type: string; category: string | null; candidate_count: number; selected_count: number; excluded_count: number; latency_ms: number; created_at: string }[] };

export const listMemories = (params: { limit?: number; offset?: number; category?: string; approval_status?: string } = {}) => {
  const query = new URLSearchParams({ limit: String(params.limit ?? 50), offset: String(params.offset ?? 0), sort_by: "updated_at", sort_order: "desc" });
  if (params.category) query.set("category", params.category);
  if (params.approval_status) query.set("approval_status", params.approval_status);
  return requestJson<MemoryPage>(`/api/v1/memories?${query.toString()}`);
};
export const getMemoryStats = () => requestJson<MemoryStats>("/api/v1/memories/stats");
export const createMemory = (input: Pick<Memory, "content" | "category" | "importance" | "confidence" | "memory_type">) => requestJson<Memory>("/api/v1/memories", {
  method: "POST", body: JSON.stringify({ ...input, explicit: true, source_message_ids: [] }),
});
export const updateMemory = (id: string, input: Partial<Pick<Memory, "content" | "category" | "importance" | "confidence" | "memory_type">>) => requestJson<Memory>(`/api/v1/memories/${encodeURIComponent(id)}`, {
  method: "PUT", body: JSON.stringify(input),
});
export const approveMemory = (id: string) => requestJson<Memory>(`/api/v1/memories/${encodeURIComponent(id)}/approve`, { method: "POST" });
export const rejectMemory = (id: string) => requestJson<Memory>(`/api/v1/memories/${encodeURIComponent(id)}/reject`, { method: "POST" });
export const deleteMemory = (id: string) => requestJson<{ deleted: boolean; vector_cleanup_pending: boolean }>(`/api/v1/memories/${encodeURIComponent(id)}`, { method: "DELETE" });
export const searchMemories = (query: string, filters: { category?: string; min_importance?: number; date_from?: string; date_to?: string; sort_by?: string } = {}) => requestJson<MemorySearchResponse>("/api/v1/memories/search", {
  method: "POST", body: JSON.stringify({ query, top_k: 5, ...filters }),
});
export const getMemoryConflicts = () => requestJson<{ items: MemoryConflict[]; total: number }>("/api/v1/memories/conflicts");
export const resolveMemoryConflict = (id: string, resolution: "keep_existing" | "accept_update") => requestJson<MemoryConflict>(`/api/v1/memories/conflicts/${encodeURIComponent(id)}/resolve`, { method: "POST", body: JSON.stringify({ resolution }) });
export const getRetrievalStats = () => requestJson<RetrievalStats>("/api/v1/memories/retrieval-stats");
export const getMemoryHistory = (id: string) => requestJson<{ history_id: string; content: string; change_reason: string; change_type: string; source_conversation_id: string | null; created_at: string }[]>(`/api/v1/memories/${encodeURIComponent(id)}/history`);

// --- Milestone 7: adaptive memory -------------------------------------------------

export type PreferenceCategory =
  | "communication_style" | "learning_style" | "programming" | "technology"
  | "project_workflow" | "ui_ux" | "content" | "other";
export type Preference = {
  preference_id: string;
  category: PreferenceCategory;
  description: string;
  normalized_key: string;
  confidence: number;
  evidence_count: number;
  supporting_memory_ids: string[];
  evidence: { message_id: string | null; conversation_id: string | null; excerpt: string; observed_at: string }[];
  status: "candidate" | "confirmed" | "rejected" | "disabled";
  first_observed_at: string;
  last_observed_at: string;
  created_at: string;
  updated_at: string;
};
export type PreferencePage = { items: Preference[]; total: number; limit: number; offset: number };
export type Pattern = {
  pattern_id: string;
  pattern_type: string;
  description: string;
  normalized_key: string;
  evidence_count: number;
  confidence: number;
  supporting_conversation_ids: string[];
  supporting_message_ids: string[];
  first_observed_at: string;
  last_observed_at: string;
  status: "candidate" | "confirmed" | "dismissed";
  created_at: string;
  updated_at: string;
};
export type PatternPage = { items: Pattern[]; total: number };
export type MemoryHealth = {
  total_approved: number;
  active: number;
  possibly_outdated: number;
  superseded: number;
  expired: number;
  archived: number;
  pending_review: number;
  low_utility: number;
  frequently_used: { memory_id: string; content: string; category: string; usage_count: number; utility_score: number }[];
  last_evaluated_at: string | null;
};
export type EvolutionItem = {
  memory_id: string;
  previous_content: string;
  new_content: string;
  change_type: string;
  change_reason: string;
  source_conversation_id: string | null;
  approval_status: string;
  changed_at: string;
};
export type FeedbackInsights = {
  total: number;
  helpful_count: number;
  not_helpful_count: number;
  incorrect_personalization_count: number;
  outdated_information_count: number;
  correction_requests: number;
  by_type: Record<string, number>;
  recent: { feedback_id: string; feedback_type: string; comment: string | null; created_at: string }[];
};
export type AdaptiveSettings = {
  preference_learning_enabled: boolean;
  auto_candidate_generation: boolean;
  pattern_detection_enabled: boolean;
  personalization_enabled: boolean;
  memory_decay_enabled: boolean;
  require_user_review: boolean;
  preference_confidence_threshold: number;
  preference_evidence_threshold: number;
  pattern_evidence_threshold: number;
  updated_at: string;
};

const ownerPath = (id: string) => `/api/v1/memories/preferences/${encodeURIComponent(id)}`;
export const listPreferences = (params: { status?: string; category?: string; limit?: number; offset?: number } = {}) => {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.category) query.set("category", params.category);
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));
  return requestJson<PreferencePage>(`/api/v1/memories/preferences?${query.toString()}`);
};
export const confirmPreference = (id: string, description?: string) => requestJson<Preference>(`${ownerPath(id)}/confirm`, {
  method: "POST", body: JSON.stringify(description ? { description } : {}),
});
export const updatePreference = (id: string, input: { description?: string; category?: PreferenceCategory; status?: "candidate" | "confirmed" | "disabled" }) => requestJson<Preference>(ownerPath(id), {
  method: "PUT", body: JSON.stringify(input),
});
export const rejectPreference = (id: string) => requestJson<Preference>(`${ownerPath(id)}/reject`, { method: "POST" });
export const deletePreference = (id: string) => requestJson<{ deleted: boolean }>(ownerPath(id), { method: "DELETE" });
export const listPatterns = (status?: string) => requestJson<PatternPage>(`/api/v1/memories/patterns${status ? `?status=${status}` : ""}`);
export const confirmPattern = (id: string) => requestJson<Pattern>(`/api/v1/memories/patterns/${encodeURIComponent(id)}/confirm`, { method: "POST" });
export const dismissPattern = (id: string) => requestJson<Pattern>(`/api/v1/memories/patterns/${encodeURIComponent(id)}/dismiss`, { method: "POST" });
export const getMemoryHealth = () => requestJson<MemoryHealth>("/api/v1/memories/health");
export const getEvolution = (params: { memory_id?: string; change_type?: string; limit?: number } = {}) => {
  const query = new URLSearchParams();
  if (params.memory_id) query.set("memory_id", params.memory_id);
  if (params.change_type) query.set("change_type", params.change_type);
  query.set("limit", String(params.limit ?? 100));
  return requestJson<{ items: EvolutionItem[]; total: number }>(`/api/v1/memories/evolution?${query.toString()}`);
};
export const getFeedbackInsights = () => requestJson<FeedbackInsights>("/api/v1/memories/feedback/insights");
export const getAdaptiveSettings = () => requestJson<AdaptiveSettings>("/api/v1/memories/adaptive-settings");
export const updateAdaptiveSettings = (input: Partial<Omit<AdaptiveSettings, "updated_at">>) => requestJson<AdaptiveSettings>("/api/v1/memories/adaptive-settings", {
  method: "PUT", body: JSON.stringify(input),
});
export const processAdaptiveNow = () => requestJson<{ processed_jobs: number; evaluated_memories: number; detected_patterns: number }>("/api/v1/memories/adaptive/process", { method: "POST" });
export const getAdaptiveStatus = () => requestJson<{ enabled: boolean; jobs: Record<string, number> }>("/api/v1/memories/adaptive/status");
export const setMemoryLifecycle = (id: string, status: "active" | "possibly_outdated" | "archived") => requestJson<Memory>(`/api/v1/memories/${encodeURIComponent(id)}/lifecycle`, {
  method: "POST", body: JSON.stringify({ status }),
});
export const submitResponseFeedback = (input: {
  targetType: "response" | "memory" | "preference";
  targetId: string;
  feedbackType: string;
  conversationId?: string | null;
  memoryIds?: string[];
}) => requestJson<{ feedback_id: string; feedback_type: string }>("/api/v1/memories/feedback", {
  method: "POST",
  body: JSON.stringify({
    target_type: input.targetType,
    target_id: input.targetId,
    feedback_type: input.feedbackType,
    conversation_id: input.conversationId || undefined,
    memory_ids: input.memoryIds ?? [],
    preference_ids: [],
  }),
});

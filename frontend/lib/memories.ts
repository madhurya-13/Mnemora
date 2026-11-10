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
export type MemorySearchResult = { memory: Memory; similarity: number; relevance: number };
export type MemorySearchResponse = { query: string; results: MemorySearchResult[] };

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
export const searchMemories = (query: string) => requestJson<MemorySearchResponse>("/api/v1/memories/search", {
  method: "POST", body: JSON.stringify({ query, top_k: 5 }),
});

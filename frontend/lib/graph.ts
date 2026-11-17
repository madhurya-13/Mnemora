import { requestJson } from "@/lib/api";

export const GRAPH_ENTITY_TYPES = [
  "person", "organization", "project", "technology", "programming_language",
  "skill", "educational_institution", "subject", "goal", "preference",
  "interest", "location", "event", "concept", "tool", "product",
] as const;

export const GRAPH_RELATIONSHIP_TYPES = [
  "STUDIES", "WORKS_ON", "DEVELOPS", "USES", "BUILT_WITH", "LEARNS",
  "INTERESTED_IN", "PREFERS", "BELONGS_TO", "HAS_GOAL", "HAS_FEATURE",
  "RELATED_TO", "DEPENDS_ON", "COMPLETED", "PARTICIPATES_IN", "LOCATED_IN",
  "REPLACED_BY", "EVOLVED_INTO",
] as const;

export type GraphEntityType = (typeof GRAPH_ENTITY_TYPES)[number];
export type GraphRelationshipType = (typeof GRAPH_RELATIONSHIP_TYPES)[number];
export type GraphEntityStatus = "active" | "pending_review" | "archived" | "merged";
export type GraphRelationshipStatus = "active" | "pending_review" | "historical" | "rejected" | "archived";

export type GraphEntity = {
  entity_id: string;
  entity_name: string;
  normalized_name: string;
  entity_type: GraphEntityType;
  description: string | null;
  aliases: string[];
  confidence: number;
  source_memory_ids: string[];
  status: GraphEntityStatus;
  merged_into_id: string | null;
  first_observed_at: string;
  last_observed_at: string;
  created_at: string;
  updated_at: string;
};

export type GraphConnection = {
  relationship_id: string;
  relationship_type: GraphRelationshipType;
  direction: "outgoing" | "incoming";
  entity: GraphEntity;
  description: string | null;
  confidence: number;
  status: GraphRelationshipStatus;
  valid_from: string | null;
  valid_until: string | null;
  evidence_memory_ids: string[];
};

export type GraphDuplicateCandidate = {
  entity_id: string;
  entity_name: string;
  entity_type: string;
  similarity: number;
  same_type: boolean;
  reason: string;
};

export type GraphEntityDetail = GraphEntity & {
  connections: GraphConnection[];
  possible_duplicates: GraphDuplicateCandidate[];
  incoming_count: number;
  outgoing_count: number;
};

export type GraphEntityPage = { items: GraphEntity[]; total: number; limit: number; offset: number };

export type GraphRelationship = {
  relationship_id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: GraphRelationshipType;
  description: string | null;
  confidence: number;
  evidence_memory_ids: string[];
  evidence: Record<string, unknown>[];
  valid_from: string | null;
  valid_until: string | null;
  status: GraphRelationshipStatus;
  superseded_by: string | null;
  created_at: string;
  updated_at: string;
  source_entity_name: string | null;
  target_entity_name: string | null;
};

export type GraphRelationshipPage = { items: GraphRelationship[]; total: number; limit: number; offset: number };

export type GraphVisualizationNode = {
  id: string;
  label: string;
  entity_type: GraphEntityType;
  description: string | null;
  confidence: number;
  status: GraphEntityStatus;
  degree: number;
  is_center: boolean;
  first_observed_at: string;
  last_observed_at: string;
  aliases: string[];
};

export type GraphVisualizationEdge = {
  id: string;
  source: string;
  target: string;
  relationship_type: GraphRelationshipType;
  label: string;
  description: string | null;
  confidence: number;
  status: GraphRelationshipStatus;
  valid_from: string | null;
  valid_until: string | null;
  evidence_memory_ids: string[];
  superseded_by: string | null;
};

export type GraphVisualization = {
  nodes: GraphVisualizationNode[];
  edges: GraphVisualizationEdge[];
  total_nodes: number;
  total_edges: number;
  truncated: boolean;
};

export type GraphPath = {
  entity_ids: string[];
  relationship_ids: string[];
  labels: string[];
  depth: number;
  score: number;
  historical: boolean;
  evidence_memory_ids: string[];
  relationship_types: string[];
};

export type GraphSearchResponse = {
  query: string;
  matched_entities: GraphVisualizationNode[];
  nodes: GraphVisualizationNode[];
  edges: GraphVisualizationEdge[];
  paths: GraphPath[];
  historical: boolean;
};

export type GraphTraversal = {
  start: GraphEntity;
  nodes: GraphVisualizationNode[];
  edges: GraphVisualizationEdge[];
  paths: GraphPath[];
  truncated: boolean;
  max_depth: number;
};

export type GraphHistoryEntry = {
  history_id: string;
  entity_id: string | null;
  relationship_id: string | null;
  action: string;
  summary: string;
  actor: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
};

export type GraphSyncRecord = {
  sync_id: string;
  source_type: string;
  source_id: string;
  status: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
};

export type GraphActivity = {
  history: GraphHistoryEntry[];
  sync_records: GraphSyncRecord[];
  total: number;
};

export type GraphEntitySummary = {
  entity_id: string;
  entity_name: string;
  entity_type: string;
  confidence: number;
  status: string;
  created_at: string;
  updated_at: string;
};

export type GraphRelationshipSummary = {
  relationship_id: string;
  source_entity_id: string;
  target_entity_id: string;
  source_name: string;
  target_name: string;
  relationship_type: string;
  confidence: number;
  status: string;
  updated_at: string;
  valid_from: string | null;
  valid_until: string | null;
};

export type GraphInsights = {
  total_entities: number;
  active_entities: number;
  total_relationships: number;
  active_relationships: number;
  historical_relationships: number;
  pending_entities: number;
  pending_relationships: number;
  entity_type_counts: Record<string, number>;
  relationship_type_counts: Record<string, number>;
  recently_added_entities: GraphEntitySummary[];
  recently_updated_relationships: GraphRelationshipSummary[];
  most_connected_entities: (GraphEntitySummary & { degree: number })[];
  isolated_entities: GraphEntitySummary[];
  growth: { date: string; entities: number }[];
  pending_corrections: number;
  merge_count: number;
  sync_pending: number;
  sync_failed: number;
  evidence_coverage: number;
};

export type GraphMergeRecord = {
  merge_id: string;
  primary_entity_id: string;
  merged_entity_id: string;
  status: string;
  performed_by: string;
  created_at: string;
  undone_at: string | null;
};

export type GraphMergeResult = {
  merge_id: string;
  primary: GraphEntity;
  merged_entity_id: string;
  moved_relationships: number;
  collapsed_relationships: number;
  aliases: string[];
};

export type GraphHealth = {
  enabled: boolean;
  entities: number;
  relationships: number;
  active_relationships: number;
  pending_review: number;
  sync_pending: number;
  sync_failed: number;
  max_depth: number;
};

type VisualizationParams = {
  entity_types?: string[];
  relationship_types?: string[];
  center_entity_id?: string;
  search?: string;
  depth?: number;
  include_isolated?: boolean;
  include_historical?: boolean;
  limit_nodes?: number;
  limit_edges?: number;
};

function queryString(params: Record<string, string | number | boolean | string[] | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) query.append(key, item);
    } else {
      query.set(key, String(value));
    }
  }
  return query.toString();
}

export const getGraphVisualization = (params: VisualizationParams = {}) =>
  requestJson<GraphVisualization>(`/api/v1/graph/visualization?${queryString(params)}`);

export const listGraphEntities = (params: { entity_type?: string; status?: string; search?: string; limit?: number; offset?: number } = {}) =>
  requestJson<GraphEntityPage>(`/api/v1/graph/entities?${queryString({ limit: 100, offset: 0, ...params })}`);

export const getGraphEntity = (id: string) =>
  requestJson<GraphEntityDetail>(`/api/v1/graph/entities/${encodeURIComponent(id)}`);

export const createGraphEntity = (input: {
  entity_name: string;
  entity_type: GraphEntityType;
  description?: string | null;
  aliases?: string[];
  confidence?: number;
}) => requestJson<GraphEntity>("/api/v1/graph/entities", {
  method: "POST", body: JSON.stringify(input),
});

export const updateGraphEntity = (id: string, input: {
  entity_name?: string;
  entity_type?: GraphEntityType;
  description?: string | null;
  aliases?: string[];
  confidence?: number;
  status?: "active" | "pending_review" | "archived";
}) => requestJson<GraphEntity>(`/api/v1/graph/entities/${encodeURIComponent(id)}`, {
  method: "PATCH", body: JSON.stringify(input),
});

export const deleteGraphEntity = (id: string) =>
  requestJson<{ deleted: boolean; entity_id: string; relationships_archived: number; memories_deleted: number }>(`/api/v1/graph/entities/${encodeURIComponent(id)}`, { method: "DELETE" });

export const getGraphEntityConnections = (id: string, params: { depth?: number; direction?: "both" | "out" | "in"; include_historical?: boolean } = {}) =>
  requestJson<GraphVisualization>(`/api/v1/graph/entities/${encodeURIComponent(id)}/connections?${queryString({ depth: 1, ...params })}`);

export const getGraphEntityHistory = (id: string) =>
  requestJson<GraphHistoryEntry[]>(`/api/v1/graph/entities/${encodeURIComponent(id)}/history`);

export const mergeGraphEntities = (primaryEntityId: string, duplicateEntityId: string, confirmSimilar = false) =>
  requestJson<GraphMergeResult>("/api/v1/graph/entities/merge", {
    method: "POST",
    body: JSON.stringify({
      primary_entity_id: primaryEntityId,
      duplicate_entity_id: duplicateEntityId,
      confirm_similar: confirmSimilar,
    }),
  });

export const listGraphMerges = (limit = 20) =>
  requestJson<GraphMergeRecord[]>(`/api/v1/graph/merges?limit=${limit}`);

export const undoGraphMerge = (mergeId: string) =>
  requestJson<{ undone: boolean; restored_entity: GraphEntity }>(`/api/v1/graph/entities/merge/${encodeURIComponent(mergeId)}/undo`, { method: "POST" });

export const getGraphRelationship = (id: string) =>
  requestJson<GraphRelationship>(`/api/v1/graph/relationships/${encodeURIComponent(id)}`);

export const listGraphRelationships = (params: {
  source_entity_id?: string;
  target_entity_id?: string;
  relationship_type?: string;
  status?: string;
  limit?: number;
  offset?: number;
} = {}) =>
  requestJson<GraphRelationshipPage>(`/api/v1/graph/relationships?${queryString({ limit: 100, offset: 0, ...params })}`);

export const createGraphRelationship = (input: {
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: GraphRelationshipType;
  description?: string | null;
  confidence?: number;
  valid_from?: string | null;
}) => requestJson<GraphRelationship>("/api/v1/graph/relationships", {
  method: "POST", body: JSON.stringify(input),
});

export const updateGraphRelationship = (id: string, input: {
  relationship_type?: GraphRelationshipType;
  description?: string | null;
  confidence?: number;
  valid_from?: string | null;
  valid_until?: string | null;
  status?: GraphRelationshipStatus;
}) => requestJson<GraphRelationship>(`/api/v1/graph/relationships/${encodeURIComponent(id)}`, {
  method: "PATCH", body: JSON.stringify(input),
});

export const deleteGraphRelationship = (id: string) =>
  requestJson<{ deleted: boolean }>(`/api/v1/graph/relationships/${encodeURIComponent(id)}`, { method: "DELETE" });

export const searchKnowledgeGraph = (query: string, params: { max_depth?: number; include_historical?: boolean } = {}) =>
  requestJson<GraphSearchResponse>("/api/v1/graph/search", {
    method: "POST",
    body: JSON.stringify({ query, max_depth: params.max_depth ?? 2, include_historical: params.include_historical ?? false }),
  });

export const traverseKnowledgeGraph = (input: {
  start_entity_id?: string;
  start_name?: string;
  max_depth?: number;
  direction?: "both" | "out" | "in";
  relationship_types?: string[];
  include_historical?: boolean;
}) => requestJson<GraphTraversal>("/api/v1/graph/traverse", {
  method: "POST", body: JSON.stringify(input),
});

export const getGraphInsights = (params: {
  date_from?: string;
  date_to?: string;
  entity_type?: string;
  relationship_type?: string;
} = {}) => requestJson<GraphInsights>(`/api/v1/graph/insights?${queryString(params)}`);

export const getGraphActivity = (limit = 30) =>
  requestJson<GraphActivity>(`/api/v1/graph/activity?limit=${limit}`);

export const rebuildKnowledgeGraph = (includePending = true) =>
  requestJson<{ memories_processed: number; preference_links: number; entities: number; relationships: number }>("/api/v1/graph/rebuild", {
    method: "POST", body: JSON.stringify({ include_pending: includePending }),
  });

export const getGraphHealth = () => requestJson<GraphHealth>("/api/v1/graph/health");

export const entityTypeLabel = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
export const relationshipLabel = (value: string) => value.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());

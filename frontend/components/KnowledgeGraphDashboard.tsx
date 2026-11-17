"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarRange,
  Check,
  ChevronDown,
  CircleHelp,
  Compass,
  GitBranch,
  GitMerge,
  Layers3,
  LoaderCircle,
  Network,
  Plus,
  RefreshCw,
  RotateCcw,
  Route,
  Search,
  Sparkles,
  Undo2,
  X,
} from "lucide-react";
import GraphCanvas from "@/components/graph/GraphCanvas";
import { EntityDetails, RelationshipDetails } from "@/components/graph/GraphDetails";
import { ApiError } from "@/lib/api";
import {
  GRAPH_ENTITY_TYPES,
  GRAPH_RELATIONSHIP_TYPES,
  createGraphEntity,
  createGraphRelationship,
  entityTypeLabel,
  getGraphActivity,
  getGraphEntity,
  getGraphEntityConnections,
  getGraphEntityHistory,
  getGraphHealth,
  getGraphInsights,
  getGraphRelationship,
  getGraphVisualization,
  listGraphEntities,
  listGraphMerges,
  rebuildKnowledgeGraph,
  relationshipLabel,
  searchKnowledgeGraph,
  undoGraphMerge,
  type GraphActivity,
  type GraphEntity,
  type GraphEntityDetail,
  type GraphEntityType,
  type GraphHealth,
  type GraphHistoryEntry,
  type GraphInsights,
  type GraphMergeRecord,
  type GraphRelationship,
  type GraphRelationshipType,
  type GraphVisualization,
  type GraphVisualizationEdge,
  type GraphVisualizationNode,
} from "@/lib/graph";

const DEFAULT_DEPTH = 2;
const date = (value: string | null) => value
  ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value))
  : "—";
const datetime = (value: string | null) => value
  ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
  : "—";
const score = (value: number) => `${Math.round(value * 100)}%`;

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "The knowledge graph request could not be completed.";
}

function uniqueGraph(base: GraphVisualization, addition: GraphVisualization): GraphVisualization {
  const nodes = new Map(base.nodes.map((node) => [node.id, node]));
  for (const node of addition.nodes) nodes.set(node.id, node);
  const edges = new Map(base.edges.map((edge) => [edge.id, edge]));
  for (const edge of addition.edges) edges.set(edge.id, edge);
  return {
    nodes: Array.from(nodes.values()),
    edges: Array.from(edges.values()),
    total_nodes: nodes.size,
    total_edges: edges.size,
    truncated: base.truncated || addition.truncated,
  };
}

export default function KnowledgeGraphDashboard() {
  const [graph, setGraph] = useState<GraphVisualization | null>(null);
  const [health, setHealth] = useState<GraphHealth | null>(null);
  const [insights, setInsights] = useState<GraphInsights | null>(null);
  const [activity, setActivity] = useState<GraphActivity | null>(null);
  const [entities, setEntities] = useState<GraphEntity[]>([]);
  const [merges, setMerges] = useState<GraphMergeRecord[]>([]);
  const [loadingGraph, setLoadingGraph] = useState(true);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [entityType, setEntityType] = useState("");
  const [relationshipType, setRelationshipType] = useState("");
  const [depth, setDepth] = useState(DEFAULT_DEPTH);
  const [includeHistorical, setIncludeHistorical] = useState(false);
  const [includeIsolated, setIncludeIsolated] = useState(true);

  const [query, setQuery] = useState("");
  const [matchedIds, setMatchedIds] = useState<Set<string>>(new Set());
  const [queryResultLabel, setQueryResultLabel] = useState<string | null>(null);

  const [selectedEntity, setSelectedEntity] = useState<GraphEntityDetail | null>(null);
  const [selectedRelationship, setSelectedRelationship] = useState<GraphRelationship | null>(null);
  const [relationshipLoading, setRelationshipLoading] = useState(false);
  const [history, setHistory] = useState<GraphHistoryEntry[]>([]);

  const [pathFrom, setPathFrom] = useState("");
  const [pathTo, setPathTo] = useState("");
  const [highlightNodes, setHighlightNodes] = useState<Set<string>>(new Set());
  const [highlightEdges, setHighlightEdges] = useState<Set<string>>(new Set());
  const [resetKey, setResetKey] = useState(0);

  const [addEntityOpen, setAddEntityOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState<GraphEntityType>("project");
  const [newDescription, setNewDescription] = useState("");
  const [newConfidence, setNewConfidence] = useState(0.9);

  const [relationshipSource, setRelationshipSource] = useState("");
  const [relationshipTarget, setRelationshipTarget] = useState("");
  const [relationshipKind, setRelationshipKind] = useState<GraphRelationshipType>("RELATED_TO");
  const [relationshipDescription, setRelationshipDescription] = useState("");

  const [insightEntityType, setInsightEntityType] = useState("");
  const [insightRelationshipType, setInsightRelationshipType] = useState("");
  const [insightFrom, setInsightFrom] = useState("");
  const [insightTo, setInsightTo] = useState("");

  const insightParams = useMemo(() => ({
    entity_type: insightEntityType || undefined,
    relationship_type: insightRelationshipType || undefined,
    date_from: insightFrom ? new Date(`${insightFrom}T00:00:00`).toISOString() : undefined,
    date_to: insightTo ? new Date(`${insightTo}T23:59:59`).toISOString() : undefined,
  }), [insightEntityType, insightRelationshipType, insightFrom, insightTo]);

  const loadGraph = useCallback(async () => {
    setLoadingGraph(true);
    try {
      const payload = await getGraphVisualization({
        search: search.trim() || undefined,
        entity_types: entityType ? [entityType] : undefined,
        relationship_types: relationshipType ? [relationshipType] : undefined,
        depth,
        include_historical: includeHistorical,
        include_isolated: includeIsolated,
      });
      setGraph(payload);
      setMatchedIds(new Set());
      setQueryResultLabel(null);
      setHighlightNodes(new Set());
      setHighlightEdges(new Set());
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoadingGraph(false);
    }
  }, [search, entityType, relationshipType, depth, includeHistorical, includeIsolated]);

  const loadAux = useCallback(async () => {
    const results = await Promise.allSettled([
      getGraphInsights(insightParams),
      getGraphActivity(30),
      listGraphEntities({ limit: 200 }),
      listGraphMerges(20),
      getGraphHealth(),
    ]);
    const [insightResult, activityResult, entitiesResult, mergesResult, healthResult] = results;
    if (insightResult.status === "fulfilled") setInsights(insightResult.value);
    if (activityResult.status === "fulfilled") setActivity(activityResult.value);
    if (entitiesResult.status === "fulfilled") setEntities(entitiesResult.value.items);
    if (mergesResult.status === "fulfilled") setMerges(mergesResult.value);
    if (healthResult.status === "fulfilled") {
      setHealth(healthResult.value);
      setDepth((current) => Math.min(current, healthResult.value.max_depth));
    }
    const failure = results.find((result) => result.status === "rejected");
    if (failure && failure.status === "rejected") setError(errorMessage(failure.reason));
  }, [insightParams]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadGraph(); }, 220);
    return () => window.clearTimeout(timer);
  }, [loadGraph, resetKey]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadAux(); }, 0);
    return () => window.clearTimeout(timer);
  }, [loadAux]);

  const selectedNodeId = selectedEntity?.entity_id ?? null;
  const selectedEdgeId = selectedRelationship?.relationship_id ?? null;

  async function refreshSelected(entityId: string | null) {
    if (!entityId) return;
    try {
      const [detail, entityHistory] = await Promise.all([
        getGraphEntity(entityId),
        getGraphEntityHistory(entityId).catch(() => []),
      ]);
      setSelectedEntity(detail);
      setHistory(entityHistory);
    } catch {
      setSelectedEntity(null);
      setHistory([]);
    }
  }

  async function refreshAll(entityId: string | null) {
    const relationshipId = selectedRelationship?.relationship_id ?? null;
    await Promise.all([
      loadGraph(),
      loadAux(),
      refreshSelected(entityId),
      relationshipId
        ? getGraphRelationship(relationshipId).then(setSelectedRelationship).catch(() => undefined)
        : Promise.resolve(),
    ]);
  }

  async function selectNode(entityId: string) {
    setSelectedRelationship(null);
    setRelationshipLoading(false);
    setLoadingDetails(true);
    try {
      const detail = await getGraphEntity(entityId);
      setSelectedEntity(detail);
      setHistory(await getGraphEntityHistory(entityId).catch(() => []));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoadingDetails(false);
    }
  }

  async function selectEdge(edgeId: string) {
    setSelectedEntity(null);
    setHistory([]);
    setRelationshipLoading(true);
    try {
      const relationship = await getGraphRelationship(edgeId);
      setSelectedRelationship(relationship);
      setError(null);
    } catch (caught) {
      setRelationshipLoading(false);
      setError(errorMessage(caught));
    } finally {
      setRelationshipLoading(false);
    }
  }

  function clearSelection() {
    setSelectedEntity(null);
    setSelectedRelationship(null);
    setHistory([]);
    setRelationshipLoading(false);
  }

  async function runGraphQuestion(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy("search");
    setError(null);
    setNotice(null);
    try {
      const result = await searchKnowledgeGraph(query.trim(), { max_depth: depth, include_historical: includeHistorical });
      setGraph({
        nodes: result.nodes,
        edges: result.edges,
        total_nodes: result.nodes.length,
        total_edges: result.edges.length,
        truncated: false,
      });
      setMatchedIds(new Set(result.matched_entities.map((node) => node.id)));
      setQueryResultLabel(
        result.matched_entities.length
          ? `Matched ${result.matched_entities.map((node) => node.label).join(", ")} · ${result.paths.length} path(s)`
          : "No matching entities were found for this question.",
      );
      setHighlightNodes(new Set());
      setHighlightEdges(new Set());
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function expandConnections(entityId: string) {
    if (!graph) return;
    setBusy("expand");
    try {
      const addition = await getGraphEntityConnections(entityId, { depth: 1, include_historical: includeHistorical });
      setGraph(uniqueGraph(graph, addition));
      setNotice(`Expanded connections for ${graph.nodes.find((node) => node.id === entityId)?.label ?? "the selected entity"}. Use Reset view to collapse.`);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  function resetView() {
    setSearch("");
    setEntityType("");
    setRelationshipType("");
    setDepth(Math.min(DEFAULT_DEPTH, health?.max_depth ?? DEFAULT_DEPTH));
    setIncludeHistorical(false);
    setIncludeIsolated(true);
    setQuery("");
    setMatchedIds(new Set());
    setQueryResultLabel(null);
    setPathFrom("");
    setPathTo("");
    setHighlightNodes(new Set());
    setHighlightEdges(new Set());
    setResetKey((value) => value + 1);
    clearSelection();
  }

  function findPath() {
    if (!graph || !pathFrom || !pathTo) {
      setError("Choose two entities to highlight a path.");
      return;
    }
    const adjacency = new Map<string, { to: string; edgeId: string }[]>();
    for (const edge of graph.edges) {
      adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), { to: edge.target, edgeId: edge.id }]);
      adjacency.set(edge.target, [...(adjacency.get(edge.target) ?? []), { to: edge.source, edgeId: edge.id }]);
    }
    const queue: string[] = [pathFrom];
    const previous = new Map<string, { from: string; edgeId: string } | null>([[pathFrom, null]]);
    while (queue.length > 0) {
      const current = queue.shift() as string;
      if (current === pathTo) break;
      for (const link of adjacency.get(current) ?? []) {
        if (!previous.has(link.to)) {
          previous.set(link.to, { from: current, edgeId: link.edgeId });
          queue.push(link.to);
        }
      }
    }
    if (!previous.has(pathTo)) {
      setHighlightNodes(new Set());
      setHighlightEdges(new Set());
      setError("No path exists between those entities in the currently displayed graph.");
      return;
    }
    const nodes = new Set<string>([pathTo]);
    const edges = new Set<string>();
    let cursor = pathTo;
    while (cursor !== pathFrom) {
      const step = previous.get(cursor);
      if (!step) break;
      edges.add(step.edgeId);
      nodes.add(step.from);
      cursor = step.from;
    }
    setHighlightNodes(nodes);
    setHighlightEdges(edges);
    const names = graph.nodes.filter((node) => nodes.has(node.id)).map((node) => node.label);
    setNotice(`Highlighted ${edges.size}-hop path: ${names.join(" → ")}.`);
    setError(null);
  }

  function clearPath() {
    setHighlightNodes(new Set());
    setHighlightEdges(new Set());
    setPathFrom("");
    setPathTo("");
  }

  async function addEntity(event: React.FormEvent) {
    event.preventDefault();
    if (!newName.trim()) return;
    setBusy("entity");
    setError(null);
    try {
      const created = await createGraphEntity({
        entity_name: newName.trim(),
        entity_type: newType,
        description: newDescription.trim() || null,
        confidence: newConfidence,
      });
      setNewName("");
      setNewDescription("");
      setNewConfidence(0.9);
      setAddEntityOpen(false);
      setNotice(`Created ${created.entity_name} as a ${entityTypeLabel(created.entity_type)}.`);
      await Promise.all([loadGraph(), loadAux()]);
      await selectNode(created.entity_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function addRelationship(event: React.FormEvent) {
    event.preventDefault();
    if (!relationshipSource || !relationshipTarget) {
      setError("Choose both a source and a target entity.");
      return;
    }
    if (relationshipSource === relationshipTarget) {
      setError("A relationship needs two different entities.");
      return;
    }
    setBusy("relationship");
    setError(null);
    try {
      const created = await createGraphRelationship({
        source_entity_id: relationshipSource,
        target_entity_id: relationshipTarget,
        relationship_type: relationshipKind,
        description: relationshipDescription.trim() || null,
      });
      setRelationshipDescription("");
      setNotice(`Created ${relationshipLabel(created.relationship_type)} relationship.`);
      await Promise.all([loadGraph(), loadAux()]);
      await selectEdge(created.relationship_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function undoMerge(mergeId: string) {
    if (!window.confirm("Undo this merge and restore the duplicate entity?")) return;
    setBusy(`merge-${mergeId}`);
    setError(null);
    try {
      const result = await undoGraphMerge(mergeId);
      setNotice(`Restored ${result.restored_entity.entity_name}.`);
      await refreshAll(selectedEntity?.entity_id ?? null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function rebuild() {
    if (!window.confirm("Rebuild the graph from your stored memories? This is idempotent and will not delete memories.")) return;
    setBusy("rebuild");
    setError(null);
    try {
      const result = await rebuildKnowledgeGraph();
      setNotice(`Rebuilt from ${result.memories_processed} memories: ${result.entities} entities and ${result.relationships} relationships; ${result.preference_links} preference links updated.`);
      await refreshAll(selectedEntity?.entity_id ?? null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  const nodes: GraphVisualizationNode[] = graph?.nodes ?? [];
  const edges: GraphVisualizationEdge[] = graph?.edges ?? [];
  const entityOptions = useMemo(
    () => [...(graph?.nodes ?? [])].sort((a, b) => a.label.localeCompare(b.label)),
    [graph?.nodes],
  );
  const typeCounts = Object.entries(insights?.entity_type_counts ?? {}).sort((a, b) => b[1] - a[1]);
  const relationshipCounts = Object.entries(insights?.relationship_type_counts ?? {}).sort((a, b) => b[1] - a[1]);
  const maxTypeCount = Math.max(1, ...typeCounts.map(([, count]) => count));
  const growth = insights?.growth ?? [];
  const maxGrowth = Math.max(1, ...growth.map((point) => point.entities));

  return (
    <main className="min-h-dvh bg-[#080a12] text-slate-100">
      <header className="sticky top-0 z-20 border-b border-white/[0.07] bg-[#0a0c15]/95 px-4 py-4 backdrop-blur sm:px-8">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <Link href="/" className="rounded-lg p-2 text-slate-400 transition hover:bg-white/[0.06] hover:text-white" aria-label="Back to chat"><ArrowLeft size={18} /></Link>
            <span className="grid h-10 w-10 place-items-center rounded-xl border border-blue-300/20 bg-blue-400/10 text-blue-200"><Network size={19} /></span>
            <div className="min-w-0"><h1 className="truncate text-lg font-medium">Knowledge Graph</h1><p className="truncate text-xs text-slate-500">How your memories, projects, skills and interests connect</p></div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Link href="/memory" className="hidden rounded-xl border border-white/[0.08] px-3 py-2 text-xs text-slate-300 transition hover:border-violet-300/20 hover:text-violet-100 sm:block">Memory</Link>
            <Link href="/" className="rounded-xl border border-white/[0.08] px-3 py-2 text-xs text-slate-300 transition hover:border-violet-300/20 hover:text-violet-100">Return to chat</Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1500px] space-y-5 px-4 py-6 sm:px-8">
        {error && <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-300/15 bg-rose-300/[0.06] px-4 py-3 text-sm text-rose-100"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><span className="min-w-0 flex-1">{error}</span><button onClick={() => setError(null)} aria-label="Dismiss error" className="text-rose-200/70"><X size={16} /></button></div>}
        {notice && <div role="status" className="flex items-start gap-2 rounded-xl border border-emerald-300/10 bg-emerald-300/[0.04] px-4 py-3 text-sm text-emerald-100/90"><Check size={16} className="mt-0.5 shrink-0" /><span className="min-w-0 flex-1">{notice}</span><button onClick={() => setNotice(null)} aria-label="Dismiss notice" className="text-emerald-200/60"><X size={15} /></button></div>}
        {health && !health.enabled && <div className="rounded-xl border border-amber-300/15 bg-amber-300/[0.05] px-4 py-3 text-xs leading-5 text-amber-100/90">The knowledge graph is disabled by backend configuration (<code>KNOWLEDGE_GRAPH_ENABLED</code>). Existing data is preserved.</div>}

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6" aria-label="Knowledge graph statistics">
          {[
            ["Entities", insights?.total_entities],
            ["Relationships", insights?.total_relationships],
            ["Active facts", insights?.active_relationships],
            ["Historical", insights?.historical_relationships],
            ["Pending review", (insights?.pending_entities ?? 0) + (insights?.pending_relationships ?? 0)],
            ["Evidence coverage", insights ? score(insights.evidence_coverage) : undefined],
          ].map(([title, value]) => <div key={String(title)} className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"><p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{title}</p><p className="mt-2.5 text-2xl font-light text-slate-100">{insights ? (value ?? "—") : "—"}</p></div>)}
        </section>

        <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-3 sm:p-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
            <form onSubmit={runGraphQuestion} className="flex min-w-0 flex-1 gap-2 rounded-xl border border-white/[0.08] bg-black/20 p-1.5 focus-within:border-violet-300/25">
              <Search className="ml-2 mt-2 shrink-0 text-slate-500" size={16} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask the graph: “Show all technologies connected to MNEMORA.”" className="min-w-0 flex-1 bg-transparent px-1.5 py-1.5 text-sm outline-none placeholder:text-slate-600" />
              <button disabled={busy === "search" || !query.trim()} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-violet-400/15 px-3 text-xs text-violet-100 transition hover:bg-violet-400/25 disabled:opacity-40">{busy === "search" ? <LoaderCircle className="animate-spin" size={13} /> : <Compass size={13} />} Ask graph</button>
            </form>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter entity names…" aria-label="Filter entity names" className="w-44 rounded-xl border border-white/[0.08] bg-[#0c0e17] px-3 py-2 text-xs text-slate-300 outline-none placeholder:text-slate-600" />
              <button onClick={() => { resetView(); }} className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.08] px-3 py-2 text-slate-300 hover:border-violet-300/20 hover:text-violet-100"><RotateCcw size={13} /> Reset view</button>
              <button disabled={busy === "rebuild"} onClick={() => void rebuild()} className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.08] px-3 py-2 text-slate-300 hover:border-blue-300/20 hover:text-blue-100 disabled:opacity-40">{busy === "rebuild" ? <LoaderCircle className="animate-spin" size={13} /> : <RefreshCw size={13} />} Rebuild</button>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <select value={entityType} onChange={(event) => setEntityType(event.target.value)} aria-label="Filter by entity type" className="rounded-xl border border-white/[0.08] bg-[#0c0e17] px-3 py-2 text-xs text-slate-300"><option value="">All entity types</option>{GRAPH_ENTITY_TYPES.map((item) => <option key={item} value={item}>{entityTypeLabel(item)}</option>)}</select>
            <select value={relationshipType} onChange={(event) => setRelationshipType(event.target.value)} aria-label="Filter by relationship type" className="rounded-xl border border-white/[0.08] bg-[#0c0e17] px-3 py-2 text-xs text-slate-300"><option value="">All relationships</option>{GRAPH_RELATIONSHIP_TYPES.map((item) => <option key={item} value={item}>{relationshipLabel(item)}</option>)}</select>
            <label className="inline-flex items-center gap-2 rounded-xl border border-white/[0.08] px-3 py-2 text-slate-400">Depth<span className="font-medium text-slate-200">{depth}</span><input type="range" min={1} max={health?.max_depth ?? 5} value={depth} onChange={(event) => setDepth(Number(event.target.value))} className="w-20 accent-violet-400" aria-label="Graph depth" /></label>
            <label className="inline-flex items-center gap-2 rounded-xl border border-white/[0.08] px-3 py-2 text-slate-400"><input type="checkbox" checked={includeHistorical} onChange={(event) => setIncludeHistorical(event.target.checked)} className="accent-violet-400" /> Historical facts</label>
            <label className="inline-flex items-center gap-2 rounded-xl border border-white/[0.08] px-3 py-2 text-slate-400"><input type="checkbox" checked={includeIsolated} onChange={(event) => setIncludeIsolated(event.target.checked)} className="accent-violet-400" /> Isolated entities</label>
            {queryResultLabel && <span className="rounded-full bg-violet-300/[0.08] px-3 py-1.5 text-[10px] text-violet-100">{queryResultLabel}</span>}
            {queryResultLabel && <button onClick={() => { setQuery(""); setQueryResultLabel(null); void loadGraph(); }} className="text-[10px] text-violet-300 hover:text-violet-200">Clear graph question</button>}
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
          <div className="space-y-4">
            <div className="relative h-[600px] min-h-[420px]">
              {loadingGraph && <div className="absolute inset-0 z-10 grid place-items-center rounded-2xl bg-[#090b14]/80 backdrop-blur-sm"><span className="inline-flex items-center gap-2 text-sm text-slate-400"><LoaderCircle className="animate-spin" size={16} /> Loading graph</span></div>}
              {!loadingGraph && nodes.length === 0 ? (
                <div className="grid h-full place-items-center rounded-2xl border border-dashed border-white/[0.09] px-6 text-center">
                  <div><Network className="mx-auto text-violet-200/60" size={26} /><p className="mt-3 text-sm text-slate-300">No graph data matches this view.</p><p className="mt-1 max-w-md text-xs leading-5 text-slate-600">Approve memories in the Memory page, then use Rebuild, or add an entity manually below. Pending graph facts never enter retrieval.</p></div>
                </div>
              ) : (
                <GraphCanvas
                  nodes={nodes}
                  edges={edges}
                  selectedNodeId={selectedNodeId}
                  selectedEdgeId={selectedEdgeId}
                  highlightedNodeIds={highlightNodes}
                  highlightedEdgeIds={highlightEdges}
                  onNodeSelect={(id) => void selectNode(id)}
                  onEdgeSelect={(id) => void selectEdge(id)}
                  onPaneSelect={clearSelection}
                />
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[10px] text-slate-500">
              <span className="font-medium text-slate-400">{graph?.total_nodes ?? 0} nodes · {graph?.total_edges ?? 0} edges</span>
              {graph?.truncated && <span className="text-amber-200">View truncated by node/edge limits — narrow the filters.</span>}
              <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-violet-300" /> person/hub</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-blue-300" /> project</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-sky-300" /> technology</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-300" /> pending review</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-slate-500" /> historical</span>
              <span className="ml-auto inline-flex items-center gap-1 text-slate-600"><CircleHelp size={11} /> Drag nodes · scroll to zoom · drag canvas to pan</span>
            </div>

            <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
              <div className="flex flex-wrap items-center gap-2"><Route size={14} className="text-blue-200" /><h2 className="text-xs font-medium">Highlight a path</h2><span className="text-[10px] text-slate-600">Uses only the currently displayed relationships</span></div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <select value={pathFrom} onChange={(event) => setPathFrom(event.target.value)} aria-label="Path start entity" className="min-w-0 flex-1 rounded-xl border border-white/[0.08] bg-[#0c0e17] px-3 py-2 text-xs text-slate-300"><option value="">Start entity…</option>{entityOptions.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select>
                <span className="text-slate-600">→</span>
                <select value={pathTo} onChange={(event) => setPathTo(event.target.value)} aria-label="Path end entity" className="min-w-0 flex-1 rounded-xl border border-white/[0.08] bg-[#0c0e17] px-3 py-2 text-xs text-slate-300"><option value="">End entity…</option>{entityOptions.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select>
                <button onClick={findPath} className="rounded-xl bg-blue-400/10 px-3 py-2 text-xs text-blue-100 hover:bg-blue-400/20">Highlight path</button>
                {(highlightEdges.size > 0 || pathFrom || pathTo) && <button onClick={clearPath} className="text-[10px] text-slate-500 hover:text-slate-300">Clear</button>}
              </div>
            </section>
          </div>

          <aside className="space-y-4">
            <section role="dialog" aria-labelledby={selectedEntity || selectedRelationship ? "graph-details-title" : undefined} className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
              {loadingDetails ? <div className="flex items-center gap-2 py-8 text-xs text-slate-500"><LoaderCircle className="animate-spin" size={14} /> Loading entity details</div>
                : selectedEntity ? <EntityDetails key={`${selectedEntity.entity_id}:${selectedEntity.updated_at}`} entity={selectedEntity} history={history} onClose={clearSelection} onChange={() => void refreshAll(selectedEntity.entity_id)} onDeleted={() => { clearSelection(); void refreshAll(null); }} onExpand={(id) => void expandConnections(id)} onOpenEntity={(id) => void selectNode(id)} onError={setError} onNotice={setNotice} />
                  : selectedRelationship ? <RelationshipDetails key={`${selectedRelationship.relationship_id}:${selectedRelationship.updated_at}`} relationship={selectedRelationship} loading={relationshipLoading} onClose={clearSelection} onChange={() => void refreshAll(null)} onDeleted={() => { clearSelection(); void refreshAll(null); }} onError={setError} onNotice={setNotice} />
                    : <div className="py-6 text-center"><Layers3 className="mx-auto text-slate-600" size={22} /><p className="mt-3 text-sm text-slate-300">Select a node or relationship</p><p className="mt-1 text-xs leading-5 text-slate-600">Inspect evidence, confidence, temporal status, connected entities and change history. You can edit or delete what MNEMORA stored.</p></div>}
            </section>

            <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
              <div className="flex items-center justify-between gap-2"><div className="flex items-center gap-2"><Plus size={14} className="text-violet-200" /><h2 className="text-xs font-medium">Graph management</h2></div><button onClick={() => setAddEntityOpen((value) => !value)} className="inline-flex items-center gap-1 text-[10px] text-violet-200 hover:text-violet-100">{addEntityOpen ? <X size={12} /> : <ChevronDown size={12} />} {addEntityOpen ? "Close" : "Add entity"}</button></div>
              {addEntityOpen && <form onSubmit={addEntity} className="mt-3 space-y-2 rounded-xl border border-violet-300/10 bg-violet-300/[0.03] p-3">
                <input value={newName} onChange={(event) => setNewName(event.target.value)} maxLength={200} placeholder="Entity name" className="w-full rounded-lg border border-white/[0.08] bg-black/25 px-3 py-2 text-sm outline-none focus:border-violet-300/30" />
                <div className="grid grid-cols-2 gap-2"><select value={newType} onChange={(event) => setNewType(event.target.value as GraphEntityType)} aria-label="New entity type" className="rounded-lg border border-white/[0.08] bg-[#11131d] px-2 py-2 text-xs text-slate-300">{GRAPH_ENTITY_TYPES.map((item) => <option key={item} value={item}>{entityTypeLabel(item)}</option>)}</select><label className="flex items-center gap-2 text-[10px] text-slate-500">Confidence {score(newConfidence)}<input type="range" min={0} max={1} step={0.01} value={newConfidence} onChange={(event) => setNewConfidence(Number(event.target.value))} className="w-full accent-violet-400" /></label></div>
                <input value={newDescription} onChange={(event) => setNewDescription(event.target.value)} maxLength={2000} placeholder="Description (optional)" className="w-full rounded-lg border border-white/[0.08] bg-black/25 px-3 py-2 text-xs outline-none focus:border-violet-300/30" />
                <button disabled={busy === "entity" || !newName.trim()} className="inline-flex items-center gap-1.5 rounded-lg bg-violet-400/15 px-3 py-2 text-[11px] text-violet-100 disabled:opacity-40">{busy === "entity" ? <LoaderCircle className="animate-spin" size={12} /> : <Plus size={12} />} Create entity</button>
              </form>}
              <form onSubmit={addRelationship} className="mt-3 space-y-2">
                <div className="grid grid-cols-2 gap-2">
                  <select value={relationshipSource} onChange={(event) => setRelationshipSource(event.target.value)} aria-label="Relationship source" className="min-w-0 rounded-lg border border-white/[0.08] bg-[#0c0e17] px-2 py-2 text-[11px] text-slate-300"><option value="">Source…</option>{entities.map((entity) => <option key={entity.entity_id} value={entity.entity_id}>{entity.entity_name}</option>)}</select>
                  <select value={relationshipTarget} onChange={(event) => setRelationshipTarget(event.target.value)} aria-label="Relationship target" className="min-w-0 rounded-lg border border-white/[0.08] bg-[#0c0e17] px-2 py-2 text-[11px] text-slate-300"><option value="">Target…</option>{entities.map((entity) => <option key={entity.entity_id} value={entity.entity_id}>{entity.entity_name}</option>)}</select>
                </div>
                <div className="grid grid-cols-[1fr_1.1fr] gap-2">
                  <select value={relationshipKind} onChange={(event) => setRelationshipKind(event.target.value as GraphRelationshipType)} aria-label="Relationship type" className="min-w-0 rounded-lg border border-white/[0.08] bg-[#11131d] px-2 py-2 text-[11px] text-slate-300">{GRAPH_RELATIONSHIP_TYPES.map((item) => <option key={item} value={item}>{relationshipLabel(item)}</option>)}</select>
                  <input value={relationshipDescription} onChange={(event) => setRelationshipDescription(event.target.value)} maxLength={500} placeholder="Description (optional)" className="min-w-0 rounded-lg border border-white/[0.08] bg-black/25 px-2 py-2 text-[11px] outline-none focus:border-violet-300/30" />
                </div>
                <button disabled={busy === "relationship" || !relationshipSource || !relationshipTarget} className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-3 py-2 text-[11px] text-slate-300 disabled:opacity-40">{busy === "relationship" ? <LoaderCircle className="animate-spin" size={12} /> : <GitBranch size={12} />} Add relationship</button>
              </form>
              <p className="mt-3 text-[10px] leading-4 text-slate-600">Manual facts are user-confirmed. Deleting an entity archives its relationships but never deletes the underlying memories.</p>
            </section>

            <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
              <div className="flex items-center gap-2"><GitMerge size={14} className="text-amber-200" /><h2 className="text-xs font-medium">Merge history</h2><span className="ml-auto text-[10px] text-slate-600">{merges.length}</span></div>
              {merges.length === 0 ? <p className="mt-2 text-[10px] text-slate-600">No entity merges recorded. Possible duplicates appear in the entity details panel.</p> : <ol className="mt-3 space-y-2">{merges.slice(0, 5).map((merge) => <li key={merge.merge_id} className="rounded-lg border border-white/[0.06] p-2"><p className="text-[10px] text-slate-400">{merge.status === "active" ? "Merged" : "Undone"} · {datetime(merge.created_at)}</p>{merge.status === "active" && <button disabled={busy === `merge-${merge.merge_id}`} onClick={() => void undoMerge(merge.merge_id)} className="mt-1.5 inline-flex items-center gap-1 rounded-md px-2 py-1 text-[9px] text-amber-100 hover:bg-amber-300/[0.08] disabled:opacity-40"><Undo2 size={10} /> Undo merge</button>}</li>)}</ol>}
            </section>

            <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
              <div className="flex items-center gap-2"><Sparkles size={14} className="text-violet-200" /><h2 className="text-xs font-medium">Graph insights</h2><span className="ml-auto text-[10px] text-slate-600">From stored rows</span></div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <label className="block text-[9px] uppercase tracking-[0.12em] text-slate-600">Entity type<select value={insightEntityType} onChange={(event) => setInsightEntityType(event.target.value)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-[#0c0e17] px-2 py-1.5 text-[10px] normal-case tracking-normal text-slate-300"><option value="">All</option>{GRAPH_ENTITY_TYPES.map((item) => <option key={item} value={item}>{entityTypeLabel(item)}</option>)}</select></label>
                <label className="block text-[9px] uppercase tracking-[0.12em] text-slate-600">Relationship<select value={insightRelationshipType} onChange={(event) => setInsightRelationshipType(event.target.value)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-[#0c0e17] px-2 py-1.5 text-[10px] normal-case tracking-normal text-slate-300"><option value="">All</option>{GRAPH_RELATIONSHIP_TYPES.map((item) => <option key={item} value={item}>{relationshipLabel(item)}</option>)}</select></label>
                <label className="block text-[9px] uppercase tracking-[0.12em] text-slate-600">From<input type="date" value={insightFrom} onChange={(event) => setInsightFrom(event.target.value)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-[#0c0e17] px-2 py-1.5 text-[10px] text-slate-300" /></label>
                <label className="block text-[9px] uppercase tracking-[0.12em] text-slate-600">To<input type="date" value={insightTo} onChange={(event) => setInsightTo(event.target.value)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-[#0c0e17] px-2 py-1.5 text-[10px] text-slate-300" /></label>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5 text-[10px]">
                <span className="rounded-full bg-white/[0.04] px-2 py-1 text-slate-400">Pending corrections <strong className="text-slate-200">{insights?.pending_corrections ?? 0}</strong></span>
                <span className="rounded-full bg-white/[0.04] px-2 py-1 text-slate-400">Merges <strong className="text-slate-200">{insights?.merge_count ?? 0}</strong></span>
                <span className={`rounded-full px-2 py-1 ${(insights?.sync_failed ?? 0) > 0 ? "bg-rose-300/[0.08] text-rose-100" : "bg-white/[0.04] text-slate-400"}`}>Sync failed <strong className="text-slate-200">{insights?.sync_failed ?? 0}</strong></span>
                <span className="rounded-full bg-white/[0.04] px-2 py-1 text-slate-400">Sync pending <strong className="text-slate-200">{insights?.sync_pending ?? 0}</strong></span>
              </div>
              <div className="mt-4">
                <p className="text-[9px] uppercase tracking-[0.12em] text-slate-600">Growth (stored entities)</p>
                <div className="mt-2 flex h-12 items-end gap-[2px]" aria-label="Graph growth over time">{growth.map((point) => <span key={point.date} title={`${point.date}: ${point.entities}`} className="min-w-[2px] flex-1 rounded-sm bg-gradient-to-t from-blue-400/40 to-violet-400/80" style={{ height: `${Math.max(4, (point.entities / maxGrowth) * 100)}%` }} />)}</div>
                {growth.length === 0 && <p className="text-[10px] text-slate-600">Growth appears after entities are stored.</p>}
              </div>
              <div className="mt-4 space-y-2">
                <p className="text-[9px] uppercase tracking-[0.12em] text-slate-600">Entity categories</p>
                {typeCounts.slice(0, 6).map(([type, count]) => <div key={type}><div className="flex justify-between text-[10px]"><span className="text-slate-400">{entityTypeLabel(type)}</span><span className="text-slate-600">{count}</span></div><div className="mt-1 h-1 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full bg-gradient-to-r from-violet-400/80 to-blue-400/80" style={{ width: `${Math.max(4, (count / maxTypeCount) * 100)}%` }} /></div></div>)}
                {typeCounts.length === 0 && <p className="text-[10px] text-slate-600">No entities stored yet.</p>}
              </div>
              <div className="mt-4 space-y-2">
                <p className="text-[9px] uppercase tracking-[0.12em] text-slate-600">Most connected</p>
                {(insights?.most_connected_entities ?? []).slice(0, 5).map((entity) => <button key={entity.entity_id} onClick={() => void selectNode(entity.entity_id)} className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-[10px] text-slate-400 hover:bg-white/[0.04] hover:text-slate-200"><span className="truncate">{entity.entity_name}</span><span className="shrink-0 text-slate-600">{entity.degree}</span></button>)}
                {(insights?.most_connected_entities.length ?? 0) === 0 && <p className="text-[10px] text-slate-600">No connected entities yet.</p>}
              </div>
              <div className="mt-4">
                <p className="text-[9px] uppercase tracking-[0.12em] text-slate-600">Recently updated relationships</p>
                <ol className="mt-2 space-y-1.5">{(insights?.recently_updated_relationships ?? []).slice(0, 4).map((relationship) => <li key={relationship.relationship_id} className="rounded-lg bg-white/[0.02] px-2.5 py-1.5 text-[10px] leading-4 text-slate-400"><span className="text-slate-300">{relationship.source_name}</span> {relationshipLabel(relationship.relationship_type)} <span className="text-slate-300">{relationship.target_name}</span><span className="block text-[9px] text-slate-600">{relationship.status} · {datetime(relationship.updated_at)}</span></li>)}</ol>
                {(insights?.recently_updated_relationships.length ?? 0) === 0 && <p className="text-[10px] text-slate-600">No relationships stored yet.</p>}
              </div>
              <div className="mt-4">
                <p className="text-[9px] uppercase tracking-[0.12em] text-slate-600">Isolated entities</p>
                <div className="mt-2 flex flex-wrap gap-1.5">{(insights?.isolated_entities ?? []).slice(0, 8).map((entity) => <button key={entity.entity_id} onClick={() => void selectNode(entity.entity_id)} className="rounded-full border border-white/[0.07] px-2 py-1 text-[9px] text-slate-400 hover:border-violet-300/20 hover:text-violet-100">{entity.entity_name}</button>)}</div>
                {(insights?.isolated_entities.length ?? 0) === 0 && <p className="text-[10px] text-slate-600">Every stored entity has at least one relationship.</p>}
              </div>
            </section>

            <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
              <div className="flex items-center gap-2"><CalendarRange size={14} className="text-blue-200" /><h2 className="text-xs font-medium">Graph construction activity</h2><span className="ml-auto text-[10px] text-slate-600">{activity?.total ?? 0}</span></div>
              {activity && activity.sync_records.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{activity.sync_records.slice(0, 4).map((record) => <span key={record.sync_id} className={`rounded-full px-2 py-1 text-[9px] ${record.status === "failed" ? "bg-rose-300/[0.08] text-rose-100" : record.status === "completed" ? "bg-emerald-300/[0.08] text-emerald-200" : "bg-amber-300/[0.08] text-amber-100"}`}>{record.source_type} · {record.status}</span>)}</div>}
              {(activity?.history.length ?? 0) === 0 ? <p className="mt-2 text-[10px] text-slate-600">No construction activity recorded yet.</p> : <ol className="mt-3 max-h-56 space-y-1.5 overflow-y-auto pr-1">{(activity?.history ?? []).slice(0, 12).map((entry) => <li key={entry.history_id} className="rounded-lg bg-white/[0.02] px-2.5 py-1.5"><p className="text-[10px] leading-4 text-slate-400">{entry.summary}</p><p className="mt-0.5 text-[9px] text-slate-600">{entry.action.replaceAll("_", " ")} · {datetime(entry.created_at)}</p></li>)}</ol>}
              <p className="mt-3 text-[10px] leading-4 text-slate-600">Automated extraction only records relationships that an approved memory supports with explicit language. Ambiguous merges wait for your confirmation.</p>
            </section>
          </aside>
        </section>
      </div>
    </main>
  );
}

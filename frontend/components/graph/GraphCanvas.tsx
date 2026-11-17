"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import {
  entityTypeLabel,
  relationshipLabel,
  type GraphVisualizationEdge,
  type GraphVisualizationNode,
} from "@/lib/graph";

export type GraphNodeData = {
  label: string;
  entityType: string;
  degree: number;
  confidence: number;
  status: string;
  isCenter: boolean;
  active: boolean;
  highlighted: boolean;
  dimmed: boolean;
};

export type EntityFlowNode = Node<GraphNodeData, "entity">;

type CanvasProps = {
  nodes: GraphVisualizationNode[];
  edges: GraphVisualizationEdge[];
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  highlightedNodeIds?: Set<string>;
  highlightedEdgeIds?: Set<string>;
  onNodeSelect: (nodeId: string) => void;
  onEdgeSelect: (edgeId: string) => void;
  onPaneSelect: () => void;
};

const TYPE_COLORS: Record<string, { border: string; background: string; text: string; dot: string }> = {
  person: { border: "rgba(196,181,253,.55)", background: "rgba(139,92,246,.16)", text: "#ede9fe", dot: "#a78bfa" },
  project: { border: "rgba(96,165,250,.55)", background: "rgba(59,130,246,.16)", text: "#dbeafe", dot: "#60a5fa" },
  technology: { border: "rgba(56,189,248,.5)", background: "rgba(14,165,233,.14)", text: "#e0f2fe", dot: "#38bdf8" },
  programming_language: { border: "rgba(34,211,238,.5)", background: "rgba(6,182,212,.13)", text: "#cffafe", dot: "#22d3ee" },
  skill: { border: "rgba(52,211,153,.5)", background: "rgba(16,185,129,.13)", text: "#d1fae5", dot: "#34d399" },
  interest: { border: "rgba(244,114,182,.5)", background: "rgba(236,72,153,.13)", text: "#fce7f3", dot: "#f472b6" },
  goal: { border: "rgba(251,191,36,.5)", background: "rgba(245,158,11,.13)", text: "#fef3c7", dot: "#fbbf24" },
  preference: { border: "rgba(167,139,250,.5)", background: "rgba(124,58,237,.15)", text: "#ede9fe", dot: "#a78bfa" },
  concept: { border: "rgba(129,140,248,.45)", background: "rgba(99,102,241,.12)", text: "#e0e7ff", dot: "#818cf8" },
  tool: { border: "rgba(45,212,191,.5)", background: "rgba(20,184,166,.13)", text: "#ccfbf1", dot: "#2dd4bf" },
  product: { border: "rgba(251,146,60,.5)", background: "rgba(249,115,22,.12)", text: "#ffedd5", dot: "#fb923c" },
  organization: { border: "rgba(148,163,184,.5)", background: "rgba(100,116,139,.14)", text: "#e2e8f0", dot: "#94a3b8" },
  educational_institution: { border: "rgba(125,211,252,.5)", background: "rgba(14,165,233,.12)", text: "#e0f2fe", dot: "#7dd3fc" },
  subject: { border: "rgba(163,230,53,.45)", background: "rgba(132,204,22,.11)", text: "#ecfccb", dot: "#a3e635" },
  location: { border: "rgba(251,113,133,.5)", background: "rgba(244,63,94,.12)", text: "#ffe4e6", dot: "#fb7185" },
  event: { border: "rgba(248,113,113,.5)", background: "rgba(239,68,68,.12)", text: "#fee2e2", dot: "#f87171" },
};

function EntityNodeView({ data, selected }: NodeProps<EntityFlowNode>) {
  const palette = TYPE_COLORS[data.entityType] ?? TYPE_COLORS.concept;
  return (
    <div
      className={`relative w-[178px] rounded-2xl border px-3 py-2.5 text-left shadow-lg backdrop-blur transition ${data.active || selected ? "ring-2 ring-violet-300/60" : ""} ${data.dimmed ? "opacity-25" : "opacity-100"}`}
      style={{ borderColor: data.highlighted ? "#f0abfc" : palette.border, background: palette.background }}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-violet-300/50" />
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-blue-300/50" />
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: palette.dot }} />
        <span className="min-w-0 flex-1 truncate text-[12px] font-medium" style={{ color: palette.text }} title={data.label}>{data.label}</span>
        {data.isCenter && <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[8px] uppercase tracking-wider text-white/70">hub</span>}
      </div>
      <div className="mt-1 flex items-center justify-between gap-2 text-[9px] uppercase tracking-[0.12em] text-slate-400">
        <span className="truncate">{entityTypeLabel(data.entityType)}</span>
        <span className="shrink-0">{data.degree} link{data.degree === 1 ? "" : "s"}</span>
      </div>
      {data.status !== "active" && <p className="mt-1 text-[9px] text-amber-200/80">{data.status.replaceAll("_", " ")}</p>}
    </div>
  );
}

const nodeTypes: NodeTypes = { entity: EntityNodeView };

function layout(nodes: GraphVisualizationNode[]): EntityFlowNode[] {
  const center = nodes.find((node) => node.is_center)
    ?? nodes.find((node) => node.entity_type === "person")
    ?? [...nodes].sort((a, b) => b.degree - a.degree)[0];
  const rest = nodes.filter((node) => node.id !== center?.id).sort((a, b) => b.degree - a.degree || a.label.localeCompare(b.label));
  const positions = new Map<string, { x: number; y: number }>();
  if (center) positions.set(center.id, { x: 0, y: 0 });
  let index = 0;
  let ring = 1;
  let placed = 0;
  while (placed < rest.length) {
    const capacity = 6 + ring * 5;
    const slice = rest.slice(placed, placed + capacity);
    const radius = 250 + (ring - 1) * 210;
    slice.forEach((node, sliceIndex) => {
      const angle = (sliceIndex / slice.length) * Math.PI * 2 - Math.PI / 2;
      positions.set(node.id, {
        x: Math.round(Math.cos(angle) * radius),
        y: Math.round(Math.sin(angle) * radius * 0.72),
      });
      index += 1;
    });
    placed += slice.length;
    ring += 1;
  }
  return nodes.map((node) => {
    const position = positions.get(node.id) ?? { x: index * 40, y: index * 40 };
    return {
      id: node.id,
      type: "entity" as const,
      position,
      // Known card dimensions let React Flow draw edges and fit the view even
      // before the browser reports node measurements.
      initialWidth: 180,
      initialHeight: 62,
      data: {
        label: node.label,
        entityType: node.entity_type,
        degree: node.degree,
        confidence: node.confidence,
        status: node.status,
        isCenter: node.is_center,
        active: false,
        highlighted: false,
        dimmed: false,
      },
    };
  });
}

function toFlowEdges(
  edges: GraphVisualizationEdge[],
  highlighted: Set<string>,
  selectedId: string | null,
): Edge[] {
  return edges.map((edge) => {
    const historical = edge.status === "historical";
    const pending = edge.status === "pending_review";
    const highlightedEdge = highlighted.has(edge.id);
    const selected = selectedId === edge.id;
    const stroke = selected
      ? "#f0abfc"
      : highlightedEdge
        ? "#a78bfa"
        : historical
          ? "#64748b"
          : pending
            ? "#f59e0b"
            : "rgba(148,163,184,.5)";
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: relationshipLabel(edge.relationship_type),
      labelStyle: { fill: "#cbd5e1", fontSize: 9, fontWeight: 500 },
      labelBgStyle: { fill: "#0b0e18", fillOpacity: 0.9 },
      labelBgPadding: [4, 2] as [number, number],
      labelBgBorderRadius: 4,
      animated: highlightedEdge,
      style: {
        stroke,
        strokeWidth: selected ? 2.6 : highlightedEdge ? 2.2 : 1.1,
        strokeDasharray: historical || pending ? "5 4" : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 14, height: 14 },
      data: { status: edge.status },
    };
  });
}

function CanvasInner({
  nodes,
  edges,
  selectedNodeId,
  selectedEdgeId,
  highlightedNodeIds,
  highlightedEdgeIds,
  onNodeSelect,
  onEdgeSelect,
  onPaneSelect,
}: CanvasProps) {
  const initialNodes = useMemo(() => layout(nodes), [nodes]);
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<EntityFlowNode>(initialNodes);
  const initialEdges = useMemo(
    () => toFlowEdges(edges, highlightedEdgeIds ?? new Set(), selectedEdgeId),
    // The explicit dependencies below intentionally preserve node positions while
    // style-only changes are re-applied to the existing nodes.
    [edges, highlightedEdgeIds, selectedEdgeId],
  );
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);
  const { fitView } = useReactFlow();
  const previousSignature = useRef("");

  const signature = useMemo(
    () => `${nodes.map((node) => node.id).sort().join(",")}|${edges.map((edge) => edge.id).sort().join(",")}`,
    [nodes, edges],
  );

  useEffect(() => {
    const changed = previousSignature.current !== signature;
    previousSignature.current = signature;
    setFlowNodes((current) => {
      if (changed) return initialNodes;
      return current.map((node) => ({
        ...node,
        data: {
          ...node.data,
          active: node.id === selectedNodeId,
          highlighted: highlightedNodeIds?.has(node.id) ?? false,
          dimmed: Boolean(highlightedNodeIds?.size) && !(highlightedNodeIds?.has(node.id) ?? false),
        },
      }));
    });
    setFlowEdges(toFlowEdges(edges, highlightedEdgeIds ?? new Set(), selectedEdgeId));
    if (changed) {
      const timer = window.setTimeout(() => { void fitView({ padding: 0.18, duration: 350 }); }, 60);
      return () => window.clearTimeout(timer);
    }
  }, [signature, initialNodes, edges, highlightedNodeIds, highlightedEdgeIds, selectedNodeId, selectedEdgeId, fitView, setFlowNodes, setFlowEdges]);

  const handleNodeClick = useCallback((_: unknown, node: Node) => onNodeSelect(node.id), [onNodeSelect]);
  const handleEdgeClick = useCallback((_: unknown, edge: Edge) => onEdgeSelect(edge.id), [onEdgeSelect]);

  return (
    <div className="h-full w-full overflow-hidden rounded-2xl border border-white/[0.07] bg-[#090b14]">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onEdgeClick={handleEdgeClick}
        onPaneClick={onPaneSelect}
        fitView
        minZoom={0.15}
        maxZoom={2.4}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        panOnDrag
        zoomOnScroll
        proOptions={{ hideAttribution: true }}
        className="mnemora-flow"
      >
        <Background color="#1e2437" gap={22} size={1} />
        <Controls className="!rounded-xl !border !border-white/10 !bg-[#0f1220] !text-slate-300" showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) => {
            const data = node.data as GraphNodeData | undefined;
            return TYPE_COLORS[data?.entityType ?? "concept"]?.dot ?? "#818cf8";
          }}
          maskColor="rgba(8,10,18,.7)"
          className="!rounded-xl !border !border-white/10"
        />
      </ReactFlow>
    </div>
  );
}

export default function GraphCanvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}

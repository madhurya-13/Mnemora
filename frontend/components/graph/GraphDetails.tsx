"use client";

import { useState } from "react";
import { ArrowDownLeft, ArrowUpRight, CalendarClock, Check, Clock3, GitMerge, History, Link2, LoaderCircle, Pencil, RefreshCw, Trash2, X } from "lucide-react";
import { ApiError } from "@/lib/api";
import {
  GRAPH_ENTITY_TYPES,
  GRAPH_RELATIONSHIP_TYPES,
  deleteGraphEntity,
  deleteGraphRelationship,
  entityTypeLabel,
  mergeGraphEntities,
  relationshipLabel,
  updateGraphEntity,
  updateGraphRelationship,
  type GraphEntityDetail,
  type GraphEntityType,
  type GraphHistoryEntry,
  type GraphRelationship,
  type GraphRelationshipStatus,
  type GraphRelationshipType,
} from "@/lib/graph";

const score = (value: number) => `${Math.round(value * 100)}%`;
const shortDate = (value: string | null) => value
  ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
  : "Not recorded";

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "The graph request could not be completed.";
}

function toLocalInput(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function Badge({ children, tone = "slate" }: { children: React.ReactNode; tone?: "slate" | "violet" | "emerald" | "amber" | "rose" | "blue" }) {
  const tones: Record<string, string> = {
    slate: "bg-slate-300/[0.06] text-slate-300",
    violet: "bg-violet-300/[0.08] text-violet-200",
    emerald: "bg-emerald-300/[0.08] text-emerald-200",
    amber: "bg-amber-300/[0.08] text-amber-100",
    rose: "bg-rose-300/[0.08] text-rose-100",
    blue: "bg-blue-300/[0.08] text-blue-200",
  };
  return <span className={`rounded-full px-2 py-1 text-[10px] ${tones[tone]}`}>{children}</span>;
}

type EntityProps = {
  entity: GraphEntityDetail;
  history: GraphHistoryEntry[];
  onClose: () => void;
  onChange: () => void;
  onDeleted: () => void;
  onExpand: (entityId: string) => void;
  onOpenEntity: (entityId: string) => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
};

export function EntityDetails({ entity, history, onClose, onChange, onDeleted, onExpand, onOpenEntity, onError, onNotice }: EntityProps) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState(entity.entity_name);
  const [type, setType] = useState<GraphEntityType>(entity.entity_type);
  const [description, setDescription] = useState(entity.description ?? "");
  const [aliases, setAliases] = useState(entity.aliases.join(", "));
  const [confidence, setConfidence] = useState(entity.confidence);
  const [status, setStatus] = useState<"active" | "pending_review" | "archived">(
    entity.status === "merged" ? "archived" : entity.status,
  );

  async function save() {
    setBusy(true);
    try {
      await updateGraphEntity(entity.entity_id, {
        entity_name: name.trim(),
        entity_type: type,
        description: description.trim() || null,
        aliases: aliases.split(",").map((item) => item.trim()).filter(Boolean),
        confidence,
        status,
      });
      setEditing(false);
      onNotice(`Updated ${name.trim()}.`);
      onChange();
    } catch (caught) { onError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!window.confirm(`Delete ${entity.entity_name}? Connected relationships are archived; the source memories are kept.`)) return;
    setBusy(true);
    try {
      const result = await deleteGraphEntity(entity.entity_id);
      onNotice(`Deleted ${entity.entity_name}. ${result.relationships_archived} relationship(s) archived; no memories were deleted.`);
      onDeleted();
    } catch (caught) { onError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  async function merge(candidateId: string, candidateName: string, confirmSimilar: boolean) {
    if (!window.confirm(`Merge “${candidateName}” into “${entity.entity_name}”? Relationships and evidence move to the primary entity and the merge can be undone.`)) return;
    setBusy(true);
    try {
      const result = await mergeGraphEntities(entity.entity_id, candidateId, confirmSimilar);
      onNotice(`Merged ${candidateName}: ${result.moved_relationships} relationship(s) moved, ${result.collapsed_relationships} duplicate(s) collapsed. The merge can be undone.`);
      onChange();
    } catch (caught) { onError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  const incoming = entity.connections.filter((connection) => connection.direction === "incoming");
  const outgoing = entity.connections.filter((connection) => connection.direction === "outgoing");

  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[10px] uppercase tracking-[0.18em] text-violet-200/70">{entityTypeLabel(entity.entity_type)} · Entity</p>
          <h2 id="graph-details-title" className="mt-1.5 truncate text-lg font-medium">{entity.entity_name}</h2>
        </div>
        <button onClick={onClose} aria-label="Close details" className="rounded-lg p-2 text-slate-500 hover:bg-white/[0.05]"><X size={16} /></button>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge tone={entity.status === "active" ? "emerald" : "amber"}>{entity.status.replaceAll("_", " ")}</Badge>
        <Badge tone="violet">Confidence {score(entity.confidence)}</Badge>
        {entity.incoming_count > 0 && <Badge tone="blue">{entity.incoming_count} in</Badge>}
        {entity.outgoing_count > 0 && <Badge tone="slate">{entity.outgoing_count} out</Badge>}
      </div>

      {!editing ? (
        <>
          <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-300">{entity.description || "No description stored for this entity."}</p>
          {entity.aliases.length > 0 && <p className="mt-3 text-[11px] text-slate-500">Also known as: <span className="text-slate-300">{entity.aliases.join(", ")}</span></p>}
          <div className="mt-4 grid grid-cols-2 gap-2 rounded-xl border border-white/[0.06] bg-black/15 p-3 text-[10px] text-slate-500">
            <span>First seen<strong className="mt-1 block text-[11px] font-normal text-slate-300">{shortDate(entity.first_observed_at)}</strong></span>
            <span>Last seen<strong className="mt-1 block text-[11px] font-normal text-slate-300">{shortDate(entity.last_observed_at)}</strong></span>
            <span>Source memories<strong className="mt-1 block text-[11px] font-normal text-slate-300">{entity.source_memory_ids.length}</strong></span>
            <span>Evidence links<strong className="mt-1 block text-[11px] font-normal text-slate-300">{new Set(entity.connections.flatMap((connection) => connection.evidence_memory_ids)).size}</strong></span>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button onClick={() => setEditing(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-2.5 py-2 text-[11px] text-slate-300 hover:border-violet-300/20 hover:text-violet-100"><Pencil size={12} /> Edit entity</button>
            <button onClick={() => onExpand(entity.entity_id)} className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-2.5 py-2 text-[11px] text-slate-300 hover:border-blue-300/20 hover:text-blue-100"><RefreshCw size={12} /> Expand connections</button>
            <button disabled={busy} onClick={() => void remove()} className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-[11px] text-rose-200/70 hover:bg-rose-300/[0.07] hover:text-rose-100 disabled:opacity-40"><Trash2 size={12} /> Delete</button>
          </div>
        </>
      ) : (
        <div className="mt-4 space-y-3">
          <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Name<input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-black/25 px-3 py-2 text-sm normal-case tracking-normal text-slate-200 outline-none focus:border-violet-300/30" /></label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Type<select value={type} onChange={(event) => setType(event.target.value as GraphEntityType)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-[#11131d] px-3 py-2 text-sm normal-case tracking-normal text-slate-300">{GRAPH_ENTITY_TYPES.map((item) => <option key={item} value={item}>{entityTypeLabel(item)}</option>)}</select></label>
            <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Status<select value={status} onChange={(event) => setStatus(event.target.value as typeof status)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-[#11131d] px-3 py-2 text-sm normal-case tracking-normal text-slate-300"><option value="active">Active</option><option value="pending_review">Pending review</option><option value="archived">Archived</option></select></label>
          </div>
          <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} maxLength={2000} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-black/25 px-3 py-2 text-sm normal-case tracking-normal text-slate-200 outline-none focus:border-violet-300/30" /></label>
          <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Aliases (comma separated)<input value={aliases} onChange={(event) => setAliases(event.target.value)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-black/25 px-3 py-2 text-sm normal-case tracking-normal text-slate-200 outline-none focus:border-violet-300/30" /></label>
          <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Confidence {score(confidence)}<input type="range" min={0} max={1} step={0.01} value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} className="mt-2 w-full accent-violet-400" /></label>
          <div className="flex gap-2"><button disabled={busy || !name.trim()} onClick={() => void save()} className="inline-flex items-center gap-1.5 rounded-lg bg-violet-400/15 px-3 py-2 text-[11px] text-violet-100 disabled:opacity-40">{busy ? <LoaderCircle className="animate-spin" size={12} /> : <Check size={12} />} Save changes</button><button onClick={() => setEditing(false)} className="rounded-lg px-3 py-2 text-[11px] text-slate-500 hover:bg-white/[0.05]">Cancel</button></div>
        </div>
      )}

      {entity.possible_duplicates.length > 0 && (
        <section className="mt-5 rounded-xl border border-amber-200/10 bg-amber-200/[0.03] p-3">
          <div className="flex items-center gap-2"><GitMerge size={13} className="text-amber-200" /><h3 className="text-xs font-medium text-amber-100">Possible duplicates</h3></div>
          <p className="mt-1 text-[10px] leading-4 text-amber-100/60">Only merge when the evidence shows these are the same thing. Every merge is recorded and can be undone.</p>
          <div className="mt-2 space-y-2">{entity.possible_duplicates.map((candidate) => <div key={candidate.entity_id} className="rounded-lg border border-white/[0.06] p-2"><div className="flex items-center justify-between gap-2"><button onClick={() => onOpenEntity(candidate.entity_id)} className="truncate text-left text-[11px] text-slate-200 hover:text-violet-100">{candidate.entity_name}</button><span className="text-[9px] text-slate-500">{score(candidate.similarity)}</span></div><p className="mt-1 text-[9px] leading-4 text-slate-500">{candidate.reason}</p><button disabled={busy} onClick={() => void merge(candidate.entity_id, candidate.entity_name, !candidate.same_type || candidate.similarity < 0.8)} className="mt-2 rounded-md bg-amber-300/[0.08] px-2 py-1 text-[9px] text-amber-100 disabled:opacity-40">Merge into {entity.entity_name}</button></div>)}</div>
        </section>
      )}

      <section className="mt-5">
        <div className="flex items-center gap-2"><Link2 size={13} className="text-violet-200" /><h3 className="text-xs font-medium">Connections</h3><span className="ml-auto text-[10px] text-slate-600">{entity.connections.length} total</span></div>
        {entity.connections.length === 0 ? <p className="mt-2 text-xs text-slate-600">No relationships stored yet.</p> : (
          <div className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
            {[...outgoing, ...incoming].map((connection) => (
              <div key={`${connection.relationship_id}-${connection.direction}`} className="rounded-lg border border-white/[0.06] bg-black/15 p-2.5">
                <div className="flex items-center gap-1.5 text-[11px]">
                  {connection.direction === "outgoing" ? <ArrowUpRight size={12} className="shrink-0 text-blue-300" /> : <ArrowDownLeft size={12} className="shrink-0 text-emerald-300" />}
                  <span className="text-slate-500">{connection.direction === "outgoing" ? "this" : connection.entity.entity_name}</span>
                  <span className="text-violet-200/80">{relationshipLabel(connection.relationship_type)}</span>
                  {connection.direction === "outgoing" ? <button onClick={() => onOpenEntity(connection.entity.entity_id)} className="truncate text-left text-slate-200 hover:text-violet-100">{connection.entity.entity_name}</button> : <span className="text-slate-500">this</span>}
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5"><Badge tone={connection.status === "active" ? "emerald" : connection.status === "historical" ? "slate" : "amber"}>{connection.status.replaceAll("_", " ")}</Badge><span className="text-[9px] text-slate-500">Confidence {score(connection.confidence)}</span>{connection.evidence_memory_ids.length > 0 && <span className="text-[9px] text-slate-600">· {connection.evidence_memory_ids.length} evidence</span>}</div>
                {(connection.valid_from || connection.valid_until) && <p className="mt-1 text-[9px] text-slate-600">{connection.valid_from ? shortDate(connection.valid_from) : "unknown start"} → {connection.valid_until ? shortDate(connection.valid_until) : "current"}</p>}
              </div>
            ))}
          </div>
        )}
      </section>

      {entity.source_memory_ids.length > 0 && (
        <section className="mt-4 rounded-xl border border-white/[0.06] p-3">
          <div className="flex items-center gap-2"><History size={12} className="text-blue-200" /><h3 className="text-xs font-medium">Supporting memories</h3></div>
          <p className="mt-1 text-[10px] leading-4 text-slate-500">These memory records are the evidence for this entity. Delete or edit them on the <a href="/memory" className="text-violet-300 hover:text-violet-200">Memory page</a>.</p>
          <ul className="mt-2 space-y-1">{entity.source_memory_ids.slice(0, 8).map((id) => <li key={id} className="truncate font-mono text-[9px] text-slate-600">{id}</li>)}</ul>
        </section>
      )}

      <section className="mt-4">
        <div className="flex items-center gap-2"><Clock3 size={12} className="text-slate-400" /><h3 className="text-xs font-medium">Change activity</h3></div>
        {history.length === 0 ? <p className="mt-2 text-[10px] text-slate-600">No recorded changes for this entity.</p> : <ol className="mt-2 space-y-1.5">{history.slice(0, 6).map((entry) => <li key={entry.history_id} className="rounded-lg bg-white/[0.02] px-2.5 py-2"><p className="text-[10px] leading-4 text-slate-400">{entry.summary}</p><p className="mt-0.5 text-[9px] text-slate-600">{entry.action.replaceAll("_", " ")} · {shortDate(entry.created_at)}</p></li>)}</ol>}
      </section>
    </>
  );
}

type RelationshipProps = {
  relationship: GraphRelationship;
  loading: boolean;
  onClose: () => void;
  onChange: () => void;
  onDeleted: () => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
};

export function RelationshipDetails({ relationship, loading, onClose, onChange, onDeleted, onError, onNotice }: RelationshipProps) {
  const [busy, setBusy] = useState(false);
  const [type, setType] = useState<GraphRelationshipType>(relationship.relationship_type);
  const [description, setDescription] = useState(relationship.description ?? "");
  const [confidence, setConfidence] = useState(relationship.confidence);
  const [status, setStatus] = useState<GraphRelationshipStatus>(relationship.status);
  const [validUntil, setValidUntil] = useState(toLocalInput(relationship.valid_until));

  async function save() {
    setBusy(true);
    try {
      await updateGraphRelationship(relationship.relationship_id, {
        relationship_type: type,
        description: description.trim() || null,
        confidence,
        status,
        valid_until: validUntil ? new Date(validUntil).toISOString() : null,
      });
      onNotice("Relationship updated. Historical facts remain stored.");
      onChange();
    } catch (caught) { onError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!window.confirm("Remove this relationship from the active graph? It will be archived, not hard-deleted.")) return;
    setBusy(true);
    try {
      await deleteGraphRelationship(relationship.relationship_id);
      onNotice("Relationship archived.");
      onDeleted();
    } catch (caught) { onError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <div><p className="text-[10px] uppercase tracking-[0.18em] text-violet-200/70">Relationship</p><h2 id="graph-details-title" className="mt-1.5 text-lg font-medium">{relationshipLabel(relationship.relationship_type)}</h2></div>
        <button onClick={onClose} aria-label="Close details" className="rounded-lg p-2 text-slate-500 hover:bg-white/[0.05]"><X size={16} /></button>
      </div>
      {loading ? <div className="flex items-center gap-2 py-8 text-xs text-slate-500"><LoaderCircle className="animate-spin" size={14} /> Loading relationship</div> : (
        <>
          <div className="mt-4 rounded-xl border border-white/[0.06] bg-black/15 p-3 text-xs leading-6 text-slate-300">
            <span className="text-slate-500">Source:</span> {relationship.source_entity_name ?? relationship.source_entity_id}<br />
            <span className="text-slate-500">Target:</span> {relationship.target_entity_name ?? relationship.target_entity_id}
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Badge tone={relationship.status === "active" ? "emerald" : relationship.status === "historical" ? "slate" : "amber"}>{relationship.status.replaceAll("_", " ")}</Badge>
            <Badge tone="violet">Confidence {score(relationship.confidence)}</Badge>
            <Badge tone="blue">{relationship.evidence_memory_ids.length} evidence</Badge>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl border border-white/[0.06] p-3 text-[10px] text-slate-500">
            <span className="inline-flex items-center gap-1"><CalendarClock size={11} /> Valid from<strong className="mt-1 block text-[11px] font-normal text-slate-300">{shortDate(relationship.valid_from)}</strong></span>
            <span className="inline-flex items-center gap-1"><CalendarClock size={11} /> Valid until<strong className="mt-1 block text-[11px] font-normal text-slate-300">{shortDate(relationship.valid_until)}</strong></span>
          </div>
          {relationship.evidence.length > 0 && <div className="mt-3 rounded-xl border border-white/[0.06] p-3"><h3 className="text-xs font-medium">Evidence</h3><ul className="mt-2 space-y-1.5">{relationship.evidence.slice(0, 6).map((item, index) => <li key={index} className="text-[10px] leading-4 text-slate-500">{typeof item.excerpt === "string" ? item.excerpt : "Stored evidence"}<span className="ml-1 text-slate-600">({String(item.kind ?? "memory")})</span></li>)}</ul></div>}
          {relationship.evidence_memory_ids.length > 0 && <p className="mt-2 break-all font-mono text-[9px] text-slate-600">Memories: {relationship.evidence_memory_ids.join(", ")}</p>}

          <div className="mt-4 space-y-3">
            <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Type<select value={type} onChange={(event) => setType(event.target.value as GraphRelationshipType)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-[#11131d] px-3 py-2 text-sm normal-case tracking-normal text-slate-300">{GRAPH_RELATIONSHIP_TYPES.map((item) => <option key={item} value={item}>{relationshipLabel(item)}</option>)}</select></label>
            <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Description<input value={description} onChange={(event) => setDescription(event.target.value)} maxLength={500} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-black/25 px-3 py-2 text-sm normal-case tracking-normal text-slate-200 outline-none focus:border-violet-300/30" /></label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Status<select value={status} onChange={(event) => setStatus(event.target.value as GraphRelationshipStatus)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-[#11131d] px-3 py-2 text-sm normal-case tracking-normal text-slate-300"><option value="active">Active</option><option value="pending_review">Pending review</option><option value="historical">Historical</option><option value="rejected">Rejected</option><option value="archived">Archived</option></select></label>
              <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Valid until<input type="datetime-local" value={validUntil} onChange={(event) => setValidUntil(event.target.value)} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-black/25 px-2 py-2 text-[11px] text-slate-300 outline-none focus:border-violet-300/30" /></label>
            </div>
            <label className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Confidence {score(confidence)}<input type="range" min={0} max={1} step={0.01} value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} className="mt-2 w-full accent-violet-400" /></label>
            <div className="flex gap-2"><button disabled={busy} onClick={() => void save()} className="inline-flex items-center gap-1.5 rounded-lg bg-violet-400/15 px-3 py-2 text-[11px] text-violet-100 disabled:opacity-40">{busy ? <LoaderCircle className="animate-spin" size={12} /> : <Check size={12} />} Save correction</button><button disabled={busy} onClick={() => void remove()} className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-[11px] text-rose-200/70 hover:bg-rose-300/[0.07] hover:text-rose-100 disabled:opacity-40"><Trash2 size={12} /> Archive</button></div>
          </div>
        </>
      )}
    </>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, Check, Clock3, Database, Eye, LoaderCircle, Plus, Search, Sparkles, Trash2, X } from "lucide-react";
import { ApiError, requestJson } from "@/lib/api";
import {
  approveMemory, createMemory, deleteMemory, getMemoryConflicts, getMemoryHistory, getMemoryStats, getRetrievalStats, listMemories, rejectMemory,
  resolveMemoryConflict, searchMemories, updateMemory, type Memory, type MemoryCategory, type MemorySearchResult, type MemoryStats, type MemoryConflict, type RetrievalStats,
} from "@/lib/memories";

const categories: MemoryCategory[] = ["personal", "education", "career", "interests", "preferences", "projects", "goals", "temporary", "other"];
const label = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);
const date = (value: string) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "The memory request could not be completed.";
}

function score(value: number) { return `${Math.round(value * 100)}%`; }

export default function MemoryDashboard() {
  const [items, setItems] = useState<Memory[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MemorySearchResult[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<Memory | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState(false);
  const [newContent, setNewContent] = useState("");
  const [newCategory, setNewCategory] = useState<MemoryCategory>("preferences");
  const [conflicts, setConflicts] = useState<MemoryConflict[]>([]);
  const [retrievalStats, setRetrievalStats] = useState<RetrievalStats | null>(null);
  const [minimumImportance, setMinimumImportance] = useState(0);
  const [sortBy, setSortBy] = useState("relevance");
  const [history, setHistory] = useState<{ history_id: string; content: string; change_reason: string; created_at: string }[]>([]);

  const refresh = useCallback(async () => {
    try {
      const [page, nextStats, conflictPage, retrieval] = await Promise.all([
        listMemories({ category: category || undefined, approval_status: status || undefined }),
        getMemoryStats(),
        getMemoryConflicts(),
        getRetrievalStats(),
      ]);
      setError(null);
      setItems(page.items);
      setStats(nextStats);
      setConflicts(conflictPage.items.filter((item) => item.status === "unresolved"));
      setRetrievalStats(retrieval);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [category, status]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refresh(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  const visibleItems = useMemo(() => searchResults?.map((result) => result.memory) ?? items, [items, searchResults]);

  async function runSearch(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setError(null);
    try {
      const result = await searchMemories(query.trim(), { category: category || undefined, min_importance: minimumImportance || undefined, sort_by: sortBy });
      setSearchResults(result.results);
    } catch (caught) { setError(errorMessage(caught)); }
  }

  async function resolveConflict(conflict: MemoryConflict, resolution: "keep_existing" | "accept_update") {
    setBusyId(conflict.conflict_id);
    try {
      await resolveMemoryConflict(conflict.conflict_id, resolution);
      setNotice(resolution === "keep_existing" ? "Kept the existing memory; conflict resolved." : "Accepted the update; the previous version remains in history.");
      await refresh();
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusyId(null); }
  }

  async function showHistory(memory: Memory) {
    setSelected(memory);
    try { setHistory(await getMemoryHistory(memory.memory_id)); }
    catch { setHistory([]); }
  }

  async function perform(id: string, action: "approve" | "reject" | "delete") {
    if (action === "delete" && !window.confirm("Delete this memory permanently?")) return;
    setBusyId(id);
    setError(null);
    setNotice(null);
    try {
      if (action === "approve") {
        const memory = await approveMemory(id);
        setNotice(memory.vector_sync_status === "synced" ? "Memory approved and indexed." : "Approval was saved; vector indexing is pending. Check the OpenAI embedding configuration.");
      } else if (action === "reject") {
        await rejectMemory(id);
        setNotice("Memory rejected.");
      } else {
        const result = await deleteMemory(id);
        setNotice(result.vector_cleanup_pending ? "Memory was removed; vector cleanup is queued for retry." : "Memory deleted.");
        if (selected?.memory_id === id) setSelected(null);
      }
      setSearchResults(null);
      await refresh();
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusyId(null); }
  }

  async function saveEdit(id: string) {
    setBusyId(id);
    try {
      await updateMemory(id, { content: draft });
      setEditingId(null);
      setNotice("Memory updated.");
      setSearchResults(null);
      await refresh();
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusyId(null); }
  }

  async function addMemory(event: React.FormEvent) {
    event.preventDefault();
    if (!newContent.trim()) return;
    setBusyId("new");
    try {
      await createMemory({ content: newContent.trim(), category: newCategory, importance: 0.7, confidence: 1, memory_type: newCategory === "temporary" ? "temporary" : "stable" });
      setNewContent("");
      setAdding(false);
      setNotice("Memory saved for your approval.");
      await refresh();
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusyId(null); }
  }

  async function retryExtraction() {
    try {
      const result = await requestJson<{ queued: number }>("/api/v1/memories/extractions/retry", { method: "POST" });
      setNotice(result.queued ? `Queued ${result.queued} extraction job(s) for retry.` : "There are no failed extraction jobs to retry.");
      await refresh();
    } catch (caught) { setError(errorMessage(caught)); }
  }

  const categoryCounts = stats?.categories ?? {};
  const categoryMax = Math.max(1, ...Object.values(categoryCounts));

  return <main className="min-h-dvh bg-[#080a12] text-slate-100">
    <header className="sticky top-0 z-20 border-b border-white/[0.07] bg-[#0a0c15]/95 px-4 py-4 backdrop-blur sm:px-8">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
        <div className="flex items-center gap-3"><Link href="/" className="rounded-lg p-2 text-slate-400 transition hover:bg-white/[0.06] hover:text-white" aria-label="Back to chat"><ArrowLeft size={18} /></Link><span className="grid h-10 w-10 place-items-center rounded-xl border border-violet-300/20 bg-violet-400/10 text-violet-200"><Database size={19} /></span><div><h1 className="text-lg font-medium">Memory</h1><p className="text-xs text-slate-500">Long-term context you control</p></div></div>
        <Link href="/" className="rounded-xl border border-white/[0.08] px-3 py-2 text-xs text-slate-300 transition hover:border-violet-300/20 hover:text-violet-100">Return to chat</Link>
      </div>
    </header>

    <div className="mx-auto max-w-7xl space-y-6 px-4 py-7 sm:px-8">
      {error && <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-300/15 bg-rose-300/[0.06] px-4 py-3 text-sm text-rose-100"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><span>{error}</span><button onClick={() => setError(null)} className="ml-auto text-rose-200/70" aria-label="Dismiss error"><X size={16} /></button></div>}
      {notice && <div role="status" className="rounded-xl border border-emerald-300/10 bg-emerald-300/[0.04] px-4 py-3 text-sm text-emerald-100/90">{notice}</div>}
      {stats && !stats.semantic_search_available && <div className="rounded-xl border border-amber-300/15 bg-amber-300/[0.05] px-4 py-3 text-xs leading-5 text-amber-100/90"><strong>Semantic indexing needs a configured embedding provider.</strong> Configure the selected provider in <code>backend/.env</code> to enable embeddings, semantic search and approved memory retrieval. Pending memories remain editable and are not used in chat.</div>}
      {stats && !stats.vector_index_available && <div role="alert" className="rounded-xl border border-rose-300/15 bg-rose-300/[0.05] px-4 py-3 text-xs leading-5 text-rose-100/90"><strong>ChromaDB is unavailable on this backend.</strong> Memory records remain in SQL, but vectors cannot be indexed or searched until the Chroma runtime can load.</div>}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Memory statistics">
        {[["All memories", stats?.total], ["Approved", stats?.approved], ["Awaiting approval", stats?.pending], ["Index sync pending", stats?.vector_sync_pending]].map(([title, value]) => <div key={String(title)} className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-5"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">{title}</p><p className="mt-3 text-3xl font-light text-slate-100">{loading ? "—" : value}</p></div>)}
      </section>

      <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-5">
          <form onSubmit={runSearch} className="flex gap-2 rounded-2xl border border-white/[0.08] bg-white/[0.025] p-2 focus-within:border-violet-300/25">
            <Search className="ml-2 mt-2.5 shrink-0 text-slate-500" size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search memories by meaning…" className="min-w-0 flex-1 bg-transparent px-2 py-2 text-sm outline-none placeholder:text-slate-600" /><button className="rounded-xl bg-violet-400/15 px-4 text-xs text-violet-100 transition hover:bg-violet-400/25">Search</button>
          </form>
          <div className="flex flex-wrap gap-2 text-xs"><select aria-label="Minimum importance" value={minimumImportance} onChange={(event) => setMinimumImportance(Number(event.target.value))} className="rounded-xl border border-white/[0.08] bg-[#0c0e17] px-3 py-2 text-slate-300"><option value={0}>Any importance</option><option value={0.5}>Importance 50%+</option><option value={0.75}>Importance 75%+</option><option value={0.9}>Importance 90%+</option></select><select aria-label="Search result order" value={sortBy} onChange={(event) => setSortBy(event.target.value)} className="rounded-xl border border-white/[0.08] bg-[#0c0e17] px-3 py-2 text-slate-300"><option value="relevance">Sort: relevance</option><option value="importance">Sort: importance</option><option value="updated_at">Sort: recently updated</option><option value="created_at">Sort: recently added</option></select></div>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-base font-medium">Your memories</h2><p className="mt-1 text-xs text-slate-500">Approved memories can help personalize future replies.</p></div>
            <button onClick={() => { setAdding((value) => !value); setNotice(null); }} className="inline-flex items-center gap-2 rounded-xl border border-violet-300/15 bg-violet-300/[0.07] px-3 py-2.5 text-xs text-violet-100 hover:bg-violet-300/[0.12]"><Plus size={15} /> Add memory</button>
          </div>

          {adding && <form onSubmit={addMemory} className="grid gap-3 rounded-2xl border border-violet-300/15 bg-violet-300/[0.035] p-4 sm:grid-cols-[1fr_170px_auto]"><input value={newContent} onChange={(event) => setNewContent(event.target.value)} maxLength={2000} placeholder="A useful fact to remember" className="rounded-lg border border-white/[0.08] bg-black/20 px-3 py-2 text-sm outline-none focus:border-violet-300/30" /><select value={newCategory} onChange={(event) => setNewCategory(event.target.value as MemoryCategory)} className="rounded-lg border border-white/[0.08] bg-[#11131d] px-3 py-2 text-sm text-slate-300">{categories.map((item) => <option key={item} value={item}>{label(item)}</option>)}</select><button disabled={busyId === "new"} className="rounded-lg bg-violet-400/15 px-4 py-2 text-xs text-violet-100 disabled:opacity-50">Save for review</button></form>}

          <div className="flex flex-wrap gap-2">
            <select value={status} onChange={(event) => { setStatus(event.target.value); setSearchResults(null); }} aria-label="Filter by approval status" className="rounded-xl border border-white/[0.08] bg-[#0c0e17] px-3 py-2 text-xs text-slate-300"><option value="">All status</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select>
            <select value={category} onChange={(event) => { setCategory(event.target.value); setSearchResults(null); }} aria-label="Filter by category" className="rounded-xl border border-white/[0.08] bg-[#0c0e17] px-3 py-2 text-xs text-slate-300"><option value="">All categories</option>{categories.map((item) => <option key={item} value={item}>{label(item)}</option>)}</select>
            {searchResults !== null && <button onClick={() => setSearchResults(null)} className="rounded-xl px-3 py-2 text-xs text-violet-200 hover:bg-white/[0.05]">Clear semantic search</button>}
          </div>

          {loading ? <div className="flex items-center justify-center gap-2 py-14 text-sm text-slate-500"><LoaderCircle className="animate-spin" size={17} /> Loading memories</div>
            : visibleItems.length === 0 ? <div className="rounded-2xl border border-dashed border-white/[0.09] px-6 py-14 text-center"><Sparkles className="mx-auto text-violet-200/70" size={22} /><p className="mt-3 text-sm text-slate-300">{searchResults ? "No relevant approved memories found." : "No memories match these filters."}</p><p className="mt-1 text-xs text-slate-600">New conversation memories will appear here for review.</p></div>
              : <div className="grid gap-3 xl:grid-cols-2">{visibleItems.map((memory) => {
                const relevance = searchResults?.find((result) => result.memory.memory_id === memory.memory_id);
                return <article key={memory.memory_id} className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4 transition hover:border-violet-300/15">
                  <div className="flex flex-wrap items-center gap-2"><span className="rounded-full border border-violet-300/10 bg-violet-300/[0.06] px-2.5 py-1 text-[10px] text-violet-200/80">{label(memory.category)}</span><span className={`rounded-full px-2.5 py-1 text-[10px] ${memory.approval_status === "approved" ? "bg-emerald-300/[0.08] text-emerald-200" : memory.approval_status === "pending" ? "bg-amber-300/[0.08] text-amber-100" : "bg-slate-300/[0.06] text-slate-400"}`}>{label(memory.approval_status)}</span>{memory.vector_sync_status === "failed" && <span className="text-[10px] text-rose-200">Index sync failed</span>}{relevance && <span className="ml-auto text-[10px] text-slate-500">Match {score(relevance.similarity)}</span>}</div>
                  {editingId === memory.memory_id ? <textarea value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={2000} className="mt-4 min-h-24 w-full rounded-xl border border-violet-300/20 bg-black/20 p-3 text-sm leading-6 text-slate-200 outline-none" /> : <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-200">{memory.content}</p>}
                  {relevance && <div className="mt-3 rounded-lg border border-violet-300/[0.08] bg-violet-300/[0.025] p-3 text-[10px] leading-5 text-slate-400"><p>{relevance.retrieval_reason}</p><p className="mt-1 text-slate-500">Semantic {score(relevance.score_components.semantic ?? relevance.similarity)} · Keyword {score(relevance.keyword_score)} · Importance {score(relevance.score_components.importance ?? memory.importance)} · Recency {score(relevance.recency_score)}</p></div>}
                  <div className="mt-4 grid grid-cols-2 gap-2 text-[10px] text-slate-500"><span>Importance <strong className="ml-1 font-medium text-slate-300">{score(memory.importance)}</strong></span><span>Confidence <strong className="ml-1 font-medium text-slate-300">{score(memory.confidence)}</strong></span><span>Created {date(memory.created_at)}</span><span>Updated {date(memory.updated_at)}</span></div>
                  <div className="mt-4 flex flex-wrap items-center gap-1 border-t border-white/[0.06] pt-3">
                    <button onClick={() => void showHistory(memory)} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-[11px] text-slate-400 hover:bg-white/[0.05] hover:text-slate-100"><Eye size={13} /> View history</button>
                    {editingId === memory.memory_id ? <><button disabled={busyId === memory.memory_id} onClick={() => void saveEdit(memory.memory_id)} className="rounded-lg px-2.5 py-2 text-[11px] text-violet-200 hover:bg-violet-300/[0.08]">Save edit</button><button onClick={() => setEditingId(null)} className="rounded-lg px-2.5 py-2 text-[11px] text-slate-500 hover:bg-white/[0.05]">Cancel</button></> : <button onClick={() => { setEditingId(memory.memory_id); setDraft(memory.content); }} className="rounded-lg px-2.5 py-2 text-[11px] text-slate-400 hover:bg-white/[0.05] hover:text-slate-100">Edit</button>}
                    {memory.approval_status === "pending" && <><button disabled={busyId === memory.memory_id} onClick={() => void perform(memory.memory_id, "approve")} className="inline-flex items-center gap-1 rounded-lg px-2.5 py-2 text-[11px] text-emerald-200 hover:bg-emerald-300/[0.08]"><Check size={13} /> Approve</button><button disabled={busyId === memory.memory_id} onClick={() => void perform(memory.memory_id, "reject")} className="rounded-lg px-2.5 py-2 text-[11px] text-amber-100/80 hover:bg-amber-300/[0.06]">Reject</button></>}
                    <button disabled={busyId === memory.memory_id} onClick={() => void perform(memory.memory_id, "delete")} className="ml-auto inline-flex items-center gap-1 rounded-lg px-2.5 py-2 text-[11px] text-rose-200/70 hover:bg-rose-300/[0.07] hover:text-rose-100"><Trash2 size={13} /> Delete</button>
                  </div>
                </article>;
              })}</div>}
        </div>

        <aside className="space-y-4">
          <section className="rounded-2xl border border-amber-200/[0.08] bg-white/[0.025] p-5"><div className="flex items-center gap-2"><AlertTriangle size={15} className="text-amber-200" /><h2 className="text-sm font-medium">Memory conflicts</h2><span className="ml-auto rounded-full bg-amber-300/[0.08] px-2 py-1 text-[10px] text-amber-100">{conflicts.length}</span></div>{conflicts.length ? <div className="mt-4 space-y-4">{conflicts.map((conflict) => <div key={conflict.conflict_id} className="rounded-xl border border-amber-200/[0.08] p-3"><p className="text-[11px] leading-5 text-slate-300">{conflict.summary}</p><p className="mt-2 text-[10px] text-slate-500">Current: {conflict.existing_memory.content}</p><p className="mt-1 text-[10px] text-slate-500">Proposed: {conflict.new_memory.content}</p><div className="mt-3 flex gap-2"><button disabled={busyId === conflict.conflict_id} onClick={() => void resolveConflict(conflict, "keep_existing")} className="rounded-lg bg-white/[0.05] px-2 py-1.5 text-[10px] text-slate-300 disabled:opacity-50">Keep current</button><button disabled={busyId === conflict.conflict_id} onClick={() => void resolveConflict(conflict, "accept_update")} className="rounded-lg bg-violet-300/[0.08] px-2 py-1.5 text-[10px] text-violet-100 disabled:opacity-50">Accept update</button></div></div>)}</div> : <p className="mt-3 text-xs text-slate-600">No unresolved conflicts.</p>}</section>
          <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-5"><div className="flex items-center gap-2"><Sparkles size={15} className="text-violet-200" /><h2 className="text-sm font-medium">Retrieval insights</h2></div><div className="mt-4 grid grid-cols-2 gap-3 text-[10px] text-slate-500"><span>Retrievals<strong className="mt-1 block text-lg font-light text-slate-200">{retrievalStats?.retrieval_count ?? 0}</strong></span><span>Selected<strong className="mt-1 block text-lg font-light text-slate-200">{retrievalStats?.selected_count ?? 0}</strong></span><span>Excluded<strong className="mt-1 block text-lg font-light text-slate-200">{retrievalStats?.excluded_count ?? 0}</strong></span><span>Avg. latency<strong className="mt-1 block text-lg font-light text-slate-200">{Math.round(retrievalStats?.average_latency_ms ?? 0)}ms</strong></span></div><div className="mt-4 space-y-2">{retrievalStats?.recent_events.slice(0, 4).map((event) => <div key={event.event_id} className="rounded-lg bg-black/10 p-2 text-[10px] text-slate-500"><span className="text-slate-300">{label(event.query_type.replaceAll("_", " "))}</span> · {event.selected_count}/{event.candidate_count} selected</div>)}</div></section>
          <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-5"><div className="flex items-center gap-2"><Sparkles size={15} className="text-violet-200" /><h2 className="text-sm font-medium">Category overview</h2></div><p className="mt-1 text-xs text-slate-600">Counts from your stored memories</p><div className="mt-5 space-y-3">{categories.filter((item) => categoryCounts[item]).map((item) => <div key={item}><div className="mb-1.5 flex justify-between text-[11px]"><span className="text-slate-400">{label(item)}</span><span className="text-slate-500">{categoryCounts[item]}</span></div><div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full bg-gradient-to-r from-violet-400/80 to-blue-400/80" style={{ width: `${Math.max(5, (categoryCounts[item] / categoryMax) * 100)}%` }} /></div></div>)}{Object.keys(categoryCounts).length === 0 && <p className="py-4 text-xs text-slate-600">Category counts will appear when memories are added.</p>}</div></section>
          <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-5"><div className="flex items-center gap-2"><Clock3 size={15} className="text-blue-200" /><h2 className="text-sm font-medium">Memory activity</h2></div><div className="mt-4 space-y-3">{stats?.recently_updated.length ? stats.recently_updated.slice(0, 5).map((memory) => <button key={memory.memory_id} onClick={() => setSelected(memory)} className="block w-full text-left"><p className="line-clamp-2 text-xs leading-5 text-slate-300">{memory.content}</p><p className="mt-1 text-[10px] text-slate-600">{label(memory.category)} · {date(memory.updated_at)}</p></button>) : <p className="py-2 text-xs text-slate-600">Recent updates will appear here.</p>}</div></section>
          {(stats?.extraction_jobs_failed ?? 0) > 0 && <section className="rounded-2xl border border-amber-300/10 bg-amber-300/[0.04] p-4"><p className="text-xs text-amber-100">{stats?.extraction_jobs_failed} memory extraction job(s) need attention.</p><button onClick={() => void retryExtraction()} className="mt-3 rounded-lg border border-amber-200/10 px-3 py-2 text-[11px] text-amber-100/80 hover:bg-amber-200/[0.05]">Retry extraction</button></section>}
          <p className="px-1 text-[11px] leading-5 text-slate-600">Pending memories are never used to answer questions. Approved vectors are stored in your local Chroma database; OpenAI credentials stay on the backend.</p>
        </aside>
      </section>
    </div>

    {selected && <div role="presentation" onClick={() => setSelected(null)} className="fixed inset-0 z-40 grid place-items-center bg-black/70 p-4 backdrop-blur-sm"><section role="dialog" aria-modal="true" aria-labelledby="memory-details-title" onClick={(event) => event.stopPropagation()} className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-2xl border border-white/[0.09] bg-[#10121b] p-6 shadow-2xl"><div className="flex items-start justify-between gap-4"><div><p className="text-[10px] uppercase tracking-[0.18em] text-violet-200/70">{label(selected.category)} · {label(selected.approval_status)}</p><h2 id="memory-details-title" className="mt-2 text-lg font-medium">Memory history</h2></div><button onClick={() => setSelected(null)} aria-label="Close details" className="rounded-lg p-2 text-slate-500 hover:bg-white/[0.05]"><X size={17} /></button></div><p className="mt-5 whitespace-pre-wrap text-sm leading-7 text-slate-200">{selected.content}</p><div className="mt-5 grid grid-cols-2 gap-3 text-xs text-slate-500"><span>Importance: {score(selected.importance)}</span><span>Confidence: {score(selected.confidence)}</span><span>Created: {date(selected.created_at)}</span><span>Updated: {date(selected.updated_at)}</span></div><h3 className="mt-6 text-xs font-medium text-slate-300">Previous versions</h3>{history.length ? <ol className="mt-3 space-y-3">{history.map((entry) => <li key={entry.history_id} className="rounded-lg border border-white/[0.06] p-3"><p className="whitespace-pre-wrap text-xs leading-5 text-slate-300">{entry.content}</p><p className="mt-2 text-[10px] text-slate-600">{entry.change_reason.replaceAll("_", " ")} · {date(entry.created_at)}</p></li>)}</ol> : <p className="mt-2 text-xs text-slate-600">No previous versions recorded.</p>}</section></div>}
  </main>;
}

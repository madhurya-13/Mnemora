"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity, AlertTriangle, Brain, Check, ChevronDown, Clock3, GitBranch, History,
  LoaderCircle, MessageSquareHeart, RefreshCw, Settings2, Sparkles, ThumbsDown, ThumbsUp, X,
} from "lucide-react";
import { ApiError } from "@/lib/api";
import {
  confirmPattern, confirmPreference, deletePreference, dismissPattern, getAdaptiveSettings,
  getEvolution, getFeedbackInsights, getMemoryHealth, listPatterns, listPreferences,
  processAdaptiveNow, rejectPreference, updateAdaptiveSettings, updatePreference,
  type AdaptiveSettings, type EvolutionItem, type FeedbackInsights, type MemoryHealth,
  type Pattern, type Preference, type PreferenceCategory,
} from "@/lib/memories";

const date = (value: string | null) =>
  value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
const percent = (value: number) => `${Math.round(value * 100)}%`;
const label = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const preferenceCategories: PreferenceCategory[] = [
  "communication_style", "learning_style", "programming", "technology",
  "project_workflow", "ui_ux", "content", "other",
];

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "The adaptive memory request could not be completed.";
}

function Section({ icon, title, hint, children }: { icon: React.ReactNode; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-5">
      <div className="flex items-center gap-2">{icon}<h2 className="text-sm font-medium">{title}</h2></div>
      {hint && <p className="mt-1 text-xs text-slate-600">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function AdaptiveMemoryPanel({ refreshKey = 0 }: { refreshKey?: number }) {
  const [preferences, setPreferences] = useState<Preference[]>([]);
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [health, setHealth] = useState<MemoryHealth | null>(null);
  const [evolution, setEvolution] = useState<EvolutionItem[]>([]);
  const [insights, setInsights] = useState<FeedbackInsights | null>(null);
  const [adaptive, setAdaptive] = useState<AdaptiveSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [prefPage, patternPage, nextHealth, evolutionPage, nextInsights, settings] = await Promise.all([
        listPreferences(),
        listPatterns(),
        getMemoryHealth(),
        getEvolution({ limit: 20 }),
        getFeedbackInsights(),
        getAdaptiveSettings(),
      ]);
      setPreferences(prefPage.items);
      setPatterns(patternPage.items);
      setHealth(nextHealth);
      setEvolution(evolutionPage.items);
      setInsights(nextInsights);
      setAdaptive(settings);
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refresh(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh, refreshKey]);

  async function perform(id: string, action: string, task: () => Promise<unknown>, message: string) {
    setBusy(`${action}:${id}`);
    setError(null);
    setNotice(null);
    try {
      await task();
      setNotice(message);
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function toggleSetting(key: keyof Omit<AdaptiveSettings, "updated_at">) {
    if (!adaptive) return;
    setBusy(`setting:${key}`);
    setError(null);
    try {
      const next = await updateAdaptiveSettings({ [key]: !adaptive[key] } as Partial<AdaptiveSettings>);
      setAdaptive(next);
      setNotice("Adaptive settings saved.");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function runProcessing() {
    setBusy("process");
    setError(null);
    try {
      const result = await processAdaptiveNow();
      setNotice(`Processed ${result.processed_jobs} job(s), re-evaluated ${result.evaluated_memories} memories and refreshed ${result.detected_patterns} pattern(s).`);
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function savePreference(id: string) {
    setBusy(`edit:${id}`);
    try {
      await updatePreference(id, { description: draft.trim() });
      setEditing(null);
      setNotice("Preference updated.");
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  const settingToggles: { key: keyof Omit<AdaptiveSettings, "updated_at" | "preference_confidence_threshold" | "preference_evidence_threshold" | "pattern_evidence_threshold">; title: string; hint: string }[] = [
    { key: "preference_learning_enabled", title: "Preference learning", hint: "Learn preferences from repeated signals." },
    { key: "auto_candidate_generation", title: "Candidate generation", hint: "Create candidates automatically after chat turns." },
    { key: "pattern_detection_enabled", title: "Pattern detection", hint: "Detect recurring topics across conversations." },
    { key: "personalization_enabled", title: "Personalization", hint: "Use confirmed preferences in relevant answers." },
    { key: "memory_decay_enabled", title: "Memory decay", hint: "Score utility and flag possibly outdated memories." },
    { key: "require_user_review", title: "Require review", hint: "Keep learned preferences as candidates until confirmed." },
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2"><Brain size={18} className="text-violet-200" /><div><h2 className="text-base font-medium">Adaptive memory</h2><p className="mt-0.5 text-xs text-slate-500">Learned preferences, patterns, health and feedback — all reviewable.</p></div></div>
        <button onClick={() => void runProcessing()} disabled={busy === "process"} className="inline-flex items-center gap-2 rounded-xl border border-violet-300/15 bg-violet-300/[0.07] px-3 py-2 text-xs text-violet-100 hover:bg-violet-300/[0.12] disabled:opacity-50">
          {busy === "process" ? <LoaderCircle size={14} className="animate-spin" /> : <RefreshCw size={14} />} Run adaptive analysis
        </button>
      </div>

      {error && <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-300/15 bg-rose-300/[0.06] px-4 py-3 text-sm text-rose-100"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><span className="flex-1">{error}</span><button onClick={() => setError(null)} aria-label="Dismiss adaptive error"><X size={16} /></button></div>}
      {notice && <div role="status" className="rounded-xl border border-emerald-300/10 bg-emerald-300/[0.04] px-4 py-3 text-xs text-emerald-100/90">{notice}</div>}

      <div className="grid gap-5 xl:grid-cols-2">
        <Section icon={<Sparkles size={15} className="text-violet-200" />} title="Learned preferences" hint="Candidates from repeated evidence. Only confirmed preferences influence answers.">
          {loading ? <div className="flex items-center gap-2 py-4 text-xs text-slate-500"><LoaderCircle className="animate-spin" size={14} /> Loading preferences</div>
            : preferences.length === 0 ? <p className="py-3 text-xs text-slate-600">No preferences learned yet. Chat naturally — repeated signals become candidates.</p>
              : <ul className="space-y-3">{preferences.map((preference) => <li key={preference.preference_id} className="rounded-xl border border-white/[0.06] p-3">
                <div className="flex flex-wrap items-center gap-2 text-[10px]">
                  <span className="rounded-full border border-violet-300/10 bg-violet-300/[0.06] px-2 py-0.5 text-violet-200/80">{label(preference.category)}</span>
                  <span className={`rounded-full px-2 py-0.5 ${preference.status === "confirmed" ? "bg-emerald-300/[0.08] text-emerald-200" : preference.status === "rejected" ? "bg-rose-300/[0.07] text-rose-200" : "bg-amber-300/[0.08] text-amber-100"}`}>{label(preference.status)}</span>
                  <span className="text-slate-500">{percent(preference.confidence)} confidence · {preference.evidence_count} observation(s)</span>
                  <span className="ml-auto text-slate-600">{date(preference.last_observed_at)}</span>
                </div>
                {editing === preference.preference_id
                  ? <textarea value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={500} className="mt-3 min-h-16 w-full rounded-lg border border-violet-300/20 bg-black/20 p-2 text-xs text-slate-200 outline-none" />
                  : <p className="mt-3 text-sm leading-6 text-slate-200">{preference.description}</p>}
                {preference.supporting_memory_ids.length > 0 && <p className="mt-2 text-[10px] text-slate-600">Linked to {preference.supporting_memory_ids.length} approved memory record(s).</p>}
                <details className="mt-2 text-[10px] text-slate-500"><summary className="cursor-pointer text-slate-400">Supporting evidence</summary><ul className="mt-2 space-y-2">{preference.evidence.map((item, index) => <li key={`${preference.preference_id}-${index}`} className="rounded-lg bg-black/15 p-2"><p className="leading-4 text-slate-400">“{item.excerpt}”</p><p className="mt-1 text-slate-600">{date(item.observed_at)}</p></li>)}</ul></details>
                <div className="mt-3 flex flex-wrap gap-1 border-t border-white/[0.06] pt-2">
                  {editing === preference.preference_id ? <>
                    <button disabled={!draft.trim() || busy === `edit:${preference.preference_id}`} onClick={() => void savePreference(preference.preference_id)} className="rounded-lg px-2 py-1.5 text-[10px] text-violet-200 hover:bg-violet-300/[0.08] disabled:opacity-40">Save</button>
                    <button onClick={() => setEditing(null)} className="rounded-lg px-2 py-1.5 text-[10px] text-slate-500 hover:bg-white/[0.05]">Cancel</button>
                  </> : <button onClick={() => { setEditing(preference.preference_id); setDraft(preference.description); }} className="rounded-lg px-2 py-1.5 text-[10px] text-slate-400 hover:bg-white/[0.05]">Edit</button>}
                  {preference.status !== "confirmed" && <button disabled={busy === `confirm:${preference.preference_id}`} onClick={() => void perform(preference.preference_id, "confirm", () => confirmPreference(preference.preference_id), "Preference confirmed.")} className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-[10px] text-emerald-200 hover:bg-emerald-300/[0.08] disabled:opacity-40"><Check size={11} /> Confirm</button>}
                  {preference.status !== "rejected" && <button disabled={busy === `reject:${preference.preference_id}`} onClick={() => void perform(preference.preference_id, "reject", () => rejectPreference(preference.preference_id), "Preference rejected.")} className="rounded-lg px-2 py-1.5 text-[10px] text-amber-100/80 hover:bg-amber-300/[0.06] disabled:opacity-40">Reject</button>}
                  {preference.status !== "disabled" && <button disabled={busy === `disable:${preference.preference_id}`} onClick={() => void perform(preference.preference_id, "disable", () => updatePreference(preference.preference_id, { status: "disabled" }), "Preference disabled.")} className="rounded-lg px-2 py-1.5 text-[10px] text-slate-500 hover:bg-white/[0.05] disabled:opacity-40">Disable</button>}
                  <button disabled={busy === `delete:${preference.preference_id}`} onClick={() => { if (window.confirm("Delete this learned preference?")) void perform(preference.preference_id, "delete", () => deletePreference(preference.preference_id), "Preference deleted."); }} className="ml-auto rounded-lg px-2 py-1.5 text-[10px] text-rose-200/70 hover:bg-rose-300/[0.07] disabled:opacity-40">Delete</button>
                </div>
              </li>)}</ul>}
        </Section>

        <Section icon={<Activity size={15} className="text-emerald-200" />} title="Memory health" hint="Lifecycle states are reversible; old memories are never silently deleted.">
          {health ? <>
            <div className="grid grid-cols-2 gap-3 text-[10px] text-slate-500 sm:grid-cols-3">
              {[["Approved", health.total_approved], ["Active", health.active], ["Possibly outdated", health.possibly_outdated], ["Superseded", health.superseded], ["Expired", health.expired], ["Archived", health.archived], ["Pending review", health.pending_review], ["Low utility", health.low_utility]].map(([title, value]) => <div key={String(title)} className="rounded-lg bg-black/15 p-2.5"><span>{title}</span><strong className="mt-1 block text-lg font-light text-slate-200">{value}</strong></div>)}
            </div>
            <p className="mt-3 text-[10px] text-slate-600">Last evaluated: {date(health.last_evaluated_at)}</p>
            {health.frequently_used.length > 0 && <div className="mt-3"><p className="text-[10px] uppercase tracking-[0.14em] text-slate-600">Frequently used</p><ul className="mt-2 space-y-2">{health.frequently_used.map((memory) => <li key={memory.memory_id} className="rounded-lg bg-black/15 p-2"><p className="line-clamp-2 text-[11px] leading-5 text-slate-300">{memory.content}</p><p className="mt-1 text-[10px] text-slate-600">{label(memory.category)} · used {memory.usage_count}× · utility {percent(memory.utility_score)}</p></li>)}</ul></div>}
          </> : <p className="py-3 text-xs text-slate-600">Health metrics will appear once evaluation runs.</p>}
        </Section>

        <Section icon={<GitBranch size={15} className="text-blue-200" />} title="Memory evolution" hint="Previous values are preserved, with the reason and source of each change.">
          {evolution.length === 0 ? <p className="py-3 text-xs text-slate-600">No memory changes recorded yet.</p>
            : <ol className="space-y-3">{evolution.map((item, index) => <li key={`${item.memory_id}-${index}`} className="rounded-xl border border-white/[0.06] p-3">
              <div className="flex flex-wrap items-center gap-2 text-[10px]"><span className="rounded-full bg-blue-300/[0.08] px-2 py-0.5 text-blue-200">{label(item.change_type)}</span><span className="text-slate-500">{label(item.approval_status)}</span><span className="ml-auto text-slate-600">{date(item.changed_at)}</span></div>
              <p className="mt-2 text-[11px] leading-5 text-slate-500 line-through decoration-slate-600/60">{item.previous_content}</p>
              <p className="mt-1 text-xs leading-5 text-slate-200">{item.new_content}</p>
              <p className="mt-2 text-[10px] text-slate-600">Reason: {label(item.change_reason)}{item.source_conversation_id ? ` · source conversation ${item.source_conversation_id.slice(0, 8)}…` : ""}</p>
            </li>)}</ol>}
        </Section>

        <Section icon={<Clock3 size={15} className="text-amber-200" />} title="Detected patterns" hint="Candidates require multiple observations across at least two conversations.">
          {patterns.length === 0 ? <p className="py-3 text-xs text-slate-600">No recurring patterns detected yet.</p>
            : <ul className="space-y-3">{patterns.map((pattern) => <li key={pattern.pattern_id} className="rounded-xl border border-white/[0.06] p-3">
              <div className="flex flex-wrap items-center gap-2 text-[10px]"><span className="rounded-full bg-amber-300/[0.08] px-2 py-0.5 text-amber-100">{label(pattern.pattern_type)}</span><span className={`rounded-full px-2 py-0.5 ${pattern.status === "confirmed" ? "bg-emerald-300/[0.08] text-emerald-200" : pattern.status === "dismissed" ? "bg-slate-300/[0.06] text-slate-400" : "bg-white/[0.05] text-slate-300"}`}>{label(pattern.status)}</span><span className="text-slate-500">{percent(pattern.confidence)} · {pattern.evidence_count} observation(s)</span></div>
              <p className="mt-2 text-sm leading-6 text-slate-200">{pattern.description}</p>
              <p className="mt-1 text-[10px] text-slate-600">{pattern.supporting_conversation_ids.length} conversation(s) · first {date(pattern.first_observed_at)} · last {date(pattern.last_observed_at)}</p>
              <div className="mt-2 flex flex-wrap gap-1 border-t border-white/[0.06] pt-2">
                {pattern.status !== "confirmed" && <button disabled={busy === `confirm:${pattern.pattern_id}`} onClick={() => void perform(pattern.pattern_id, "confirm", () => confirmPattern(pattern.pattern_id), "Pattern confirmed.")} className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-[10px] text-emerald-200 hover:bg-emerald-300/[0.08] disabled:opacity-40"><Check size={11} /> Confirm</button>}
                {pattern.status !== "dismissed" && <button disabled={busy === `dismiss:${pattern.pattern_id}`} onClick={() => void perform(pattern.pattern_id, "dismiss", () => dismissPattern(pattern.pattern_id), "Pattern dismissed.")} className="rounded-lg px-2 py-1.5 text-[10px] text-slate-400 hover:bg-white/[0.05] disabled:opacity-40">Dismiss</button>}
              </div>
            </li>)}</ul>}
        </Section>

        <Section icon={<MessageSquareHeart size={15} className="text-rose-200" />} title="Feedback insights" hint="Real feedback events from this account.">
          {insights ? <>
            <div className="grid grid-cols-2 gap-3 text-[10px] text-slate-500 sm:grid-cols-3">
              {[["Total", insights.total], ["Helpful", insights.helpful_count], ["Not helpful", insights.not_helpful_count], ["Incorrect personalization", insights.incorrect_personalization_count], ["Outdated memory reports", insights.outdated_information_count], ["Correction requests", insights.correction_requests]].map(([title, value]) => <div key={String(title)} className="rounded-lg bg-black/15 p-2.5"><span>{title}</span><strong className="mt-1 block text-lg font-light text-slate-200">{value}</strong></div>)}
            </div>
            {insights.recent.length > 0 ? <ul className="mt-3 space-y-2">{insights.recent.slice(0, 5).map((item) => <li key={item.feedback_id} className="flex items-center gap-2 rounded-lg bg-black/15 p-2 text-[10px] text-slate-500"><span className="inline-flex items-center gap-1 text-slate-300">{item.feedback_type === "helpful" ? <ThumbsUp size={11} /> : item.feedback_type === "not_helpful" ? <ThumbsDown size={11} /> : <History size={11} />}{label(item.feedback_type)}</span><span className="ml-auto">{date(item.created_at)}</span></li>)}</ul>
              : <p className="mt-3 text-xs text-slate-600">Use the thumbs up/down buttons on assistant replies to create feedback.</p>}
          </> : <p className="py-3 text-xs text-slate-600">Feedback totals will appear after the first rating.</p>}
        </Section>

        <Section icon={<Settings2 size={15} className="text-slate-300" />} title="Adaptive settings" hint="Saved per user. Disabling learning leaves existing approved memories untouched.">
          {adaptive ? <>
            <ul className="space-y-2">{settingToggles.map((toggle) => <li key={toggle.key} className="flex items-center gap-3 rounded-lg border border-white/[0.05] p-3"><div className="min-w-0 flex-1"><p className="text-xs text-slate-200">{toggle.title}</p><p className="mt-0.5 text-[10px] leading-4 text-slate-600">{toggle.hint}</p></div><button role="switch" aria-checked={adaptive[toggle.key]} aria-label={toggle.title} disabled={busy === `setting:${toggle.key}`} onClick={() => void toggleSetting(toggle.key)} className={`relative h-6 w-11 shrink-0 rounded-full transition ${adaptive[toggle.key] ? "bg-violet-400/70" : "bg-white/[0.09]"} disabled:opacity-50`}><span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${adaptive[toggle.key] ? "left-[22px]" : "left-0.5"}`} /></button></li>)}</ul>
            <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-slate-500"><span>Confidence threshold<strong className="mt-1 block text-sm text-slate-300">{percent(adaptive.preference_confidence_threshold)}</strong></span><span>Evidence threshold<strong className="mt-1 block text-sm text-slate-300">{adaptive.preference_evidence_threshold} observations</strong></span><span>Pattern threshold<strong className="mt-1 block text-sm text-slate-300">{adaptive.pattern_evidence_threshold} observations</strong></span><span>Updated<strong className="mt-1 block text-xs text-slate-300">{date(adaptive.updated_at)}</strong></span></div>
            <details className="mt-2 text-[10px] text-slate-500"><summary className="cursor-pointer text-slate-400">Advanced thresholds</summary><div className="mt-2 grid gap-2"><label className="flex items-center justify-between gap-2">Confidence threshold<input type="number" min={0} max={1} step={0.05} defaultValue={adaptive.preference_confidence_threshold} onBlur={(event) => { const value = Number(event.target.value); if (Number.isFinite(value) && value !== adaptive.preference_confidence_threshold) void updateAdaptiveSettings({ preference_confidence_threshold: value }).then(setAdaptive).catch((caught) => setError(errorMessage(caught))); }} className="w-20 rounded-lg border border-white/[0.08] bg-[#0c0e17] px-2 py-1 text-slate-300" /></label><label className="flex items-center justify-between gap-2">Preference evidence threshold<input type="number" min={2} max={20} defaultValue={adaptive.preference_evidence_threshold} onBlur={(event) => { const value = Number(event.target.value); if (Number.isInteger(value) && value !== adaptive.preference_evidence_threshold) void updateAdaptiveSettings({ preference_evidence_threshold: value }).then(setAdaptive).catch((caught) => setError(errorMessage(caught))); }} className="w-20 rounded-lg border border-white/[0.08] bg-[#0c0e17] px-2 py-1 text-slate-300" /></label><label className="flex items-center justify-between gap-2">Pattern evidence threshold<input type="number" min={2} max={20} defaultValue={adaptive.pattern_evidence_threshold} onBlur={(event) => { const value = Number(event.target.value); if (Number.isInteger(value) && value !== adaptive.pattern_evidence_threshold) void updateAdaptiveSettings({ pattern_evidence_threshold: value }).then(setAdaptive).catch((caught) => setError(errorMessage(caught))); }} className="w-20 rounded-lg border border-white/[0.08] bg-[#0c0e17] px-2 py-1 text-slate-300" /></label></div></details>
          </> : <p className="py-3 text-xs text-slate-600">Adaptive settings are loading.</p>}
        </Section>
      </div>
      <p className="px-1 text-[11px] leading-5 text-slate-600">Adaptive learning reads eligible conversation text and approved structured memories only — never raw audio, images, passwords or tokens. <ChevronDown size={11} className="inline" /> Expand supporting evidence on any preference to inspect what was observed.</p>
    </div>
  );
}

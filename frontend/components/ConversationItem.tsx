"use client";

import { FormEvent, useState } from "react";
import { Check, MessageSquare, Pencil, RotateCcw, Trash2, X } from "lucide-react";
import type { ConversationSummary } from "@/lib/chat";

type Props = {
  conversation: ConversationSummary;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onClear: () => void;
  onDelete: () => void;
};

export default function ConversationItem({ conversation, active, onSelect, onRename, onClear, onDelete }: Props) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(conversation.title);

  function save(event: FormEvent) {
    event.preventDefault();
    const clean = title.trim();
    if (!clean) return;
    onRename(clean);
    setEditing(false);
  }

  if (editing) return <form onSubmit={save} className="flex items-center gap-1 rounded-xl border border-violet-300/20 bg-white/[0.045] p-1.5">
    <input autoFocus maxLength={80} value={title} onChange={(event) => setTitle(event.target.value)} aria-label="Conversation title" className="min-w-0 flex-1 bg-transparent px-2 text-xs text-slate-200 outline-none" />
    <button type="submit" aria-label="Save conversation name" className="rounded-md p-1 text-emerald-300 hover:bg-white/10"><Check size={14} /></button>
    <button type="button" aria-label="Cancel rename" onClick={() => { setTitle(conversation.title); setEditing(false); }} className="rounded-md p-1 text-slate-500 hover:bg-white/10"><X size={14} /></button>
  </form>;

  return <div className={`group flex items-center gap-1 rounded-xl border px-2 py-1.5 transition ${active ? "border-violet-300/15 bg-violet-300/[0.08]" : "border-transparent hover:bg-white/[0.045]"}`}>
    <button onClick={onSelect} className="flex min-w-0 flex-1 items-center gap-2.5 py-1 text-left" aria-current={active ? "page" : undefined}>
      <MessageSquare size={14} className={active ? "shrink-0 text-violet-200" : "shrink-0 text-slate-600"} />
      <span className="min-w-0 flex-1 truncate text-xs text-slate-300">{conversation.title}</span>
    </button>
    <span className="hidden text-[10px] text-slate-600 group-hover:hidden">{conversation.message_count || ""}</span>
    <div className="flex shrink-0 items-center sm:hidden sm:group-hover:flex">
      <button title="Rename conversation" aria-label="Rename conversation" onClick={() => { setTitle(conversation.title); setEditing(true); }} className="rounded-md p-1 text-slate-500 hover:bg-white/10 hover:text-slate-200"><Pencil size={12} /></button>
      <button title="Clear messages" aria-label="Clear messages" onClick={() => { if (window.confirm("Clear all messages in this conversation?")) onClear(); }} className="rounded-md p-1 text-slate-500 hover:bg-white/10 hover:text-amber-200"><RotateCcw size={12} /></button>
      <button title="Delete conversation" aria-label="Delete conversation" onClick={() => { if (window.confirm("Delete this conversation? This only removes its temporary in-memory chat history.")) onDelete(); }} className="rounded-md p-1 text-slate-500 hover:bg-white/10 hover:text-rose-300"><Trash2 size={12} /></button>
    </div>
  </div>;
}

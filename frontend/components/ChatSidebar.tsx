"use client";

import { Brain, MessageSquarePlus, Settings2, Sparkles, X } from "lucide-react";
import ConversationItem from "@/components/ConversationItem";
import type { ConversationSummary } from "@/lib/chat";

type Props = {
  conversations: ConversationSummary[];
  loading: boolean;
  hasMore: boolean;
  showArchived: boolean;
  activeId: string | null;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onClear: (id: string) => void;
  onDelete: (id: string) => void;
  onArchive: (id: string, archived: boolean) => void;
  onLoadMore: () => void;
  onToggleArchived: () => void;
  onToggleInfo: () => void;
};

export default function ChatSidebar(props: Props) {
  return <>
    {props.mobileOpen && <button aria-label="Close navigation" onClick={props.onCloseMobile} className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden" />}
    <aside className={`fixed inset-y-0 left-0 z-40 flex w-[278px] flex-col border-r border-white/[0.07] bg-[#0c0e17] transition-transform duration-200 lg:static lg:z-auto lg:translate-x-0 ${props.mobileOpen ? "translate-x-0" : "-translate-x-full"}`}>
      <div className="flex h-[72px] items-center justify-between border-b border-white/[0.06] px-5">
        <a href="#chat" className="flex items-center gap-3" aria-label="MNEMORA home"><span className="grid h-9 w-9 place-items-center rounded-xl border border-violet-300/20 bg-violet-400/10 text-violet-200"><Brain size={19} /></span><span className="text-xs font-semibold tracking-[0.24em] text-slate-100">MNEMORA</span></a>
        <button onClick={props.onCloseMobile} aria-label="Close sidebar" className="rounded-lg p-2 text-slate-500 hover:bg-white/[0.06] lg:hidden"><X size={17} /></button>
      </div>
      <div className="px-4 py-4"><button onClick={props.onNew} className="flex w-full items-center justify-center gap-2 rounded-xl border border-violet-300/20 bg-gradient-to-r from-violet-500/15 to-blue-500/10 px-3 py-3 text-sm font-medium text-violet-100 transition hover:border-violet-200/35 hover:from-violet-500/20"><MessageSquarePlus size={16} /> New chat</button></div>
      <div className="mb-2 flex items-center justify-between px-5 pt-2"><span className="text-[10px] font-medium uppercase tracking-[0.19em] text-slate-600">{props.showArchived ? "Archived conversations" : "Recent conversations"}</span><button onClick={props.onToggleArchived} className="text-[10px] text-violet-300/60 hover:text-violet-200">{props.showArchived ? "Show active" : "Archived"}</button></div>
      <nav aria-label="Conversation history" className="flex-1 space-y-1 overflow-y-auto px-3 pb-4">
        {props.loading ? <div className="space-y-2 px-2 py-2" aria-label="Loading conversations"><div className="h-9 animate-pulse rounded-lg bg-white/[0.04]" /><div className="h-9 animate-pulse rounded-lg bg-white/[0.04]" /><div className="h-9 animate-pulse rounded-lg bg-white/[0.04]" /></div>
          : props.conversations.length === 0 ? <p className="px-3 py-4 text-xs leading-5 text-slate-600">{props.showArchived ? "No archived conversations." : "Saved conversations will appear here."}</p>
            : props.conversations.map((conversation) => <ConversationItem key={conversation.conversation_id} conversation={conversation} active={props.activeId === conversation.conversation_id} onSelect={() => props.onSelect(conversation.conversation_id)} onRename={(title) => props.onRename(conversation.conversation_id, title)} onClear={() => props.onClear(conversation.conversation_id)} onDelete={() => props.onDelete(conversation.conversation_id)} onArchive={() => props.onArchive(conversation.conversation_id, !conversation.is_archived)} />)}
        {props.hasMore && <button onClick={props.onLoadMore} className="w-full rounded-lg py-2 text-xs text-slate-500 hover:bg-white/[0.04] hover:text-slate-300">Load more</button>}
      </nav>
      <div className="border-t border-white/[0.06] p-3">
        <button onClick={props.onToggleInfo} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs text-slate-400 transition hover:bg-white/[0.045] hover:text-slate-200"><Settings2 size={15} /> Assistant settings</button>
        <div className="mt-1 flex items-center gap-3 rounded-xl px-3 py-3"><span className="grid h-8 w-8 place-items-center rounded-full border border-white/10 bg-white/[0.05] text-slate-400"><Sparkles size={15} /></span><span><span className="block text-xs text-slate-300">Personal workspace</span><span className="mt-0.5 block text-[10px] text-slate-600">Local session</span></span></div>
      </div>
    </aside>
  </>;
}

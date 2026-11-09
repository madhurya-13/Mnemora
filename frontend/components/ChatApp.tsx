"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, Info, Menu, PanelRightClose, Sparkles } from "lucide-react";
import ChatInput from "@/components/ChatInput";
import ChatMessage, { type DisplayMessage } from "@/components/ChatMessage";
import ChatSidebar from "@/components/ChatSidebar";
import TypingIndicator from "@/components/TypingIndicator";
import WelcomeScreen from "@/components/WelcomeScreen";
import { ApiError, getChatHealth, getHealth, type ChatHealthResponse } from "@/lib/api";
import {
  clearConversation,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  renameConversation,
  streamChat,
  type ConversationDetail,
  type ConversationSummary,
} from "@/lib/chat";

type ConnectionState = "checking" | "connected" | "disconnected";
type SendOptions = { includeUser?: boolean; regenerate?: boolean; replaceMessageId?: string };

function toDisplayMessages(conversation: ConversationDetail): DisplayMessage[] {
  return conversation.messages.map((message, index) => ({
    id: `${conversation.conversation_id}-${index}-${message.created_at}`,
    role: message.role,
    content: message.content,
    createdAt: message.created_at,
    retryPrompt: message.role === "assistant"
      ? conversation.messages.slice(0, index).reverse().find((prior) => prior.role === "user")?.content
      : undefined,
  }));
}

function safeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

export default function ChatApp() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [chatHealth, setChatHealth] = useState<ChatHealthResponse | null>(null);
  const [sending, setSending] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const activeIdRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const changeActiveId = useCallback((id: string | null) => {
    activeIdRef.current = id;
    setActiveId(id);
  }, []);

  const refreshConversations = useCallback(async () => {
    const list = await listConversations();
    setConversations(list);
    return list;
  }, []);

  useEffect(() => {
    let mounted = true;
    getHealth().then(() => { if (mounted) setConnection("connected"); }).catch(() => { if (mounted) setConnection("disconnected"); });
    getChatHealth().then((result) => { if (mounted) setChatHealth(result); }).catch(() => { if (mounted) setChatHealth(null); });
    listConversations().then(async (list) => {
      if (!mounted) return;
      setConversations(list);
      if (list.length) {
        const first = await getConversation(list[0].conversation_id);
        if (mounted) {
          changeActiveId(first.conversation_id);
          setMessages(toDisplayMessages(first));
        }
      }
    }).catch((error: unknown) => { if (mounted) setPageError(safeError(error)); });
    return () => { mounted = false; };
  }, [changeActiveId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: sending ? "smooth" : "auto", block: "end" });
  }, [messages, sending]);

  const openConversation = useCallback(async (id: string) => {
    setLoadingConversation(true);
    setPageError(null);
    try {
      const detail = await getConversation(id);
      changeActiveId(id);
      setMessages(toDisplayMessages(detail));
      setMobileSidebarOpen(false);
    } catch (error) {
      setPageError(safeError(error));
    } finally {
      setLoadingConversation(false);
    }
  }, [changeActiveId]);

  const startConversation = useCallback(async () => {
    setPageError(null);
    try {
      const created = await createConversation();
      setConversations((current) => [created, ...current]);
      changeActiveId(created.conversation_id);
      setMessages([]);
      setMobileSidebarOpen(false);
    } catch (error) {
      setPageError(safeError(error));
    }
  }, [changeActiveId]);

  async function submitMessage(rawText: string, options: SendOptions = {}) {
    const message = rawText.trim();
    if (!message || sending) return;
    setPageError(null);
    setSending(true);
    let conversationId = activeIdRef.current;
    try {
      if (!conversationId) {
        const created = await createConversation();
        conversationId = created.conversation_id;
        changeActiveId(conversationId);
        setConversations((current) => [created, ...current]);
      }

      const assistantId = `local-${crypto.randomUUID()}`;
      const now = new Date().toISOString();
      setMessages((current) => {
        const withoutReplaced = options.replaceMessageId
          ? current.filter((item) => item.id !== options.replaceMessageId)
          : current;
        const withUser = options.includeUser === false
          ? withoutReplaced
          : [...withoutReplaced, { id: `local-${crypto.randomUUID()}`, role: "user" as const, content: message, createdAt: now }];
        return [...withUser, {
          id: assistantId,
          role: "assistant" as const,
          content: "",
          createdAt: now,
          retryPrompt: message,
          pending: true,
        }];
      });

      let completed = false;
      await streamChat(
        { conversation_id: conversationId, message, regenerate: options.regenerate ?? false },
        (event) => {
          if (activeIdRef.current !== conversationId) return;
          if (event.event === "token") {
            setMessages((current) => current.map((item) => item.id === assistantId
              ? { ...item, content: item.content + event.data.text, pending: false }
              : item));
          } else if (event.event === "error") {
            setMessages((current) => current.map((item) => item.id === assistantId
              ? { ...item, pending: false, error: event.data.message, retryable: event.data.retryable }
              : item));
          } else if (event.event === "done") {
            completed = true;
            setMessages((current) => current.map((item) => item.id === assistantId ? { ...item, pending: false } : item));
          }
        },
      );

      if (completed) {
        const [detail] = await Promise.all([getConversation(conversationId), refreshConversations()]);
        if (activeIdRef.current === conversationId) setMessages(toDisplayMessages(detail));
      }
    } catch (error) {
      const messageText = safeError(error);
      if (conversationId && activeIdRef.current === conversationId) {
        setMessages((current) => {
          const last = current.at(-1);
          if (last?.role === "assistant" && last.pending) {
            return current.map((item) => item.id === last.id
              ? { ...item, pending: false, error: messageText, retryable: true }
              : item);
          }
          return [...current, {
            id: `local-${crypto.randomUUID()}`,
            role: "assistant",
            content: "",
            createdAt: new Date().toISOString(),
            retryPrompt: message,
            error: messageText,
            retryable: true,
          }];
        });
      } else {
        setPageError(messageText);
      }
    } finally {
      setSending(false);
      refreshConversations().catch(() => undefined);
    }
  }

  async function rename(id: string, title: string) {
    try {
      await renameConversation(id, title);
      await refreshConversations();
    } catch (error) { setPageError(safeError(error)); }
  }

  async function clear(id: string) {
    try {
      const detail = await clearConversation(id);
      await refreshConversations();
      if (activeIdRef.current === id) setMessages(toDisplayMessages(detail));
    } catch (error) { setPageError(safeError(error)); }
  }

  async function remove(id: string) {
    try {
      await deleteConversation(id);
      setConversations((current) => current.filter((item) => item.conversation_id !== id));
      if (activeIdRef.current === id) { changeActiveId(null); setMessages([]); }
    } catch (error) { setPageError(safeError(error)); }
  }

  function retry(prompt: string, regenerate: boolean, messageId: string) {
    void submitMessage(prompt, { includeUser: false, regenerate, replaceMessageId: messageId });
  }

  const activeConversation = conversations.find((item) => item.conversation_id === activeId) ?? null;
  const connectionText = connection === "checking" ? "Checking backend" : connection === "connected" ? "Backend connected" : "Backend unavailable";

  return <div className="flex h-dvh min-h-[520px] overflow-hidden bg-[#080a12] text-slate-100">
    <ChatSidebar
      conversations={conversations}
      activeId={activeId}
      mobileOpen={mobileSidebarOpen}
      onCloseMobile={() => setMobileSidebarOpen(false)}
      onNew={() => void startConversation()}
      onSelect={(id) => void openConversation(id)}
      onRename={(id, title) => void rename(id, title)}
      onClear={(id) => void clear(id)}
      onDelete={(id) => void remove(id)}
      onToggleInfo={() => setInfoOpen((value) => !value)}
    />

    <div className="relative flex min-w-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[72px] shrink-0 items-center justify-between border-b border-white/[0.06] px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button aria-label="Open navigation" onClick={() => setMobileSidebarOpen(true)} className="rounded-lg p-2 text-slate-400 hover:bg-white/[0.05] lg:hidden"><Menu size={18} /></button>
            <div className="min-w-0"><p className="truncate text-sm font-medium text-slate-200">{activeConversation?.title ?? "New conversation"}</p><p className="mt-0.5 text-[10px] text-slate-600">Personal AI workspace</p></div>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <span className={`hidden items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] sm:flex ${connection === "connected" ? "border-emerald-300/10 bg-emerald-300/[0.045] text-emerald-200/80" : connection === "disconnected" ? "border-rose-300/10 bg-rose-300/[0.045] text-rose-200/80" : "border-white/[0.08] text-slate-500"}`}><span className={`h-1.5 w-1.5 rounded-full ${connection === "connected" ? "bg-emerald-400" : connection === "disconnected" ? "bg-rose-400" : "animate-pulse bg-violet-300"}`} />{connectionText}</span>
            <span className="hidden rounded-full border border-violet-300/10 bg-violet-300/[0.04] px-3 py-1.5 text-[11px] text-violet-200/70 md:inline-flex"><Sparkles size={12} className="mr-1.5" />{chatHealth?.model ?? "MNEMORA"}</span>
            <button aria-label={infoOpen ? "Hide assistant information" : "Show assistant information"} onClick={() => setInfoOpen((value) => !value)} className="rounded-lg p-2 text-slate-500 transition hover:bg-white/[0.05] hover:text-slate-200"><Info size={17} /></button>
          </div>
        </header>

        {pageError && <div className="mx-4 mt-4 flex items-start gap-2 rounded-xl border border-rose-300/15 bg-rose-300/[0.06] px-4 py-3 text-sm text-rose-100 sm:mx-6"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><span className="flex-1">{pageError}</span><button onClick={() => setPageError(null)} aria-label="Dismiss error" className="text-rose-200/70 hover:text-rose-100"><ChevronDown size={16} /></button></div>}
        {connection === "connected" && chatHealth && !chatHealth.configured && <div className="mx-4 mt-4 flex items-start gap-2 rounded-xl border border-amber-300/15 bg-amber-300/[0.055] px-4 py-3 text-xs leading-5 text-amber-100/90 sm:mx-6"><AlertTriangle size={15} className="mt-0.5 shrink-0" /><span>Chat is not configured yet. Add <code className="rounded bg-black/20 px-1">GOOGLE_API_KEY</code> to <code className="rounded bg-black/20 px-1">backend/.env</code>, then restart the backend.</span></div>}

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" aria-live="polite">
          {loadingConversation ? <div className="grid flex-1 place-items-center text-sm text-slate-500">Loading conversation…</div>
            : messages.length === 0 ? <WelcomeScreen onPrompt={(prompt) => void submitMessage(prompt)} />
              : <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-7 px-4 py-8 sm:px-8 sm:py-10" role="log" aria-label="Conversation messages">
                {messages.map((message) => message.pending && !message.content
                  ? <TypingIndicator key={message.id} />
                  : <ChatMessage key={message.id} message={message} canRegenerate={message.id === messages.at(-1)?.id} onRetry={(prompt, regenerate = false) => retry(prompt, regenerate, message.id)} />)}
                <div ref={bottomRef} />
              </div>}
        </div>
        <div className="shrink-0 px-4 pb-4 pt-2 sm:px-8 sm:pb-6"><ChatInput disabled={sending} onSend={(message) => void submitMessage(message)} /></div>
      </main>

      {infoOpen && <>
        <button aria-label="Close assistant information" onClick={() => setInfoOpen(false)} className="fixed inset-0 z-20 bg-black/60 backdrop-blur-sm lg:hidden" />
        <aside className="fixed inset-y-0 right-0 z-30 w-[270px] shrink-0 border-l border-white/[0.06] bg-[#0c0e17] p-5 shadow-2xl lg:static lg:z-auto lg:w-[260px] lg:shadow-none">
        <div className="mb-7 flex items-center justify-between"><h2 className="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">Assistant details</h2><button onClick={() => setInfoOpen(false)} aria-label="Close assistant details" className="rounded-lg p-1.5 text-slate-500 hover:bg-white/[0.05]"><PanelRightClose size={16} /></button></div>
        <div className="space-y-5">
          <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"><p className="text-[10px] uppercase tracking-[0.16em] text-slate-600">Model</p><p className="mt-2 text-sm text-slate-200">{chatHealth?.model ?? "Loading…"}</p><p className="mt-1 text-[11px] text-slate-500">Configured in backend environment</p></div>
          <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"><p className="text-[10px] uppercase tracking-[0.16em] text-slate-600">Connection</p><p className={`mt-2 text-sm ${connection === "connected" ? "text-emerald-200" : connection === "disconnected" ? "text-rose-200" : "text-slate-300"}`}>{connectionText}</p><p className="mt-1 text-[11px] text-slate-500">{chatHealth?.configured ? "Chat service configured" : "Chat service not configured"}</p></div>
          <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"><p className="text-[10px] uppercase tracking-[0.16em] text-slate-600">This conversation</p><p className="mt-2 truncate text-sm text-slate-200">{activeConversation?.title ?? "No conversation selected"}</p><p className="mt-1 text-[11px] text-slate-500">{activeConversation ? `${activeConversation.message_count} messages` : "Start a new chat to begin"}</p></div>
          <p className="text-[11px] leading-5 text-slate-600">Conversation history is held in backend memory for this running session. It clears when the backend restarts.</p>
        </div>
        </aside>
      </>}
    </div>
  </div>;
}

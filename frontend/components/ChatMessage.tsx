"use client";

import { useState } from "react";
import { Bot, Check, Copy, RotateCcw, UserRound } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { MessageRole } from "@/lib/chat";

export type DisplayMessage = {
  id: string;
  role: MessageRole;
  content: string;
  createdAt: string;
  error?: string;
  retryable?: boolean;
  retryPrompt?: string;
  pending?: boolean;
};

type Props = { message: DisplayMessage; canRegenerate?: boolean; onRetry?: (prompt: string, regenerate?: boolean) => void };

export default function ChatMessage({ message, canRegenerate = false, onRetry }: Props) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";

  async function copyResponse() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  }

  return <article className={`group flex w-full gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
    <span className={`mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-xl ${isUser ? "border border-blue-300/15 bg-blue-300/[0.08] text-blue-200" : "border border-violet-300/15 bg-violet-300/[0.07] text-violet-200"}`}>
      {isUser ? <UserRound size={16} /> : <Bot size={16} />}
    </span>
    <div className={`min-w-0 max-w-[min(82%,760px)] ${isUser ? "items-end" : "items-start"} flex flex-col`}>
      <div className={`mb-1 flex items-center gap-2 px-1 text-[11px] text-slate-500 ${isUser ? "flex-row-reverse" : ""}`}>
        <span>{isUser ? "You" : "MNEMORA"}</span>
        <time dateTime={message.createdAt}>{new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(message.createdAt))}</time>
      </div>
      <div className={`w-fit max-w-full overflow-hidden rounded-2xl px-4 py-3.5 text-[14px] leading-7 sm:px-5 ${isUser ? "rounded-tr-sm border border-blue-300/10 bg-blue-500/[0.12] text-slate-100" : "rounded-tl-sm border border-white/[0.07] bg-white/[0.035] text-slate-200"}`}>
        {message.content ? <div className="max-w-none break-words text-sm leading-7 [&_p]:my-2 [&_h1]:mb-2 [&_h1]:mt-5 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-4 [&_h3]:font-semibold [&_a]:text-blue-300 [&_a]:underline [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-6 [&_li]:my-1 [&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-violet-400/40 [&_blockquote]:pl-4 [&_blockquote]:text-slate-400 [&_strong]:font-semibold [&_strong]:text-white [&_hr]:my-4 [&_hr]:border-white/10">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
            a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer">{children}</a>,
            pre: ({ children }) => <pre className="my-3 max-w-full overflow-x-auto rounded-xl border border-white/10 bg-[#080a12] p-4 text-xs leading-6">{children}</pre>,
            code: ({ className, children, ...props }) => <code {...props} className={className ? `${className} rounded bg-black/35 px-1 py-0.5 text-violet-200` : "rounded bg-black/35 px-1 py-0.5 font-mono text-[.9em] text-violet-200"}>{children}</code>,
          }}>{message.content}</ReactMarkdown>
        </div> : message.pending ? <span className="text-slate-500">Thinking…</span> : null}
        {message.error && <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-rose-300/10 pt-3 text-sm text-rose-200"><span>{message.error}</span>{message.retryable && message.retryPrompt && <button className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200/15 px-2.5 py-1 text-xs text-rose-100 transition hover:bg-rose-200/10" onClick={() => onRetry?.(message.retryPrompt!, false)}><RotateCcw size={12} /> Retry</button>}</div>}
      </div>
      {!isUser && message.content && !message.pending && <div className="mt-1.5 flex items-center gap-1">
        <button onClick={copyResponse} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-slate-500 opacity-70 transition hover:bg-white/[0.05] hover:text-slate-300 sm:opacity-0 sm:group-hover:opacity-100" aria-label="Copy response">{copied ? <Check size={12} /> : <Copy size={12} />}{copied ? "Copied" : "Copy"}</button>
        {canRegenerate && !message.error && message.retryPrompt && <button onClick={() => onRetry?.(message.retryPrompt!, true)} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-slate-500 opacity-70 transition hover:bg-white/[0.05] hover:text-slate-300 sm:opacity-0 sm:group-hover:opacity-100" aria-label="Regenerate response"><RotateCcw size={12} /> Regenerate</button>}
      </div>}
    </div>
  </article>;
}

"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Bot,
  Check,
  Copy,
  Image as ImageIcon,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
  Square,
  ThumbsDown,
  ThumbsUp,
  UserRound,
  Volume2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { MessageRole } from "@/lib/chat";
import { submitResponseFeedback } from "@/lib/memories";
import { synthesizeSpeech } from "@/lib/voice";

export type DisplayMessage = {
  id: string;
  role: MessageRole;
  content: string;
  createdAt: string;
  error?: string;
  retryable?: boolean;
  retryPrompt?: string;
  pending?: boolean;
  imagePreviewUrl?: string;
  memoriesUsed?: string[];
  assistantMessageId?: string;
};

type Props = {
  message: DisplayMessage;
  canRegenerate?: boolean;
  onRetry?: (prompt: string, regenerate?: boolean) => void;
  voiceName?: string;
  conversationId?: string | null;
};

type AudioState = "idle" | "loading" | "playing" | "paused";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function ChatMessage({
  message,
  canRegenerate = false,
  onRetry,
  voiceName,
  conversationId,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [audioState, setAudioState] = useState<AudioState>("idle");
  const [audioError, setAudioError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<"helpful" | "not_helpful" | null>(null);
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const audioBlobUrlRef = useRef<string | null>(null);

  const isUser = message.role === "user";
  const feedbackTargetId = message.assistantMessageId ?? message.id;
  const feedbackAvailable = !isUser && UUID_PATTERN.test(feedbackTargetId);

  async function sendFeedback(type: "helpful" | "not_helpful") {
    if (!feedbackAvailable || feedbackBusy) return;
    setFeedbackBusy(true);
    setFeedbackError(null);
    try {
      await submitResponseFeedback({
        targetType: "response",
        targetId: feedbackTargetId,
        feedbackType: type,
        conversationId,
      });
      setFeedback(type);
    } catch (error) {
      setFeedbackError(error instanceof Error ? error.message : "Feedback could not be saved.");
    } finally {
      setFeedbackBusy(false);
    }
  }

  useEffect(() => {
    return () => {
      if (audioBlobUrlRef.current) {
        URL.revokeObjectURL(audioBlobUrlRef.current);
      }
      if (audioElementRef.current) {
        audioElementRef.current.pause();
        audioElementRef.current.src = "";
      }
    };
  }, []);

  async function copyResponse() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  }

  // --- Text-to-Speech Playback Handlers ---
  async function togglePlayAudio() {
    setAudioError(null);

    // If currently playing, pause
    if (audioState === "playing" && audioElementRef.current) {
      audioElementRef.current.pause();
      setAudioState("paused");
      return;
    }

    // If paused, resume
    if (audioState === "paused" && audioElementRef.current) {
      audioElementRef.current
        .play()
        .then(() => setAudioState("playing"))
        .catch(() => setAudioState("idle"));
      return;
    }

    // If idle, synthesize speech from backend
    if (!message.content.trim()) return;

    setAudioState("loading");
    try {
      // Strip markdown syntax for speech synthesis
      const plainText = message.content
        .replace(/```[\s\S]*?```/g, "Code block omitted.")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
        .replace(/[#*_~>]/g, "")
        .trim();

      const blob = await synthesizeSpeech(plainText, voiceName);
      if (audioBlobUrlRef.current) {
        URL.revokeObjectURL(audioBlobUrlRef.current);
      }
      const blobUrl = URL.createObjectURL(blob);
      audioBlobUrlRef.current = blobUrl;

      const audio = new Audio(blobUrl);
      audioElementRef.current = audio;

      audio.onended = () => {
        setAudioState("idle");
      };

      audio.onerror = () => {
        setAudioState("idle");
        setAudioError("Playback failed.");
      };

      await audio.play();
      setAudioState("playing");
    } catch (err: unknown) {
      setAudioState("idle");
      const msg = err instanceof Error ? err.message : "Failed to generate speech.";
      setAudioError(msg);
      window.setTimeout(() => setAudioError(null), 4000);
    }
  }

  function stopAudio() {
    if (audioElementRef.current) {
      audioElementRef.current.pause();
      audioElementRef.current.currentTime = 0;
    }
    setAudioState("idle");
  }

  // Check if user message contains an attached image notice
  const attachedImageMatch = isUser ? message.content.match(/^\[Attached image:\s*([^\]]+)\]\s*\n?([\s\S]*)$/) : null;
  const attachedImageName = attachedImageMatch ? attachedImageMatch[1].trim() : null;
  const userTextBody = attachedImageMatch ? attachedImageMatch[2].trim() : message.content;

  return (
    <article className={`group flex w-full gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <span
        className={`mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-xl ${
          isUser
            ? "border border-blue-300/15 bg-blue-300/[0.08] text-blue-200"
            : "border border-violet-300/15 bg-violet-300/[0.07] text-violet-200"
        }`}
      >
        {isUser ? <UserRound size={16} /> : <Bot size={16} />}
      </span>

      <div className={`min-w-0 max-w-[min(82%,760px)] ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div className={`mb-1 flex items-center gap-2 px-1 text-[11px] text-slate-500 ${isUser ? "flex-row-reverse" : ""}`}>
          <span>{isUser ? "You" : "MNEMORA"}</span>
          <time dateTime={message.createdAt}>
            {new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(
              new Date(message.createdAt)
            )}
          </time>
        </div>

        <div
          className={`w-fit max-w-full overflow-hidden rounded-2xl px-4 py-3.5 text-[14px] leading-7 sm:px-5 ${
            isUser
              ? "rounded-tr-sm border border-blue-300/10 bg-blue-500/[0.12] text-slate-100"
              : "rounded-tl-sm border border-white/[0.07] bg-white/[0.035] text-slate-200"
          }`}
        >
          {/* User Image Attachment Badge */}
          {attachedImageName && (
            <div className="mb-2 overflow-hidden rounded-xl border border-blue-400/20 bg-blue-500/10">
              {message.imagePreviewUrl && (
                // Session-only preview. Uploaded bytes are not kept on the server.
                // eslint-disable-next-line @next/next/no-img-element
                <img src={message.imagePreviewUrl} alt="" className="max-h-48 w-full object-cover" />
              )}
              <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-blue-200">
                <ImageIcon size={14} className="shrink-0 text-blue-300" />
                <span className="truncate font-medium">{attachedImageName}</span>
              </div>
            </div>
          )}

          {/* Message Content */}
          {userTextBody ? (
            <div className="max-w-none break-words text-sm leading-7 [&_p]:my-2 [&_h1]:mb-2 [&_h1]:mt-5 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-4 [&_h3]:font-semibold [&_a]:text-blue-300 [&_a]:underline [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-6 [&_li]:my-1 [&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-violet-400/40 [&_blockquote]:pl-4 [&_blockquote]:text-slate-400 [&_strong]:font-semibold [&_strong]:text-white [&_hr]:my-4 [&_hr]:border-white/10">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ children, ...props }) => (
                    <a {...props} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  ),
                  pre: ({ children }) => (
                    <pre className="my-3 max-w-full overflow-x-auto rounded-xl border border-white/10 bg-[#080a12] p-4 text-xs leading-6">
                      {children}
                    </pre>
                  ),
                  code: ({ className, children, ...props }) => (
                    <code
                      {...props}
                      className={
                        className
                          ? `${className} rounded bg-black/35 px-1 py-0.5 text-violet-200`
                          : "rounded bg-black/35 px-1 py-0.5 font-mono text-[.9em] text-violet-200"
                      }
                    >
                      {children}
                    </code>
                  ),
                }}
              >
                {userTextBody}
              </ReactMarkdown>
            </div>
          ) : message.pending ? (
            <span className="text-slate-500">Thinking…</span>
          ) : null}

          {message.error && (
            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-rose-300/10 pt-3 text-sm text-rose-200">
              <span>{message.error}</span>
              {message.retryable && message.retryPrompt && (
                <button
                  className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200/15 px-2.5 py-1 text-xs text-rose-100 transition hover:bg-rose-200/10"
                  onClick={() => onRetry?.(message.retryPrompt!, false)}
                >
                  <RotateCcw size={12} /> Retry
                </button>
              )}
            </div>
          )}

          {audioError && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-rose-300">
              <AlertCircle size={12} />
              <span>{audioError}</span>
            </div>
          )}
        </div>

        {/* Action Controls for Assistant Message */}
        {!isUser && message.memoriesUsed && message.memoriesUsed.length > 0 && (
          <p className="mt-1.5 max-w-full px-1 text-[10px] leading-4 text-violet-200/80">
            Used {message.memoriesUsed.length} saved {message.memoriesUsed.length === 1 ? "memory" : "memories"}: {message.memoriesUsed.slice(0, 2).join(" · ")}
          </p>
        )}

        {!isUser && message.content && !message.pending && (
          <div className="mt-1.5 flex items-center gap-1.5">
            {/* Speaker / TTS Button */}
            <div className="inline-flex items-center gap-1">
              <button
                onClick={togglePlayAudio}
                disabled={audioState === "loading"}
                className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] transition ${
                  audioState === "playing"
                    ? "bg-violet-500/20 text-violet-200"
                    : audioState === "paused"
                    ? "bg-white/[0.08] text-slate-200"
                    : "text-slate-500 opacity-70 hover:bg-white/[0.05] hover:text-slate-300 sm:opacity-0 sm:group-hover:opacity-100"
                }`}
                aria-label={
                  audioState === "playing"
                    ? "Pause spoken response"
                    : audioState === "paused"
                    ? "Resume spoken response"
                    : "Listen to response"
                }
                title={
                  audioState === "playing"
                    ? "Pause audio"
                    : audioState === "paused"
                    ? "Resume audio"
                    : "Speak response (Text-to-Speech)"
                }
              >
                {audioState === "loading" ? (
                  <LoaderCircle size={12} className="animate-spin text-violet-400" />
                ) : audioState === "playing" ? (
                  <Pause size={12} className="fill-violet-300" />
                ) : audioState === "paused" ? (
                  <Play size={12} className="fill-slate-300" />
                ) : (
                  <Volume2 size={12} />
                )}
                <span>
                  {audioState === "loading"
                    ? "Synthesizing…"
                    : audioState === "playing"
                    ? "Pause"
                    : audioState === "paused"
                    ? "Resume"
                    : "Listen"}
                </span>
              </button>

              {(audioState === "playing" || audioState === "paused") && (
                <button
                  onClick={stopAudio}
                  className="rounded-md p-1 text-[11px] text-slate-500 hover:bg-white/[0.08] hover:text-slate-200 transition"
                  aria-label="Stop audio"
                  title="Stop playback"
                >
                  <Square size={11} className="fill-slate-400" />
                </button>
              )}
            </div>

            <button
              onClick={copyResponse}
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-slate-500 opacity-70 transition hover:bg-white/[0.05] hover:text-slate-300 sm:opacity-0 sm:group-hover:opacity-100"
              aria-label="Copy response"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? "Copied" : "Copy"}
            </button>

            {canRegenerate && !message.error && message.retryPrompt && (
              <button
                onClick={() => onRetry?.(message.retryPrompt!, true)}
                className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-slate-500 opacity-70 transition hover:bg-white/[0.05] hover:text-slate-300 sm:opacity-0 sm:group-hover:opacity-100"
                aria-label="Regenerate response"
              >
                <RotateCcw size={12} /> Regenerate
              </button>
            )}

            {feedbackAvailable && (
              feedback ? (
                <span className="text-[11px] text-emerald-300/80">
                  {feedback === "helpful" ? "Marked helpful" : "Feedback saved"}
                </span>
              ) : (
                <>
                  <button
                    onClick={() => void sendFeedback("helpful")}
                    disabled={feedbackBusy}
                    className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-slate-500 opacity-70 transition hover:bg-emerald-300/[0.07] hover:text-emerald-200 disabled:opacity-40 sm:opacity-0 sm:group-hover:opacity-100"
                    aria-label="Mark response helpful"
                    title="Helpful response"
                  >
                    <ThumbsUp size={12} />
                  </button>
                  <button
                    onClick={() => void sendFeedback("not_helpful")}
                    disabled={feedbackBusy}
                    className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-slate-500 opacity-70 transition hover:bg-rose-300/[0.07] hover:text-rose-200 disabled:opacity-40 sm:opacity-0 sm:group-hover:opacity-100"
                    aria-label="Mark response not helpful"
                    title="Not helpful"
                  >
                    <ThumbsDown size={12} />
                  </button>
                </>
              )
            )}
            {feedbackError && <span className="text-[11px] text-rose-300/80">{feedbackError}</span>}
          </div>
        )}
      </div>
    </article>
  );
}

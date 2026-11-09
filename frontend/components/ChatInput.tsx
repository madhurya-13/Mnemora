"use client";

import { FormEvent, KeyboardEvent, useRef, useState } from "react";
import { ArrowUp, LoaderCircle } from "lucide-react";

type Props = { disabled?: boolean; onSend: (message: string) => void };

export default function ChatInput({ disabled = false, onSend }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const canSend = value.trim().length > 0 && !disabled;

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const message = value.trim();
    if (!message || disabled) return;
    onSend(message);
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return <form onSubmit={submit} className="mx-auto w-full max-w-4xl">
    <div className="relative rounded-[22px] border border-white/[0.11] bg-[#11131e] shadow-[0_10px_50px_rgba(0,0,0,.25)] transition focus-within:border-violet-300/30 focus-within:shadow-[0_0_0_3px_rgba(139,115,255,.07)]">
      <textarea ref={textareaRef} rows={1} maxLength={8000} value={value} disabled={disabled} onChange={(event) => { setValue(event.target.value); event.target.style.height = "auto"; event.target.style.height = `${Math.min(event.target.scrollHeight, 192)}px`; }} onKeyDown={handleKeyDown} placeholder="Ask MNEMORA anything…" aria-label="Message MNEMORA" className="max-h-48 min-h-[58px] w-full resize-none bg-transparent py-4 pl-5 pr-16 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-600 disabled:opacity-60" />
      <button type="submit" disabled={!canSend} aria-label="Send message" className="absolute bottom-3 right-3 grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 text-white shadow-[0_4px_18px_rgba(112,83,255,.24)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-none disabled:bg-white/[0.07] disabled:text-slate-600 disabled:shadow-none">{disabled ? <LoaderCircle className="animate-spin" size={16} /> : <ArrowUp size={18} />}</button>
    </div>
    <p className="mt-2 text-center text-[10px] text-slate-600">Enter to send <span className="mx-1 text-slate-700">·</span> Shift + Enter for a new line <span className="mx-1 text-slate-700">·</span> Responses may be inaccurate</p>
  </form>;
}

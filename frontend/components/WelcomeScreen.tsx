"use client";

import { ArrowUpRight, Lightbulb, MessagesSquare, Puzzle, Sparkles } from "lucide-react";

const suggestions = [
  { icon: Puzzle, title: "Explain a difficult concept to me.", detail: "Make a complex idea easier to understand." },
  { icon: Lightbulb, title: "Help me brainstorm a project.", detail: "Explore ideas and find a useful direction." },
  { icon: Sparkles, title: "Teach me something new.", detail: "Follow your curiosity somewhere unexpected." },
  { icon: MessagesSquare, title: "Help me solve a problem.", detail: "Break a challenge into clear next steps." },
];

export default function WelcomeScreen({ onPrompt }: { onPrompt: (prompt: string) => void }) {
  return <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-5 pb-12 pt-8 sm:px-8">
    <div className="mb-8 grid h-12 w-12 place-items-center rounded-2xl border border-violet-300/15 bg-violet-300/[0.07] text-violet-200 shadow-[0_0_45px_rgba(129,92,255,.13)]"><Sparkles size={21} /></div>
    <p className="mb-4 text-xs font-medium uppercase tracking-[0.22em] text-violet-200/80">A new kind of personal assistant</p>
    <h1 className="max-w-2xl text-4xl font-medium leading-[1.13] tracking-[-0.04em] text-slate-100 sm:text-5xl">Your thoughts, conversations and ideas — <span className="bg-gradient-to-r from-violet-300 to-blue-300 bg-clip-text text-transparent">connected.</span></h1>
    <p className="mt-5 text-base text-slate-400">Meet your intelligent personal AI companion.</p>
    <div className="mt-10 grid gap-3 sm:grid-cols-2">
      {suggestions.map(({ icon: Icon, title, detail }) => <button key={title} onClick={() => onPrompt(title)} className="group flex min-h-[92px] items-start gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4 text-left transition hover:border-violet-300/20 hover:bg-violet-300/[0.045]"><span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/[0.045] text-violet-200"><Icon size={17} /></span><span className="min-w-0 flex-1"><span className="block text-sm font-medium text-slate-200">{title}</span><span className="mt-1 block text-xs leading-5 text-slate-500">{detail}</span></span><ArrowUpRight size={15} className="mt-1 text-slate-600 transition group-hover:text-violet-200" /></button>)}
    </div>
  </div>;
}

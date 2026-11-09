import { Brain } from "lucide-react";

export default function TypingIndicator() {
  return <div className="flex items-center gap-3 px-1 py-3" role="status" aria-label="MNEMORA is responding">
    <span className="grid h-8 w-8 place-items-center rounded-xl border border-violet-300/15 bg-violet-300/[0.07] text-violet-200"><Brain size={16} /></span>
    <span className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm border border-white/[0.07] bg-white/[0.035] px-4 py-3">
      <i className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-300 [animation-delay:-.25s]" />
      <i className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-300 [animation-delay:-.12s]" />
      <i className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-300" />
    </span>
  </div>;
}

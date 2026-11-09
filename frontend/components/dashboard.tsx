import { ArrowUpRight, Brain, Command, Cpu, Database, Fingerprint, Network, Sparkles } from "lucide-react";
import ConnectionStatus from "@/components/connection-status";

const systems = [
  { icon: Cpu, name: "Assistant core", detail: "Ready for setup", color: "text-violet-300" },
  { icon: Database, name: "Long-term memory", detail: "Not configured yet", color: "text-blue-300" },
  { icon: Network, name: "Knowledge network", detail: "Standing by", color: "text-cyan-300" },
];

export default function Dashboard() {
  return <main className="relative min-h-screen overflow-hidden">
    <div className="pointer-events-none absolute -top-48 left-1/2 h-[520px] w-[740px] -translate-x-1/2 rounded-full bg-violet-600/[0.11] blur-[130px]" />
    <div className="relative mx-auto max-w-6xl px-6 pb-16 pt-7 sm:px-10 lg:px-12">
      <header className="flex items-center justify-between border-b border-white/[0.08] pb-6">
        <a className="flex items-center gap-3" href="#home" aria-label="MNEMORA home"><span className="grid h-10 w-10 place-items-center rounded-xl border border-violet-300/20 bg-violet-400/10 text-violet-200"><Brain size={21} /></span><span className="text-sm font-semibold tracking-[0.24em]">MNEMORA</span></a>
        <div className="hidden items-center gap-2 text-xs text-slate-500 sm:flex"><Command size={14} /> PERSONAL INTELLIGENCE</div>
        <ConnectionStatus />
      </header>
      <section id="home" className="grid gap-12 pb-20 pt-20 md:grid-cols-[1.2fr_.8fr] md:items-center md:pt-28">
        <div><div className="mb-7 inline-flex items-center gap-2 rounded-full border border-violet-300/15 bg-violet-300/[0.06] px-3 py-1.5 text-xs text-violet-200"><Sparkles size={13} /> YOUR PERSONAL AI, TAKING SHAPE</div>
          <h1 className="max-w-2xl text-5xl font-medium leading-[1.08] tracking-[-0.045em] sm:text-6xl lg:text-7xl">An AI that <span className="bg-gradient-to-r from-violet-300 via-indigo-300 to-blue-300 bg-clip-text text-transparent">remembers,</span> learns and evolves.</h1>
          <p className="mt-7 max-w-xl text-base leading-7 text-slate-400 sm:text-lg">A thoughtful assistant built around what matters to you. Your conversations will become context that grows more useful over time.</p>
          <div className="mt-9 flex flex-wrap items-center gap-4 text-sm text-slate-400"><span className="flex items-center gap-2"><Fingerprint size={16} className="text-violet-300" /> Personal by design</span><span className="h-1 w-1 rounded-full bg-slate-600" /><span>Built to grow with you</span></div>
        </div>
        <div className="relative mx-auto flex aspect-square w-full max-w-[350px] items-center justify-center"><div className="absolute inset-4 rounded-full border border-violet-300/[0.09]" /><div className="absolute inset-12 rounded-full border border-blue-300/[0.12]" /><div className="absolute inset-[27%] rounded-full bg-gradient-to-br from-violet-500/20 to-blue-500/10 blur-2xl" /><div className="relative grid h-32 w-32 place-items-center rounded-[2rem] border border-white/10 bg-[#131524]/90 shadow-glow"><Brain size={52} strokeWidth={1.15} className="text-violet-200" /><span className="absolute -right-3 -top-3 h-3 w-3 rounded-full bg-blue-300 shadow-[0_0_20px_rgba(147,197,253,.8)]" /></div><span className="absolute left-5 top-1/3 h-2 w-2 rounded-full bg-violet-300/70" /><span className="absolute bottom-12 right-10 h-1.5 w-1.5 rounded-full bg-blue-300/80" /></div>
      </section>
      <section aria-labelledby="system-title"><div className="mb-5 flex items-end justify-between"><div><p className="text-xs font-medium uppercase tracking-[0.2em] text-slate-500">Overview</p><h2 id="system-title" className="mt-2 text-xl font-medium">System status</h2></div><span className="text-xs text-slate-500">Milestone 1 · Foundation</span></div>
        <div className="grid gap-4 md:grid-cols-3">{systems.map(({ icon: Icon, name, detail, color }) => <article key={name} className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-5 transition-colors hover:border-white/[0.14]"><div className="flex items-center justify-between"><span className={`grid h-10 w-10 place-items-center rounded-xl bg-white/[0.045] ${color}`}><Icon size={19} /></span><ArrowUpRight size={16} className="text-slate-600" /></div><h3 className="mt-5 text-sm font-medium">{name}</h3><p className="mt-1 text-sm text-slate-500">{detail}</p></article>)}</div>
      </section>
      <footer className="mt-16 flex flex-col gap-2 border-t border-white/[0.08] pt-6 text-xs text-slate-600 sm:flex-row sm:justify-between"><span>MNEMORA <span className="text-slate-700">·</span> An AI that remembers, learns and evolves.</span><span>Private context. Built over time.</span></footer>
    </div>
  </main>;
}

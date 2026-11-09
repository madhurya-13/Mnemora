"use client";

import { Activity, CheckCircle2, CircleAlert, LoaderCircle } from "lucide-react";
import { useBackendHealth } from "@/hooks/use-backend-health";

export default function ConnectionStatus() {
  const { state, version } = useBackendHealth();

  const connected = state === "connected";
  const label = state === "checking" ? "Checking connection" : connected ? "Connected" : "Disconnected";
  return <div className="flex items-center gap-3 rounded-full border border-white/10 bg-white/[0.035] px-4 py-2.5" aria-live="polite">
    {state === "checking" ? <LoaderCircle className="h-4 w-4 animate-spin text-violet-300" /> : connected ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <CircleAlert className="h-4 w-4 text-rose-400" />}
    <span className={`h-1.5 w-1.5 rounded-full ${state === "checking" ? "bg-violet-300" : connected ? "bg-emerald-400" : "bg-rose-400"}`} />
    <span className="text-sm text-slate-300">API {label}</span>
    {connected && <span className="hidden text-xs text-slate-500 sm:inline">v{version}</span>}
    <Activity className="ml-1 h-4 w-4 text-slate-500" />
  </div>;
}

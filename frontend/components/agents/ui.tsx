import type { ReactNode } from "react";

export function cx(...values: (string | false | null | undefined)[]) {
  return values.filter(Boolean).join(" ");
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatDuration(milliseconds: number): string {
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "0 ms";
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  return `${(milliseconds / 1000).toFixed(1)} s`;
}

export function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

const STATUS_STYLES: Record<string, string> = {
  draft: "border-slate-400/20 bg-slate-400/10 text-slate-300",
  needs_clarification: "border-amber-300/25 bg-amber-300/10 text-amber-200",
  approved: "border-sky-300/25 bg-sky-300/10 text-sky-200",
  running: "border-violet-300/25 bg-violet-300/10 text-violet-200",
  executing: "border-violet-300/25 bg-violet-300/10 text-violet-200",
  awaiting_approval: "border-amber-300/25 bg-amber-300/10 text-amber-200",
  paused: "border-slate-300/20 bg-slate-300/10 text-slate-200",
  completed: "border-emerald-300/25 bg-emerald-300/10 text-emerald-200",
  verified: "border-emerald-300/25 bg-emerald-300/10 text-emerald-200",
  partially_completed: "border-amber-300/25 bg-amber-300/10 text-amber-200",
  partially_verified: "border-amber-300/25 bg-amber-300/10 text-amber-200",
  failed: "border-rose-300/25 bg-rose-300/10 text-rose-200",
  cancelled: "border-slate-400/20 bg-slate-400/10 text-slate-300",
  archived: "border-slate-400/20 bg-slate-400/10 text-slate-400",
  pending: "border-sky-300/20 bg-sky-300/10 text-sky-200",
  ready: "border-sky-300/20 bg-sky-300/10 text-sky-200",
  skipped: "border-slate-400/20 bg-slate-400/10 text-slate-400",
  not_verifiable: "border-slate-400/20 bg-slate-400/10 text-slate-300",
  consumed: "border-emerald-300/25 bg-emerald-300/10 text-emerald-200",
  expired: "border-slate-400/20 bg-slate-400/10 text-slate-300",
  rejected: "border-rose-300/25 bg-rose-300/10 text-rose-200",
  suggested: "border-sky-300/25 bg-sky-300/10 text-sky-200",
  active: "border-emerald-300/25 bg-emerald-300/10 text-emerald-200",
};

export function StatusPill({ status, className }: { status: string; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em]",
        STATUS_STYLES[status] ?? "border-white/10 bg-white/[0.04] text-slate-300",
        className,
      )}
    >
      {humanize(status)}
    </span>
  );
}

export function ProgressBar({
  value,
  label = "Progress",
  definition,
}: {
  value: number;
  label?: string;
  definition?: string;
}) {
  const bounded = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-[11px] text-slate-400">
        <span>{label}</span>
        <span className="font-medium text-slate-200">{bounded}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-full rounded-full bg-gradient-to-r from-violet-400 to-blue-400 transition-all"
          style={{ width: `${bounded}%` }}
        />
      </div>
      {definition && <p className="mt-1.5 text-[10px] leading-4 text-slate-500">{definition}</p>}
    </div>
  );
}

export function Panel({
  children,
  className,
  title,
  description,
  action,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <section
      className={cx(
        "rounded-2xl border border-white/[0.07] bg-[#0d101a]/90 p-4 shadow-[0_18px_60px_rgba(3,5,12,0.35)]",
        className,
      )}
    >
      {(title || action) && (
        <header className="mb-3 flex items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-100">{title}</h2>}
            {description && <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-xs leading-6 text-slate-500">
      {children}
    </div>
  );
}

export function Alert({ tone = "error", children }: { tone?: "error" | "info" | "success"; children: ReactNode }) {
  const styles = {
    error: "border-rose-300/20 bg-rose-300/[0.06] text-rose-100",
    info: "border-sky-300/20 bg-sky-300/[0.06] text-sky-100",
    success: "border-emerald-300/20 bg-emerald-300/[0.06] text-emerald-100",
  }[tone];
  return <div className={cx("rounded-xl border px-3 py-2 text-xs leading-5", styles)}>{children}</div>;
}

export function KeyValue({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</dt>
      <dd className="mt-1 text-xs text-slate-200">{children}</dd>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[11px] text-slate-400">
      <span className="h-3 w-3 animate-spin rounded-full border border-violet-300/30 border-t-violet-300" />
      {label ?? "Working…"}
    </span>
  );
}

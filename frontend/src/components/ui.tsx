"use client";

import { FILE_TYPE_LABEL, FILE_TYPE_STYLE } from "@/lib/format";

export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <span
      className="inline-flex items-center justify-center rounded-[9px] bg-ink text-white"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg width={size * 0.56} height={size * 0.56} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M8 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h2" />
        <path d="M16 5h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-2" />
        <path d="M9 12h6" />
      </svg>
    </span>
  );
}

export function FileBadge({ type, className = "" }: { type: string; className?: string }) {
  return (
    <span
      className={`inline-flex min-w-[42px] items-center justify-center rounded-[5px] px-1.5 py-0.5 text-[10.5px] font-bold tracking-wide ${
        FILE_TYPE_STYLE[type] ?? "bg-[#f0f1f4] text-ink-2"
      } ${className}`}
    >
      {(FILE_TYPE_LABEL[type] ?? type).toUpperCase()}
    </span>
  );
}

const STATUS: Record<string, string> = {
  ready: "bg-ok-soft text-ok",
  processing: "bg-accent-soft text-accent-strong",
  failed: "bg-bad-soft text-bad",
  done: "bg-ok-soft text-ok",
  running: "bg-accent-soft text-accent-strong",
  queued: "bg-[#f0f1f4] text-ink-2",
};

const STATUS_LABEL: Record<string, string> = {
  ready: "Ready",
  processing: "Reading…",
  failed: "Failed",
  done: "Done",
  running: "Running",
  queued: "Queued",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS[status] ?? STATUS.queued}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-line bg-panel ${className}`}>{children}</section>;
}

export function Button({
  children,
  variant = "secondary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" | "accent" }) {
  const styles = {
    primary: "bg-ink text-white hover:bg-[#2a2d35] border border-ink",
    accent: "bg-accent text-white hover:bg-accent-strong border border-accent",
    secondary: "bg-panel text-ink border border-line hover:bg-[#f0f1f4]",
    danger: "bg-panel text-bad border border-[#f3c9c5] hover:bg-bad-soft",
    ghost: "bg-transparent text-ink-2 border border-transparent hover:bg-[#eceef2]",
  }[variant];
  return (
    <button
      type="button"
      className={`inline-flex min-h-9 items-center justify-center gap-2 rounded-[10px] px-3.5 text-[13.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

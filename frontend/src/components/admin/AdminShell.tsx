"use client";

import { FlaskConical, FolderOpen, Gauge, LayoutDashboard, MessageSquare, Search, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { LogoMark } from "@/components/ui";

const NAV = [
  { href: "/admin", label: "Overview", icon: LayoutDashboard },
  { href: "/admin/documents", label: "Documents", icon: FolderOpen },
  { href: "/admin/retrieval", label: "Retrieval lab", icon: Search },
  { href: "/admin/evaluation", label: "Evaluation", icon: Gauge },
  { href: "/admin/settings", label: "Settings", icon: Settings },
];

export default function AdminShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className="flex min-h-dvh flex-col bg-ground text-ink lg:flex-row">
      <aside className="flex shrink-0 flex-col gap-4 border-b border-line bg-[#fbfbfc] px-3.5 py-4 lg:sticky lg:top-0 lg:h-dvh lg:w-[236px] lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2.5 px-1.5">
          <LogoMark />
          <div className="leading-tight">
            <div className="text-[17px] font-semibold">Clause</div>
            <div className="text-[11.5px] text-mute">Claude console</div>
          </div>
        </div>
        <nav aria-label="Admin" className="flex flex-row flex-wrap gap-0.5 lg:flex-col">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/admin" ? path === "/admin" : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-10 items-center gap-2.5 rounded-[9px] px-2.5 text-[14px] ${
                  active ? "bg-[#e9ecf3] font-semibold text-ink" : "text-ink-2 hover:bg-[#eceef2]"
                }`}
              >
                <Icon size={16} /> {label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto hidden flex-col gap-1 border-t border-line pt-3 lg:flex">
          <div className="flex items-center gap-2 px-2.5 text-[12px] text-faint">
            <FlaskConical size={13} /> Technical details live here, not in chat.
          </div>
          <Link href="/" className="flex min-h-10 items-center gap-2.5 rounded-[9px] px-2.5 text-[14px] text-ink-2 hover:bg-[#eceef2]">
            <MessageSquare size={16} /> Open chat
          </Link>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-7">{children}</main>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description: string; actions?: React.ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[26px] font-semibold tracking-[-0.015em]">{title}</h1>
        <p className="mt-1 max-w-[70ch] text-[14px] text-mute">{description}</p>
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "ok" | "warn" | "bad" }) {
  const toneClass = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : "text-mute";
  return (
    <div className="flex flex-col gap-1 rounded-2xl border border-line bg-panel px-[18px] py-4">
      <span className="text-[12.5px] text-mute">{label}</span>
      <span className="text-[28px] font-semibold tabular-nums tracking-[-0.01em]">{value}</span>
      {hint && <span className={`text-[12.5px] ${toneClass}`}>{hint}</span>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return <div className="mb-4 rounded-xl border border-[#f3c9c5] bg-bad-soft/60 px-4 py-3 text-[13.5px] text-[#7a1810]">{message}</div>;
}

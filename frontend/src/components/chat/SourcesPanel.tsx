"use client";

import { Check, Copy, ExternalLink, X } from "lucide-react";
import { useState } from "react";

import { FileBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { locationLabel } from "@/lib/format";
import type { Source } from "@/lib/types";

function Highlighted({ text, highlight }: { text: string; highlight: string }) {
  const idx = highlight ? text.indexOf(highlight) : -1;
  if (idx < 0) return <p className="whitespace-pre-line">{text}</p>;
  return (
    <p className="whitespace-pre-line">
      {text.slice(0, idx)}
      <mark className="rounded-[3px] bg-[#e6ecfd] px-0.5 text-ink shadow-[inset_0_-2px_0_var(--color-accent)]">{highlight}</mark>
      {text.slice(idx + highlight.length)}
    </p>
  );
}

export function SourcesPanel({
  sources,
  selected,
  onSelect,
  onClose,
}: {
  sources: Source[];
  selected: number | null;
  onSelect: (n: number) => void;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const current = sources.find((s) => s.n === selected) ?? sources[0];

  if (!current) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(current.highlight || current.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };

  return (
    <aside aria-label="Sources" className="flex h-full min-w-0 flex-col gap-4 overflow-y-auto border-l border-line bg-[#fbfbfc] px-4 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[15px] font-semibold">Sources</h2>
          <span className="text-[12.5px] text-mute">
            {sources.length} {sources.length === 1 ? "passage" : "passages"}
          </span>
        </div>
        <button type="button" onClick={onClose} aria-label="Close sources" className="rounded-lg p-1.5 text-mute hover:bg-[#eceef2]">
          <X size={16} />
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-line bg-panel">
        <div className="flex items-center gap-2.5 border-b border-line-soft px-3.5 py-3">
          <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-accent px-1.5 text-[11.5px] font-semibold text-white">
            {current.n}
          </span>
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold">{current.filename}</div>
            <div className="text-xs text-mute">{locationLabel(current.page, current.section) || "Whole document"}</div>
          </div>
        </div>
        <div className="max-h-[340px] overflow-y-auto px-4 py-3.5 text-[13.5px] leading-relaxed text-ink-2">
          <Highlighted text={current.text} highlight={current.highlight} />
        </div>
        <div className="flex flex-wrap gap-2 px-4 pb-3.5">
          <a
            href={api.fileUrl(current.document_id, { page: current.file_type === "pdf" ? current.page : null })}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-8 items-center gap-1.5 rounded-[9px] border border-line px-3 text-[12.5px] hover:bg-[#f0f1f4]"
          >
            <ExternalLink size={14} />
            {current.page ? `Open at page ${current.page}` : "Open document"}
          </a>
          <button
            type="button"
            onClick={copy}
            className="inline-flex min-h-8 items-center gap-1.5 rounded-[9px] border border-line bg-panel px-3 text-[12.5px] hover:bg-[#f0f1f4]"
          >
            {copied ? <Check size={14} className="text-ok" /> : <Copy size={14} />}
            {copied ? "Copied" : "Copy quote"}
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.07em] text-faint">In this answer</span>
        {sources.map((s) => (
          <button
            key={s.n}
            type="button"
            onClick={() => onSelect(s.n)}
            aria-pressed={s.n === current.n}
            className={`flex w-full items-start gap-2.5 rounded-[11px] border bg-panel px-3 py-2.5 text-left transition-colors ${
              s.n === current.n ? "border-accent" : "border-line hover:border-[#c9ceda]"
            }`}
          >
            <span
              className={`mt-[1px] inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] px-[5px] text-[11px] font-semibold ${
                s.n === current.n ? "bg-accent text-white" : "bg-accent-soft text-accent-strong"
              }`}
            >
              {s.n}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                <span className="truncate text-[13px] font-medium">{s.filename}</span>
                <FileBadge type={s.file_type} className="shrink-0 scale-90" />
              </span>
              <span className="block text-xs text-mute">{locationLabel(s.page, s.section) || "Whole document"}</span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

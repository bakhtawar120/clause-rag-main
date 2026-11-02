"use client";

import { Check, ChevronDown, CornerDownLeft, Layers, Plus, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { FileBadge, Spinner } from "@/components/ui";
import { ACCEPTED_FILES } from "@/lib/format";
import type { DocumentInfo } from "@/lib/types";

export interface PendingUpload {
  key: string;
  name: string;
  progress: number; // 0..1 upload progress
  state: "uploading" | "reading" | "ready" | "failed";
  error?: string;
  fileType?: string;
}

export function Composer({
  busy,
  onSend,
  onStop,
  onFiles,
  uploads,
  onDismissUpload,
  chatDocs,
  scope,
  setScope,
  strict,
  setStrict,
}: {
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onFiles: (files: File[]) => void;
  uploads: PendingUpload[];
  onDismissUpload: (key: string) => void;
  chatDocs: DocumentInfo[];
  scope: "all" | "chat";
  setScope: (s: "all" | "chat") => void;
  strict: boolean;
  setStrict: (v: boolean) => void;
}) {
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const scopeRef = useRef<HTMLDivElement>(null);
  const [scopeOpen, setScopeOpen] = useState(false);

  useEffect(() => {
    if (!scopeOpen) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !scopeRef.current?.contains(e.target as Node)) setScopeOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [scopeOpen]);

  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const submit = () => {
    const value = text.trim();
    if (!value || busy) return;
    onSend(value);
    setText("");
  };

  const readyChatDocs = chatDocs.filter((d) => d.status === "ready");
  const hasText = text.trim().length > 0;

  return (
    <div className="mx-auto w-full max-w-[760px]">
      <div
        className="rounded-[18px] border border-[#dadde4] bg-panel py-2 pl-3 pr-2 shadow-[0_1px_2px_rgba(21,23,28,0.04),0_8px_24px_rgba(21,23,28,0.05)] transition-[border-color,box-shadow] focus-within:border-[#b4b9c4] focus-within:shadow-[0_1px_2px_rgba(21,23,28,0.05),0_10px_30px_rgba(21,23,28,0.08)]"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (e.dataTransfer.files.length) onFiles(Array.from(e.dataTransfer.files));
        }}
      >
        {uploads.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {uploads.map((u) => (
              <div
                key={u.key}
                className={`flex min-w-[220px] max-w-full items-center gap-2.5 rounded-[10px] border px-2 py-1.5 ${
                  u.state === "failed" ? "border-[#f3c9c5] bg-bad-soft/40" : "border-line bg-subtle"
                }`}
              >
                {u.fileType ? <FileBadge type={u.fileType} /> : <Spinner className="text-accent" />}
                <div className="min-w-0 flex-1 leading-tight">
                  <div className="truncate text-[12.5px] font-medium">{u.name}</div>
                  {u.state === "uploading" && (
                    <div className="mt-1 flex items-center gap-2">
                      <div className="h-1 flex-1 overflow-hidden rounded bg-line">
                        <div className="h-1 bg-accent transition-all" style={{ width: `${Math.round(u.progress * 100)}%` }} />
                      </div>
                      <span className="text-[11px] tabular-nums text-mute">{Math.round(u.progress * 100)}%</span>
                    </div>
                  )}
                  {u.state === "reading" && <div className="text-[11px] text-mute">Reading the document…</div>}
                  {u.state === "ready" && <div className="text-[11px] text-ok">Ready to use in this chat</div>}
                  {u.state === "failed" && <div className="text-[11px] text-bad">{u.error ?? "Couldn't read this file"}</div>}
                </div>
                {(u.state === "ready" || u.state === "failed") && (
                  <button
                    type="button"
                    onClick={() => onDismissUpload(u.key)}
                    aria-label={`Dismiss ${u.name}`}
                    className="rounded-md p-1 text-faint hover:bg-[#eceef2]"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        <label htmlFor="ask" className="sr-only">
          Ask Clause
        </label>
        <div className="flex items-end gap-2">
          <textarea
            id="ask"
            ref={area}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={chatDocs.length ? "Reply…" : "Ask anything about your documents…"}
            className="max-h-[200px] min-h-[36px] flex-1 resize-none bg-transparent px-1 py-[7px] text-[15px] leading-[22px] text-ink outline-none placeholder:text-faint"
          />
          {busy ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop"
              title="Stop"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-[#eceef2] text-ink transition-colors hover:bg-[#e2e5ea]"
            >
              <Square size={12} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!hasText}
              aria-label="Send"
              title="Send (Enter)"
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] transition-all duration-150 ${
                hasText ? "bg-[#eceef2] text-ink hover:bg-[#e2e5ea]" : "text-faint"
              }`}
            >
              <CornerDownLeft size={17} strokeWidth={hasText ? 2.25 : 2} />
            </button>
          )}
        </div>
      </div>

      <div className="mt-2 flex items-center gap-1 px-1 text-[13px]">
        <input
          ref={fileInput}
          type="file"
          multiple
          accept={ACCEPTED_FILES}
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) onFiles(Array.from(e.target.files));
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          aria-label="Attach files"
          title="Attach files (PDF, Word, CSV, text, Markdown, HTML)"
          className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-[#eceef2] hover:text-ink"
        >
          <Plus size={18} />
        </button>

        <div ref={scopeRef} className="relative">
          <button
            type="button"
            onClick={() => setScopeOpen((o) => !o)}
            aria-haspopup="listbox"
            aria-expanded={scopeOpen}
            title="Which documents to answer from"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-ink-2 transition-colors hover:bg-[#eceef2] hover:text-ink"
          >
            <Layers size={15} aria-hidden="true" />
            <span className="max-w-[160px] truncate">{scope === "all" ? "All documents" : `This chat's files (${readyChatDocs.length})`}</span>
            <ChevronDown size={14} className={`text-faint transition-transform ${scopeOpen ? "rotate-180" : ""}`} aria-hidden="true" />
          </button>
          {scopeOpen && (
            <div
              role="listbox"
              aria-label="Answer from"
              className="absolute bottom-full left-0 z-20 mb-1.5 w-[240px] rounded-xl border border-line bg-panel p-1 shadow-[0_8px_28px_rgba(21,23,28,0.12)]"
            >
              {(
                [
                  { value: "all", label: "All documents", hint: "Search your whole library", disabled: false },
                  {
                    value: "chat",
                    label: `This chat's files${readyChatDocs.length ? ` (${readyChatDocs.length})` : ""}`,
                    hint: readyChatDocs.length ? "Only files attached here" : "Attach files to this chat first",
                    disabled: readyChatDocs.length === 0,
                  },
                ] as const
              ).map((o) => (
                <button
                  key={o.value}
                  type="button"
                  role="option"
                  aria-selected={scope === o.value}
                  disabled={o.disabled}
                  onClick={() => {
                    setScope(o.value);
                    setScopeOpen(false);
                  }}
                  className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-[#f3f4f7] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-ink">{o.label}</span>
                    <span className="block text-[12px] text-mute">{o.hint}</span>
                  </span>
                  {scope === o.value && <Check size={15} className="mt-0.5 text-ink-2" aria-hidden="true" />}
                </button>
              ))}
            </div>
          )}
        </div>

        <p className="hidden min-w-0 flex-1 truncate px-2 text-center text-[12.5px] text-faint md:block">
          {strict ? "Answers come only from your documents. Check important ones." : "General knowledge is marked. Document facts are cited."}
        </p>
        <span className="flex-1 md:hidden" />

        <button
          type="button"
          role="switch"
          aria-checked={strict}
          onClick={() => setStrict(!strict)}
          title={strict ? "Answer only from your documents" : "Allow general knowledge (marked)"}
          className="inline-flex h-8 items-center gap-2 rounded-lg px-2 text-ink-2 transition-colors hover:bg-[#eceef2] hover:text-ink"
        >
          Sources only
          <span className={`relative h-[18px] w-8 rounded-full transition-colors ${strict ? "bg-ink-2" : "bg-[#c9ceda]"}`}>
            <span
              className={`absolute top-[3px] h-3 w-3 rounded-full bg-white shadow-sm transition-all ${strict ? "left-[17px]" : "left-[3px]"}`}
            />
          </span>
        </button>
      </div>
    </div>
  );
}

"use client";

import { Download, FileArchive, RefreshCw, Sparkles, Trash2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorNote, PageHeader } from "@/components/admin/AdminShell";
import { Button, Card, FileBadge, Spinner, StatusPill } from "@/components/ui";
import { api, uploadFiles } from "@/lib/api";
import { ACCEPTED_FILES, formatBytes, locationLabel, timeAgo } from "@/lib/format";
import type { ChunkInfo, DocumentInfo, SampleDoc } from "@/lib/types";

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [samples, setSamples] = useState<SampleDoc[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [inspect, setInspect] = useState<{ doc: DocumentInfo; chunks: ChunkInfo[] } | null>(null);
  const [scope, setScope] = useState<"library" | "all">("library");
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setDocs(await api.listDocuments(scope));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [scope]);

  useEffect(() => {
    load();
    api.listSamples().then(setSamples).catch(() => undefined);
  }, [load]);

  const upload = async (files: File[]) => {
    if (!files.length) return;
    setUploading(0);
    try {
      const results = await uploadFiles(files, { onProgress: setUploading });
      const failed = results.filter((r) => r.error || r.document?.status === "failed");
      const dup = results.filter((r) => r.duplicate).length;
      setMessage(
        `${results.length - failed.length} of ${results.length} files ready${dup ? ` (${dup} already in the library)` : ""}` +
          (failed.length ? `. Failed: ${failed.map((r) => `${r.filename} (${r.error ?? r.document?.error})`).join("; ")}` : "."),
      );
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(null);
    }
  };

  const importSamples = async () => {
    setBusyId("samples");
    try {
      const results = await api.importSamples();
      setMessage(`${results.filter((r) => r.document?.status === "ready").length} sample documents are in the library.`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const act = async (doc: DocumentInfo, action: "reindex" | "delete") => {
    if (action === "delete" && busyId !== `confirm-${doc.id}`) {
      setBusyId(`confirm-${doc.id}`);
      return;
    }
    setBusyId(doc.id);
    try {
      if (action === "reindex") await api.reindexDocument(doc.id);
      else await api.deleteDocument(doc.id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const openChunks = async (doc: DocumentInfo) => {
    try {
      setInspect({ doc, chunks: await api.getChunks(doc.id) });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader
        title="Documents"
        description="Every document Clause can search: upload many at once, check each file's status, inspect its chunks, re-index or delete."
        actions={
          <>
            <Button onClick={importSamples} disabled={busyId === "samples"}>
              {busyId === "samples" ? <Spinner /> : <Sparkles size={15} />} Add sample documents
            </Button>
            <Button variant="primary" onClick={() => input.current?.click()} disabled={uploading !== null}>
              {uploading !== null ? <Spinner /> : <Upload size={15} />} Upload files
            </Button>
          </>
        }
      />
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPTED_FILES}
        className="hidden"
        onChange={(e) => {
          upload(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      {error && <ErrorNote message={error} />}
      {message && (
        <div className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-line bg-panel px-4 py-3 text-[13.5px]">
          <span>{message}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setMessage(null)} className="text-faint hover:text-ink">
            <X size={15} />
          </button>
        </div>
      )}

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          upload(Array.from(e.dataTransfer.files));
        }}
        className="mb-4 rounded-2xl border-[1.5px] border-dashed border-[#c9ceda] bg-[#fafbfc] px-5 py-5 text-center text-[13px] text-mute"
      >
        {uploading !== null ? (
          <div className="mx-auto flex max-w-sm flex-col gap-2">
            <span>{uploading < 1 ? `Uploading… ${Math.round(uploading * 100)}%` : "Reading, chunking and indexing…"}</span>
            <div className="h-1.5 overflow-hidden rounded bg-line">
              <div className="h-1.5 bg-accent transition-all" style={{ width: `${Math.round(uploading * 100)}%` }} />
            </div>
          </div>
        ) : (
          "Drop files here: PDF, Word (.docx), CSV, Markdown, plain text, HTML"
        )}
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">{docs.length} documents</h2>
          <div className="inline-flex rounded-[10px] border border-line p-0.5 text-[13px]" role="radiogroup" aria-label="Show">
            {(["library", "all"] as const).map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={scope === s}
                onClick={() => setScope(s)}
                className={`rounded-[8px] px-3 py-1 ${scope === s ? "bg-[#eceef2] font-medium" : "text-mute"}`}
              >
                {s === "library" ? "Shared library" : "Including chat uploads"}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-[13.5px]">
            <thead>
              <tr className="border-y border-line bg-subtle text-left text-xs font-semibold text-mute">
                <th className="px-5 py-2.5">File</th>
                <th className="px-3 py-2.5">Status</th>
                <th className="px-3 py-2.5 text-right">Pages</th>
                <th className="px-3 py-2.5 text-right">Chunks</th>
                <th className="px-3 py-2.5">Added</th>
                <th className="px-5 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {docs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center text-mute">
                    No documents yet. Upload files or add the sample documents.
                  </td>
                </tr>
              )}
              {docs.map((d) => (
                <tr key={d.id} className="border-b border-line-soft hover:bg-subtle">
                  <td className="px-5 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <FileBadge type={d.file_type} />
                      <div className="min-w-0">
                        <button type="button" onClick={() => openChunks(d)} className="truncate text-left font-medium hover:text-accent">
                          {d.filename}
                        </button>
                        <div className="text-xs text-mute">
                          {formatBytes(d.size_bytes)}
                          {d.conversation_id ? " · uploaded in a chat" : ""}
                        </div>
                        {d.error && <div className="text-xs text-bad">{d.error}</div>}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusPill status={d.status} />
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-ink-2">{d.pages ?? "–"}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-ink-2">{d.chunk_count}</td>
                  <td className="px-3 py-2.5 text-mute">{timeAgo(d.created_at)}</td>
                  <td className="px-5 py-2.5">
                    <div className="flex justify-end gap-1">
                      <a
                        href={api.fileUrl(d.id, { download: true })}
                        aria-label={`Download ${d.filename}`}
                        title="Download original"
                        className="rounded-lg p-2 text-mute hover:bg-[#eceef2]"
                      >
                        <Download size={15} />
                      </a>
                      <button
                        type="button"
                        onClick={() => act(d, "reindex")}
                        disabled={busyId === d.id}
                        aria-label={`Re-index ${d.filename}`}
                        title="Re-index"
                        className="rounded-lg p-2 text-mute hover:bg-[#eceef2] disabled:opacity-40"
                      >
                        {busyId === d.id ? <Spinner /> : <RefreshCw size={15} />}
                      </button>
                      <button
                        type="button"
                        onClick={() => act(d, "delete")}
                        aria-label={`Delete ${d.filename}`}
                        title={busyId === `confirm-${d.id}` ? "Click again to delete" : "Delete"}
                        className={`rounded-lg p-2 hover:bg-bad-soft ${busyId === `confirm-${d.id}` ? "bg-bad-soft text-bad" : "text-mute"}`}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="mt-4 p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-[15px] font-semibold">Test documents</h2>
            <p className="text-[12.5px] text-mute">
              The documents behind the evaluation golden set. Download them to test Clause yourself.
            </p>
          </div>
          <a href={api.samplesZipUrl()} className="inline-flex min-h-9 items-center gap-2 rounded-[10px] border border-line px-3.5 text-[13.5px] font-medium hover:bg-[#f0f1f4]">
            <FileArchive size={15} /> Download all (.zip)
          </a>
        </div>
        <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {samples.map((s) => (
            <li key={s.filename}>
              <a
                href={api.sampleUrl(s.filename)}
                className="flex items-center gap-3 rounded-xl border border-line px-3.5 py-2.5 hover:border-[#c9ceda] hover:bg-subtle"
              >
                <FileBadge type={s.file_type} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] font-medium">{s.filename}</span>
                  <span className="block truncate text-xs text-mute">{s.description}</span>
                </span>
                <span className="text-xs text-faint">{formatBytes(s.size_bytes)}</span>
                <Download size={15} className="text-mute" />
              </a>
            </li>
          ))}
        </ul>
      </Card>

      {inspect && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/25" onClick={() => setInspect(null)}>
          <aside
            role="dialog"
            aria-label={`Chunks of ${inspect.doc.filename}`}
            onClick={(e) => e.stopPropagation()}
            className="flex h-full w-[min(560px,100vw)] flex-col bg-panel shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
              <div className="min-w-0">
                <h2 className="truncate text-[16px] font-semibold">{inspect.doc.filename}</h2>
                <p className="text-[12.5px] text-mute">
                  {inspect.chunks.length} chunks · {inspect.doc.pages ? `${inspect.doc.pages} pages · ` : ""}
                  {formatBytes(inspect.doc.size_bytes)}
                </p>
              </div>
              <button type="button" onClick={() => setInspect(null)} aria-label="Close" className="rounded-lg p-1.5 text-mute hover:bg-[#eceef2]">
                <X size={17} />
              </button>
            </div>
            <div className="flex-1 space-y-2.5 overflow-y-auto p-5">
              {inspect.chunks.map((c) => (
                <div key={c.id} className="rounded-xl border border-line-soft bg-subtle p-3">
                  <div className="mb-1.5 font-mono text-[11.5px] text-mute">
                    #{c.chunk_index} · id {c.id} · {c.char_count} chars{locationLabel(c.page, c.section) ? ` · ${locationLabel(c.page, c.section)}` : ""}
                  </div>
                  <p className="whitespace-pre-line text-[13px] leading-relaxed text-ink-2">{c.text}</p>
                </div>
              ))}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

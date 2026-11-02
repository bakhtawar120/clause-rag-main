"use client";

import {
  Check,
  Copy,
  FileText,
  LayoutDashboard,
  Menu,
  MessageSquarePlus,
  PanelRight,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Answer } from "@/components/chat/Answer";
import { Composer, type PendingUpload } from "@/components/chat/Composer";
import { EmptyState } from "@/components/chat/EmptyState";
import { SourcesPanel } from "@/components/chat/SourcesPanel";
import { FileBadge, LogoMark } from "@/components/ui";
import { ApiError, api, streamChat, uploadFiles } from "@/lib/api";
import { ACCEPTED_FILES, timeAgo } from "@/lib/format";
import type { Conversation, DocumentInfo, Message, Source } from "@/lib/types";

interface UIMessage extends Message {
  key: string;
  pending?: boolean;
  status?: string;
  error?: boolean;
}

let localCounter = 0;
const localKey = () => `local-${Date.now()}-${localCounter++}`;

function citedSources(m: UIMessage): Source[] {
  const all = m.sources ?? [];
  const cited = all.filter((s) => s.cited);
  return cited.length ? cited : [];
}

export default function ChatApp() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [title, setTitle] = useState("New chat");
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [chatDocs, setChatDocs] = useState<DocumentInfo[]>([]);
  const [libraryCount, setLibraryCount] = useState(0);
  const [uploads, setUploads] = useState<PendingUpload[]>([]);
  const [scope, setScope] = useState<"all" | "chat">("all");
  const [strict, setStrict] = useState(true);
  const [busy, setBusy] = useState(false);
  const [panel, setPanel] = useState<{ key: string; n: number } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const activeRef = useRef<string | null>(null);
  activeRef.current = activeId;

  const flash = (text: string) => {
    setNotice(text);
    setTimeout(() => setNotice(null), 4000);
  };

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations());
    } catch (err) {
      flash((err as Error).message);
    }
  }, []);

  const refreshLibrary = useCallback(async () => {
    try {
      const docs = await api.listDocuments("library");
      setLibraryCount(docs.filter((d) => d.status === "ready").length);
    } catch {
      /* shown elsewhere */
    }
  }, []);

  const setUrl = (id: string | null) => {
    const url = id ? `/?c=${id}` : "/";
    window.history.replaceState(null, "", url);
  };

  const openConversation = useCallback(async (id: string) => {
    abortRef.current?.abort();
    try {
      const detail = await api.getConversation(id);
      setActiveId(detail.id);
      setTitle(detail.title);
      setMessages(detail.messages.map((m) => ({ ...m, key: `m-${m.id}` })));
      setChatDocs(detail.documents);
      setUploads([]);
      setScope("all");
      setPanel(null);
      setUrl(detail.id);
      setSidebarOpen(false);
    } catch (err) {
      flash(err instanceof ApiError && err.status === 404 ? "That conversation no longer exists." : (err as Error).message);
      setUrl(null);
    }
  }, []);

  useEffect(() => {
    refreshConversations();
    refreshLibrary();
    const id = new URLSearchParams(window.location.search).get("c");
    if (id) openConversation(id);
  }, [refreshConversations, refreshLibrary, openConversation]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && messages.length > 0) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const newChat = () => {
    abortRef.current?.abort();
    setActiveId(null);
    setTitle("New chat");
    setMessages([]);
    setChatDocs([]);
    setUploads([]);
    setScope("all");
    setPanel(null);
    setUrl(null);
    setSidebarOpen(false);
  };

  const ensureConversation = async (): Promise<string> => {
    if (activeRef.current) return activeRef.current;
    const conv = await api.createConversation();
    setActiveId(conv.id);
    activeRef.current = conv.id;
    setUrl(conv.id);
    setConversations((prev) => [conv, ...prev]);
    return conv.id;
  };

  const send = async (question: string) => {
    if (busy) return;
    const userMsg: UIMessage = {
      key: localKey(), id: -1, role: "user", content: question, sources: null, feedback: null, created_at: new Date().toISOString(),
    };
    const placeholderKey = localKey();
    const placeholder: UIMessage = {
      key: placeholderKey, id: -1, role: "assistant", content: "", sources: [], feedback: null,
      created_at: new Date().toISOString(), pending: true, status: strict || libraryCount > 0 ? "Searching your documents" : "Thinking",
    };
    setMessages((prev) => [...prev, userMsg, placeholder]);
    setUploads((prev) => prev.filter((u) => u.state !== "ready"));
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const update = (patch: Partial<UIMessage> | ((m: UIMessage) => Partial<UIMessage>)) =>
      setMessages((prev) => prev.map((m) => (m.key === placeholderKey ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m)));

    try {
      await streamChat(
        { question, conversation_id: activeRef.current, scope, strict },
        (event) => {
          switch (event.type) {
            case "conversation":
              if (!activeRef.current) {
                setActiveId(event.conversation_id);
                activeRef.current = event.conversation_id;
                setUrl(event.conversation_id);
              }
              setTitle(event.title);
              break;
            case "status":
              update({ status: event.message });
              break;
            case "sources":
              update({ sources: event.sources });
              break;
            case "token":
              update((m) => ({ content: m.content + event.text, status: undefined }));
              break;
            case "done": {
              update({ ...event.message, key: placeholderKey, pending: false, status: undefined });
              const firstCited = (event.message.sources ?? []).find((s) => s.cited);
              if (firstCited && window.innerWidth >= 1280) setPanel({ key: placeholderKey, n: firstCited.n });
              break;
            }
            case "error":
              update({ content: event.message, pending: false, error: true, status: undefined });
              break;
          }
        },
        controller.signal,
      );
      update((m) => (m.pending ? { pending: false, status: undefined, content: m.content || "Stopped." } : {}));
    } catch (err) {
      update({ content: (err as Error).message, pending: false, error: true, status: undefined });
    } finally {
      setBusy(false);
      abortRef.current = null;
      refreshConversations();
    }
  };

  const stop = () => abortRef.current?.abort();

  const onFiles = async (files: File[]) => {
    const accepted = ACCEPTED_FILES.split(",");
    const valid = files.filter((f) => accepted.some((ext) => f.name.toLowerCase().endsWith(ext)));
    const rejected = files.filter((f) => !valid.includes(f));
    if (rejected.length) flash(`Not supported: ${rejected.map((f) => f.name).join(", ")}`);
    if (!valid.length) return;
    const entries: PendingUpload[] = valid.map((f) => ({ key: localKey(), name: f.name, progress: 0, state: "uploading" }));
    setUploads((prev) => [...prev, ...entries]);
    const keys = new Set(entries.map((e) => e.key));
    const patch = (fn: (u: PendingUpload, i: number) => Partial<PendingUpload>) =>
      setUploads((prev) => {
        let i = -1;
        return prev.map((u) => {
          if (!keys.has(u.key)) return u;
          i += 1;
          return { ...u, ...fn(u, i) };
        });
      });
    try {
      const conversationId = await ensureConversation();
      const results = await uploadFiles(valid, {
        conversationId,
        onProgress: (p) => patch(() => (p >= 1 ? { progress: 1, state: "reading" } : { progress: p })),
      });
      patch((_, i) => {
        const r = results[i];
        if (!r) return { state: "failed", error: "No response for this file" };
        if (r.error || !r.document) return { state: "failed", error: r.error ?? "Couldn't read this file" };
        if (r.document.status === "failed") return { state: "failed", error: r.document.error ?? "Couldn't read this file", fileType: r.document.file_type };
        return { state: "ready", fileType: r.document.file_type };
      });
      const detail = await api.getConversation(conversationId);
      setChatDocs(detail.documents);
    } catch (err) {
      patch(() => ({ state: "failed", error: (err as Error).message }));
    }
  };

  const removeConversation = async (id: string) => {
    try {
      await api.deleteConversation(id);
      if (id === activeId) newChat();
      setConversations((prev) => prev.filter((c) => c.id !== id));
    } catch (err) {
      flash((err as Error).message);
    }
  };

  const giveFeedback = async (m: UIMessage, value: 1 | -1) => {
    if (m.id < 0) return;
    const next = m.feedback === value ? 0 : value;
    try {
      const saved = await api.feedback(m.id, next);
      setMessages((prev) => prev.map((x) => (x.key === m.key ? { ...x, feedback: saved.feedback } : x)));
    } catch (err) {
      flash((err as Error).message);
    }
  };

  const copyAnswer = async (m: UIMessage) => {
    try {
      await navigator.clipboard.writeText(m.content.replace(/\[(\d+)\]/g, ""));
      setCopiedKey(m.key);
      setTimeout(() => setCopiedKey(null), 1500);
    } catch {
      /* clipboard blocked */
    }
  };

  const panelMessage = useMemo(() => messages.find((m) => m.key === panel?.key), [messages, panel]);
  const panelSources = panelMessage ? citedSources(panelMessage) : [];
  const lastWithSources = [...messages].reverse().find((m) => m.role === "assistant" && citedSources(m).length);

  return (
    <div className="flex h-dvh overflow-hidden bg-ground text-ink">
      {/* ---------------- Sidebar ---------------- */}
      <div
        className={`fixed inset-0 z-30 bg-black/20 lg:hidden ${sidebarOpen ? "block" : "hidden"}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[264px] flex-col gap-4 border-r border-line bg-[#fbfbfc] px-3.5 py-4 transition-transform lg:static lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-2.5 px-1.5">
          <LogoMark />
          <span className="text-lg font-semibold tracking-[-0.01em]">Clause</span>
        </div>
        <button
          type="button"
          onClick={newChat}
          className="group flex min-h-10 items-center gap-2.5 rounded-[10px] border border-line bg-panel px-3.5 text-sm font-medium text-ink-2 shadow-[0_1px_2px_rgba(21,23,28,0.04)] transition-all duration-150 hover:border-[#cfd3dc] hover:bg-[#f3f4f7] hover:text-ink hover:shadow-[0_1px_3px_rgba(21,23,28,0.08)] active:bg-[#eceef2]"
        >
          <MessageSquarePlus size={16} className="text-mute transition-colors group-hover:text-ink" aria-hidden="true" /> New chat
        </button>

        <nav aria-label="Recent chats" className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
          <span className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.07em] text-faint">Recent</span>
          {conversations.length === 0 && <p className="px-2.5 text-[13px] text-faint">Your chats will appear here.</p>}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`group flex items-center rounded-[9px] ${c.id === activeId ? "bg-[#eceef2]" : "hover:bg-[#f0f1f4]"}`}
            >
              <button
                type="button"
                onClick={() => openConversation(c.id)}
                className="min-w-0 flex-1 truncate px-2.5 py-2 text-left text-[13.5px] text-ink-2"
                title={`${c.title} · ${timeAgo(c.updated_at)}`}
              >
                {c.title}
              </button>
              <button
                type="button"
                onClick={() => removeConversation(c.id)}
                aria-label={`Delete chat ${c.title}`}
                className="mr-1 rounded-md p-1.5 text-faint opacity-0 hover:bg-white hover:text-bad focus:opacity-100 group-hover:opacity-100"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </nav>

        <div className="flex flex-col gap-1 border-t border-line pt-3">
          <div className="flex items-center gap-2.5 px-2.5 py-1.5 text-[13px] text-mute">
            <FileText size={15} /> {libraryCount} {libraryCount === 1 ? "document" : "documents"} in the library
          </div>
          <Link href="/admin" className="flex min-h-10 items-center gap-2.5 rounded-[9px] px-2.5 text-[14px] text-ink-2 hover:bg-[#eceef2]">
            <LayoutDashboard size={16} /> Claude console
          </Link>
        </div>
      </aside>

      {/* ---------------- Main ---------------- */}
      <main className="flex min-w-0 flex-1 flex-col bg-panel">
        <header className="flex items-center justify-between gap-3 border-b border-line-soft px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            <button type="button" onClick={() => setSidebarOpen(true)} aria-label="Open menu" className="rounded-lg p-1.5 hover:bg-[#eceef2] lg:hidden">
              <Menu size={18} />
            </button>
            <h1 className="truncate text-[15px] font-semibold">{title}</h1>
            {chatDocs.length > 0 && (
              <span className="hidden shrink-0 rounded-full bg-[#f3f4f7] px-2.5 py-0.5 text-xs text-ink-2 sm:inline">
                {chatDocs.length} {chatDocs.length === 1 ? "file" : "files"} in this chat
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => {
              if (panel) setPanel(null);
              else if (lastWithSources) setPanel({ key: lastWithSources.key, n: citedSources(lastWithSources)[0].n });
            }}
            disabled={!panel && !lastWithSources}
            aria-label="Show or hide sources"
            aria-pressed={!!panel}
            className="flex h-9 w-9 items-center justify-center rounded-[9px] border border-line text-ink-2 hover:bg-[#f0f1f4] disabled:opacity-40"
          >
            <PanelRight size={16} />
          </button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 pb-4 pt-6 sm:px-6">
          {messages.length === 0 ? (
            <EmptyState
              libraryCount={libraryCount}
              onAsk={send}
              onPickFiles={() => fileInput.current?.click()}
            />
          ) : (
            <div className="mx-auto flex w-full max-w-[760px] flex-col gap-7">
              {messages.map((m) =>
                m.role === "user" ? (
                  <div key={m.key} className="flex justify-end">
                    <div className="max-w-[85%] whitespace-pre-wrap rounded-[16px_16px_4px_16px] bg-[#f1f3f7] px-4 py-3 text-[14.5px]">
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <div key={m.key} className="flex items-start gap-3.5">
                    <LogoMark size={28} />
                    <div className="flex min-w-0 flex-1 flex-col gap-3 pt-0.5">
                      {m.pending && !m.content ? (
                        <div className="flex items-center gap-2.5 text-[14px] text-mute" role="status">
                          <span className="flex gap-1" aria-hidden="true">
                            <span className="typing-dot h-1.5 w-1.5 rounded-full bg-mute" />
                            <span className="typing-dot h-1.5 w-1.5 rounded-full bg-mute" />
                            <span className="typing-dot h-1.5 w-1.5 rounded-full bg-mute" />
                          </span>
                          {m.status ?? "Thinking"}…
                        </div>
                      ) : m.error ? (
                        <div className="rounded-xl border border-[#f3c9c5] bg-bad-soft/50 px-4 py-3 text-[14px] text-[#7a1810]">{m.content}</div>
                      ) : (
                        <Answer
                          content={m.content}
                          selected={panel?.key === m.key ? panel.n : null}
                          onCite={(n) => setPanel({ key: m.key, n })}
                          validNumbers={new Set((m.sources ?? []).map((s) => s.n))}
                        />
                      )}

                      {!m.pending && !m.error && (
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap gap-1.5">
                            {citedSources(m).map((s) => (
                              <button
                                key={s.n}
                                type="button"
                                onClick={() => setPanel({ key: m.key, n: s.n })}
                                className="inline-flex max-w-[260px] items-center gap-1.5 rounded-full border border-line bg-panel py-1 pl-1 pr-2.5 text-xs text-ink-2 hover:border-[#c9ceda]"
                              >
                                <span className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-accent-soft px-1 text-[10.5px] font-semibold text-accent-strong">
                                  {s.n}
                                </span>
                                <span className="truncate">{s.filename}</span>
                                {s.page ? <span className="shrink-0 text-faint">p. {s.page}</span> : null}
                              </button>
                            ))}
                          </div>
                          {m.id > 0 && (
                            <div className="flex gap-0.5">
                              <button type="button" onClick={() => copyAnswer(m)} aria-label="Copy answer" className="rounded-lg p-2 text-mute hover:bg-[#f0f1f4]">
                                {copiedKey === m.key ? <Check size={15} className="text-ok" /> : <Copy size={15} />}
                              </button>
                              <button
                                type="button"
                                onClick={() => giveFeedback(m, 1)}
                                aria-label="Helpful"
                                aria-pressed={m.feedback === 1}
                                className={`rounded-lg p-2 hover:bg-[#f0f1f4] ${m.feedback === 1 ? "text-ok" : "text-mute"}`}
                              >
                                <ThumbsUp size={15} />
                              </button>
                              <button
                                type="button"
                                onClick={() => giveFeedback(m, -1)}
                                aria-label="Not helpful"
                                aria-pressed={m.feedback === -1}
                                className={`rounded-lg p-2 hover:bg-[#f0f1f4] ${m.feedback === -1 ? "text-bad" : "text-mute"}`}
                              >
                                <ThumbsDown size={15} />
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ),
              )}
            </div>
          )}
        </div>

        <div className="px-4 pb-4 pt-2 sm:px-6">
          {notice && (
            <div role="status" className="mx-auto mb-2 w-full max-w-[760px] rounded-xl border border-line bg-[#fbfbfc] px-4 py-2.5 text-[13px] text-ink-2">
              {notice}
            </div>
          )}
          {chatDocs.length > 0 && messages.length > 0 && (
            <div className="mx-auto mb-2 flex w-full max-w-[760px] flex-wrap gap-1.5">
              {chatDocs.map((d) => (
                <span key={d.id} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-subtle py-0.5 pl-1 pr-2.5 text-xs text-ink-2">
                  <FileBadge type={d.file_type} className="scale-90" />
                  <span className="max-w-[200px] truncate">{d.filename}</span>
                  {d.status === "failed" && <span className="text-bad">· couldn&apos;t read</span>}
                </span>
              ))}
            </div>
          )}
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
          <Composer
            busy={busy}
            onSend={send}
            onStop={stop}
            onFiles={onFiles}
            uploads={uploads}
            onDismissUpload={(key) => setUploads((prev) => prev.filter((u) => u.key !== key))}
            chatDocs={chatDocs}
            scope={scope}
            setScope={setScope}
            strict={strict}
            setStrict={setStrict}
          />
        </div>
      </main>

      {/* ---------------- Sources panel ---------------- */}
      {panel && panelSources.length > 0 && (
        <>
          <div className="fixed inset-0 z-30 bg-black/20 xl:hidden" onClick={() => setPanel(null)} aria-hidden="true" />
          <div className="fixed inset-y-0 right-0 z-40 w-[min(400px,100vw)] xl:static xl:z-auto xl:w-[380px]">
            <SourcesPanel
              sources={panelSources}
              selected={panel.n}
              onSelect={(n) => setPanel({ key: panel.key, n })}
              onClose={() => setPanel(null)}
            />
          </div>
        </>
      )}
    </div>
  );
}

import type {
  ChunkInfo,
  Conversation,
  ConversationDetail,
  DocumentInfo,
  EvalRun,
  EvalRunDetail,
  GoldenQuestion,
  Message,
  RetrievalTestResult,
  SampleDoc,
  Stats,
  StreamEvent,
  UploadResult,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: init?.body instanceof FormData ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Clause can't reach its server. Check that the backend is running.", 0);
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join(", ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  // documents
  listDocuments: (scope: "library" | "all" = "library") => request<DocumentInfo[]>(`/api/documents?scope=${scope}`),
  getChunks: (id: string) => request<ChunkInfo[]>(`/api/documents/${id}/chunks`),
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  reindexDocument: (id: string) => request<DocumentInfo>(`/api/documents/${id}/reindex`, { method: "POST" }),
  fileUrl: (id: string, opts?: { download?: boolean; page?: number | null }) =>
    `${API_URL}/api/documents/${id}/file${opts?.download ? "?download=true" : ""}${opts?.page ? `#page=${opts.page}` : ""}`,

  // samples
  listSamples: () => request<SampleDoc[]>("/api/samples"),
  importSamples: () => request<UploadResult[]>("/api/samples/import", { method: "POST" }),
  sampleUrl: (filename: string) => `${API_URL}/api/samples/${encodeURIComponent(filename)}`,
  samplesZipUrl: () => `${API_URL}/api/samples/archive`,

  // conversations
  listConversations: () => request<Conversation[]>("/api/conversations"),
  getConversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),
  createConversation: () => request<Conversation>("/api/conversations", { method: "POST", body: JSON.stringify({}) }),
  deleteConversation: (id: string) => request<void>(`/api/conversations/${id}`, { method: "DELETE" }),
  feedback: (messageId: number, value: -1 | 0 | 1) =>
    request<Message>(`/api/messages/${messageId}/feedback`, { method: "POST", body: JSON.stringify({ value }) }),

  // admin
  health: (deep = false) => request<Record<string, unknown>>(`/api/health${deep ? "?deep=true" : ""}`),
  config: () => request<Record<string, unknown>>("/api/config"),
  stats: () => request<Stats>("/api/stats"),
  retrievalTest: (body: { query: string; mode?: string; reranker?: string; top_n?: number }) =>
    request<RetrievalTestResult>("/api/retrieval/test", { method: "POST", body: JSON.stringify(body) }),
  golden: () =>
    request<{ documents: string[]; questions: GoldenQuestion[]; variants: Record<string, string> }>("/api/eval/golden"),
  listRuns: () => request<EvalRun[]>("/api/eval/runs"),
  getRun: (id: string) => request<EvalRunDetail>(`/api/eval/runs/${id}`),
  startRun: (body: { variants: string[]; generate: boolean; judge: boolean; limit?: number | null }) =>
    request<EvalRun>("/api/eval/runs", { method: "POST", body: JSON.stringify(body) }),
  deleteRun: (id: string) => request<void>(`/api/eval/runs/${id}`, { method: "DELETE" }),
  reportUrl: (id: string) => `${API_URL}/api/eval/runs/${id}/report`,
};

/** Upload many files with progress (fetch has no upload progress, so XHR). */
export function uploadFiles(
  files: File[],
  opts: { conversationId?: string | null; onProgress?: (fraction: number) => void } = {},
): Promise<UploadResult[]> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    if (opts.conversationId) form.append("conversation_id", opts.conversationId);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/api/documents`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) opts.onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as UploadResult[]);
      } else {
        let detail = `Upload failed (${xhr.status})`;
        try {
          detail = JSON.parse(xhr.responseText).detail ?? detail;
        } catch {
          /* ignore */
        }
        reject(new ApiError(detail, xhr.status));
      }
    };
    xhr.onerror = () => reject(new ApiError("Clause can't reach its server. Check that the backend is running.", 0));
    xhr.send(form);
  });
}

/** Ask a question and receive the answer as it is written. */
export async function streamChat(
  body: { question: string; conversation_id?: string | null; scope?: "all" | "chat"; strict?: boolean },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    throw new ApiError("Clause can't reach its server. Check that the backend is running.", 0);
  }
  if (!res.ok || !res.body) {
    let detail = `Request failed (${res.status})`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line) as StreamEvent);
      newline = buffer.indexOf("\n");
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as StreamEvent);
}

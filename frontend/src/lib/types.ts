// Mirrors backend/app/schemas.py

export type DocumentStatus = "processing" | "ready" | "failed";

export interface DocumentInfo {
  id: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  status: DocumentStatus;
  error: string | null;
  pages: number | null;
  chunk_count: number;
  conversation_id: string | null;
  created_at: string;
}

export interface UploadResult {
  filename: string;
  document: DocumentInfo | null;
  duplicate: boolean;
  error: string | null;
}

export interface ChunkInfo {
  id: number;
  chunk_index: number;
  text: string;
  page: number | null;
  section: string | null;
  char_count: number;
}

export interface Source {
  n: number;
  document_id: string;
  filename: string;
  file_type: string;
  page: number | null;
  section: string | null;
  text: string;
  highlight: string;
  cited: boolean;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[] | null;
  feedback: number | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
  documents: DocumentInfo[];
}

export type StreamEvent =
  | { type: "conversation"; conversation_id: string; title: string }
  | { type: "status"; message: string }
  | { type: "sources"; sources: Source[] }
  | { type: "token"; text: string }
  | { type: "done"; message: Message; refused: boolean }
  | { type: "error"; message: string };

export interface SampleDoc {
  filename: string;
  description: string;
  size_bytes: number;
  file_type: string;
}

export interface Stats {
  documents: { total: number; ready: number; processing: number; failed: number };
  chunks: number;
  index: { chunks: number; vectors: number; keyword_docs: number };
  conversations: number;
  questions: number;
  answers: number;
  not_found_rate: number | null;
  feedback: { up: number; down: number };
  content_gaps: { question: string; asked_at: string }[];
  recent_documents: { id: string; filename: string; status: DocumentStatus; chunk_count: number; created_at: string; in_chat: boolean }[];
  last_eval: { id: string; created_at: string; summary: Record<string, VariantSummary> } | null;
}

export interface VariantSummary {
  questions: number;
  answerable: number;
  "hit@1"?: number | null;
  "hit@3"?: number | null;
  "hit@5"?: number | null;
  "recall@5"?: number | null;
  "precision@5"?: number | null;
  mrr?: number | null;
  refusal_correct?: number | null;
  refusal_accuracy_unanswerable?: number | null;
  key_facts?: number | null;
  answer_f1?: number | null;
  cited?: number | null;
  citation_precision?: number | null;
  faithfulness?: number | null;
  relevance?: number | null;
  correctness?: number | null;
  latency_ms?: number | null;
  quality_score?: number | null;
  by_category?: Record<string, Record<string, number | null>>;
}

export interface EvalRun {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  variants: string[];
  progress: number;
  total: number;
  summary: Record<string, VariantSummary> | null;
  config: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface EvalResultRow {
  variant: string;
  question_id: string;
  category: string;
  question: string;
  answer: string;
  metrics: Record<string, number | boolean | string | null>;
  retrieved: {
    n: number;
    filename: string;
    page: number | null;
    section: string | null;
    cited: boolean;
    score: number;
    text: string;
    relevant: boolean;
  }[];
}

export interface EvalRunDetail extends EvalRun {
  results: EvalResultRow[];
}

export interface GoldenQuestion {
  id: string;
  category: string;
  question: string;
  reference: string;
  answerable: boolean;
  expected_sources: { file: string; contains: string }[];
  must_include: string[][];
  history: [string, string][];
}

export interface RetrievalCandidate {
  chunk_id: number;
  fused_score: number;
  vector_score: number | null;
  vector_rank: number | null;
  keyword_score: number | null;
  keyword_rank: number | null;
  rerank_score: number | null;
  filename?: string;
  page?: number | null;
  section?: string | null;
  text?: string;
}

export interface RetrievalTestResult {
  plan: { route: string; standalone: string; sub_queries: string[]; search_queries: string[] };
  reranker: string;
  timings_ms: Record<string, number>;
  candidates: RetrievalCandidate[];
  context: (RetrievalCandidate & { n: number; score: number })[];
}

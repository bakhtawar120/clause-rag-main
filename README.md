# Clause

Grounded answers from your documents. Users ask questions in plain language; Clause searches the
documents, answers only from what it finds, and cites the exact passage behind every fact.

- **Frontend**: Next.js 15 (App Router) + React 19 + Tailwind CSS 4, in `frontend/`
- **Backend**: FastAPI + LangChain + SQLite + FAISS, managed with `uv`, in `backend/`
- **Ready for later**: Postgres (change one URL) and pgvector (one small class), agentic RAG and connectors

---

## 1. Quick start

You need: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+, and [Ollama](https://ollama.com) for free local models.

```bash
# Local models (one time)
ollama pull gemma3:4b
ollama pull nomic-embed-text

# Backend  ->  http://localhost:8000  (API docs at /docs)
cd backend
cp .env.example .env
uv sync
uv run fastapi dev

# Frontend ->  http://localhost:3000   (second terminal)
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open http://localhost:3000, click **Add sample documents**, and ask one of the suggested questions.
The Claude console is at http://localhost:3000/admin.

**Intel Mac (macOS 13/14)?** Supported. The lock file pins `faiss-cpu` 1.13.2 and `onnxruntime` 1.23.2 for Intel Macs,
because newer versions only ship wheels for Apple Silicon or macOS 15. If an older `uv sync` failed, run
`rm -rf .venv && uv sync` with this version.

**No Ollama yet?** Set `CHAT_PROVIDER=fake` and `EMBEDDING_PROVIDER=fake` in `backend/.env`. Everything runs offline;
answers are extractive (copied sentences), so use it to try the product, not to judge answer quality.

**Another model provider?** Install its LangChain package and set it in `.env`, for example:

```bash
uv add langchain-anthropic   # then CHAT_PROVIDER=anthropic, CHAT_MODEL=<model id>, CHAT_API_KEY=...
uv add langchain-openai      # then CHAT_PROVIDER=openai,    CHAT_MODEL=<model id>, CHAT_API_KEY=...
```

---

## 2. Settings and the `.env` file

| File | Purpose |
|---|---|
| `backend/.env.example` | Every backend setting, documented, with safe defaults. Copy to `backend/.env`. |
| `frontend/.env.local.example` | Only `NEXT_PUBLIC_API_URL`. Copy to `frontend/.env.local`. |

How settings work (`backend/app/core/config.py`, pydantic-settings):

- The app starts with **no `.env` at all**; every value has a default.
- Real environment variables **override** `.env` (useful for Docker and CI).
- Keys are `SecretStr`: never logged, never in error messages, never returned by `/api/config`.
- Values are **validated at startup** (for example, `CHUNK_OVERLAP` must be smaller than `CHUNK_SIZE`).
- `.env` and `.env.local` are in `.gitignore`. Commit only the `.example` files.
- The frontend only receives `NEXT_PUBLIC_*` values, so it never holds a secret.
- Changing `EMBEDDING_MODEL` is safe: at the next start Clause sees that the stored vectors came from a different
  model and re-embeds every chunk automatically.

---

## 3. The RAG pipeline

The four stages from the reference diagram, and where each lives in the code:

```
INDEXING (when documents change)
  Documents ──► Pre-processing ──► Chunking ──► Embedding model ──► Vector DB (FAISS) + keyword index (BM25)
  loaders.py     preprocess.py      chunking.py   models.py           vectorstore.py      keyword.py

QUERY (every question)
  Query ──► PRE-RETRIEVAL ──► RETRIEVAL ──────────────► POST-RETRIEVAL ─────────────► LLM ──► Response + citations
            query.py           retrieval.py               rerank.py, context.py          engine.py, prompts.py
```

| Stage | Technique | Setting |
|---|---|---|
| **Indexing** | Loaders for PDF, Word, Markdown, text, CSV, HTML (headings kept as structure) | |
| | Pre-processing: Unicode clean-up, re-join hyphenated and wrapped lines, remove running headers/footers and page numbers | |
| | Structure-aware chunking: follows headings across pages, recursive splitting with overlap, no heading-only chunks | `CHUNK_SIZE`, `CHUNK_OVERLAP` |
| | Contextual chunk headers: "file > section" embedded and keyword-indexed with each chunk | `CONTEXTUAL_HEADERS` |
| | Duplicate uploads detected by SHA-256 | |
| **Pre-retrieval** | Query routing: greetings skip the search | |
| | Query transformation: follow-ups rewritten into standalone questions (used for search only) | `QUERY_REWRITE` |
| | Query decomposition: complex questions split into sub-queries | `QUERY_EXPANSION` |
| **Retrieval** | Hybrid search: vectors (meaning) + BM25 (exact words, codes like SKU-4471) | `RETRIEVAL_MODE` |
| | Reciprocal Rank Fusion with weights | `RRF_K`, `VECTOR_WEIGHT`, `KEYWORD_WEIGHT` |
| | Metadata filtering: each chat only searches the documents it may use | |
| | Excluding vector search outliers (absolute floor + gap from the best hit) | `MIN_VECTOR_SCORE`, `VECTOR_SCORE_GAP` |
| **Post-retrieval** | Re-ranking: FlashRank cross-encoder, LLM scoring, or lexical (automatic fallback) | `RERANKER` |
| | Context post-processing: near-duplicate removal, character budget, numbered sources | `RERANK_TOP_N`, `MAX_CONTEXT_CHARS` |
| | Prompt engineering: answer only from sources, cite every fact, fixed refusal sentence | `STRICT_SOURCES` |
| | Citation post-processing: invalid numbers removed, best supporting sentence highlighted | |

FlashRank downloads its small model (about 30 MB) into `backend/data/models` on first use. If it cannot
(no internet), Clause logs a warning and uses the lexical re-ranker instead.

---

## 4. Evaluation

The golden set (`backend/eval/golden_set.json`) has **30 questions** over the 7 test documents:
single-document, exact-keyword, multi-document, follow-up (with chat history) and **unanswerable** questions.
Each answerable question lists the passages that must be retrieved and the key facts the answer must contain.

| Group | Metrics |
|---|---|
| Retrieval | hit@1, hit@3, hit@5, recall@5, precision@5, MRR (on the passages actually sent to the model) |
| Answer | key-fact coverage, token F1 vs reference, correct refusals (unanswerable must be refused), cited, citation precision |
| LLM judge | faithfulness (claims supported by cited passages), relevance, correctness vs reference |

Variants compared in one run: `vector`, `keyword`, `hybrid`, `hybrid_rerank`. Each run builds its own in-memory
index over the test documents, so results are reproducible and never touch user data.

```bash
cd backend
uv run python -m app.eval.cli                    # all variants, answers + judge
uv run python -m app.eval.cli --no-generate      # retrieval only: fast, no LLM
uv run python -m app.eval.cli --no-judge         # skip judge calls
uv run python -m app.eval.cli --variants hybrid_rerank --min-hit5 0.9 --min-refusal 0.9   # CI quality gate (exit code 1 on failure)
```

Reports are saved as JSON in `backend/data/eval_reports/`. The same runs can be started, compared and inspected
question by question in **Admin → Evaluation**. Use a stronger judge model with `JUDGE_PROVIDER` / `JUDGE_MODEL`.

---

## 5. Tests

```bash
cd backend
uv run pytest
```

70 tests run offline (fake models, no network, no keys) in a few seconds:

- `test_config.py`: defaults, validation, comma-separated CORS, secrets never exposed
- `test_indexing.py`: every loader, password-protected and empty files, pre-processing, chunk sections, page numbers, overlap
- `test_retrieval.py`: FAISS add/search/delete/filter/persist, embedding-change detection, BM25 codes, RRF maths, outliers,
  routing, query rewrite, all three re-rankers (including FlashRank fallback), de-duplication, citation clean-up, highlights
- `test_engine.py`: grounded cited answers, refusals, metadata filter, streaming events, follow-ups, topic changes, index rebuild
- `test_evaluation.py`: every metric, golden set consistency with the documents, and a **quality gate** on the full golden set
- `test_api.py`: uploads of many files, duplicates, bad files, chat, streaming, chat-only scope, follow-ups, feedback, stats,
  delete/re-index, restart persistence, sample downloads and import, retrieval lab, evaluation runs through the API

Frontend checks: `cd frontend && npm run lint && npm run build`.

---

## 6. Test documents

`backend/sample_docs/` (fictional company "Acme Inc."):

| File | Format | Covers |
|---|---|---|
| HR_Policy_v7.pdf | PDF, 3 pages | leave, sick leave, parental leave, notice, payment in lieu, remote work |
| Supplier_Agreement_2026.pdf | PDF, 2 pages | term, payment, late interest, liability, termination, governing law |
| Employment_Contract_Template.docx | Word | probation, hours, salary, notice, confidentiality |
| Returns_and_Warranty_FAQ.md | Markdown | returns window, refunds, sale items, warranty, X200 |
| Price_List_Q3_2026.csv | CSV | SKUs, prices, warranty months |
| Travel_and_Expenses_Policy.html | HTML | daily allowance, flights, mileage, claims |
| Delivery_Policy.txt | Plain text | delivery times, charges, days |

Download them from **Admin → Documents → Test documents**, or regenerate with
`uv run python scripts/make_sample_docs.py` (if you change a fact, update the golden set too).

---

## 7. API overview

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/documents` | Upload one or many files (`files`, optional `conversation_id`) |
| GET | `/api/documents` | List documents (`scope=library` or `all`) |
| GET | `/api/documents/{id}/chunks` | Inspect chunks |
| GET | `/api/documents/{id}/file` | Original file (`?download=true`) |
| POST / DELETE | `/api/documents/{id}/reindex`, `/api/documents/{id}` | Re-index / delete |
| POST | `/api/chat` and `/api/chat/stream` | Ask (JSON, or streamed newline-delimited JSON) |
| GET / POST / DELETE | `/api/conversations[/{id}]` | Conversations |
| POST | `/api/messages/{id}/feedback` | Thumbs up/down |
| POST | `/api/retrieval/test` | Retrieval lab (every stage, no answer) |
| POST / GET | `/api/eval/runs[/{id}]`, `/api/eval/runs/{id}/report` | Evaluation runs and JSON report |
| GET | `/api/samples`, `/api/samples/{file}`, `/api/samples/archive` | Test documents |
| POST | `/api/samples/import` | Add all test documents to the library |
| GET | `/api/health?deep=true`, `/api/config`, `/api/stats` | Health, public settings, admin stats |

---

## 8. Moving to Postgres and pgvector

**Postgres** (database): `uv add "psycopg[binary]"` and set
`DATABASE_URL=postgresql+psycopg://user:password@host:5432/clause`. The models use only portable column types.

**pgvector** (vectors): the engine talks to the small `VectorStore` interface in `app/rag/vectorstore.py`
(`add`, `delete`, `search`, `count`, `reset`, `save`). Write a `PgVectorStore` with the same six methods (a table
with `chunk_id`, `embedding vector(N)`; cosine distance; `WHERE chunk_id = ANY(:allowed)` for the metadata filter)
and construct it in `RAGEngine.__init__`. Nothing else changes.

---

## 9. Project layout

```
backend/
  app/core/config.py        settings (.env)
  app/db/                   SQLAlchemy models: documents, chunks, conversations, messages, eval runs
  app/rag/                  loaders, preprocess, chunking, models, vectorstore, keyword, query,
                            retrieval, rerank, context, prompts, engine
  app/services/             document lifecycle, evaluation runs
  app/eval/                 golden set, metrics, LLM judge, runner, CLI
  app/api/                  documents, chat, admin routes
  sample_docs/  eval/golden_set.json  scripts/make_sample_docs.py  tests/
frontend/
  src/app/page.tsx          the Clause chat
  src/app/admin/*           overview, documents, retrieval lab, evaluation, settings
  src/components/chat/*     chat app, answer with citation chips, sources panel, composer, start screen
  src/lib/api.ts            API client (uploads with progress, streaming)
```

The chat shows only what users need (answers, sources, files). Scores, ranks, chunk ids and settings stay in the Claude console.

## 10. Next steps (not in this version)

- **Agentic RAG**: expose `engine.retrieve` as a LangChain tool so the model decides when and how often to search.
- **Connectors**: Google Drive, SharePoint and MCP servers feeding the same indexing pipeline, keeping source permissions.
- **OCR** for scanned PDFs, and per-user access groups on the library.

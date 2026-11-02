"use client";

import { Search } from "lucide-react";
import { useState } from "react";

import { ErrorNote, PageHeader } from "@/components/admin/AdminShell";
import { Button, Card, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { locationLabel, num } from "@/lib/format";
import type { RetrievalTestResult } from "@/lib/types";

const EXAMPLES = ["price of SKU-4471", "notice period for permanent staff", "can I return opened earbuds", "late payment interest"];

export default function RetrievalLabPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [reranker, setReranker] = useState("");
  const [topN, setTopN] = useState(5);
  const [result, setResult] = useState<RetrievalTestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (q = query) => {
    if (!q.trim()) return;
    setQuery(q);
    setLoading(true);
    setError(null);
    try {
      setResult(await api.retrievalTest({ query: q, mode, reranker: reranker || undefined, top_n: topN }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader
        title="Retrieval lab"
        description="See every stage for one question: the planned search queries, meaning and keyword ranks, the fused score, the re-ranker score and the final passages sent to the model. No answer is generated."
      />
      {error && <ErrorNote message={error} />}
      <Card className="mb-4 p-5">
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
        >
          <div className="flex flex-col gap-2 sm:flex-row">
            <label htmlFor="q" className="sr-only">
              Test question
            </label>
            <input
              id="q"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type a question to test retrieval"
              className="min-h-10 flex-1 rounded-[10px] border border-[#dadde4] px-3 text-[14px] outline-none focus:border-[#b4b9c4]"
            />
            <Button type="submit" variant="accent" disabled={loading || !query.trim()}>
              {loading ? <Spinner /> : <Search size={15} />} Search
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-[13px]">
            <label className="flex items-center gap-2">
              Mode
              <select value={mode} onChange={(e) => setMode(e.target.value)} className="rounded-lg border border-line bg-panel px-2 py-1.5">
                <option value="hybrid">Hybrid (vector + keyword, RRF)</option>
                <option value="vector">Vector only</option>
                <option value="keyword">Keyword only (BM25)</option>
              </select>
            </label>
            <label className="flex items-center gap-2">
              Re-ranker
              <select value={reranker} onChange={(e) => setReranker(e.target.value)} className="rounded-lg border border-line bg-panel px-2 py-1.5">
                <option value="">Default from settings</option>
                <option value="flashrank">FlashRank cross-encoder</option>
                <option value="llm">LLM scoring</option>
                <option value="lexical">Lexical</option>
                <option value="none">None</option>
              </select>
            </label>
            <label className="flex items-center gap-2">
              Passages to keep
              <input type="number" min={1} max={20} value={topN} onChange={(e) => setTopN(Number(e.target.value) || 5)} className="w-16 rounded-lg border border-line px-2 py-1.5" />
            </label>
            <span className="text-faint">Try:</span>
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" onClick={() => run(ex)} className="rounded-full border border-line px-2.5 py-1 text-xs hover:bg-[#f0f1f4]">
                {ex}
              </button>
            ))}
          </div>
        </form>
      </Card>

      {result && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="p-5 lg:col-span-2">
              <h2 className="mb-2 text-[15px] font-semibold">Pre-retrieval plan</h2>
              <dl className="grid grid-cols-[140px_1fr] gap-y-1.5 text-[13.5px]">
                <dt className="text-mute">Route</dt>
                <dd>{result.plan.route}</dd>
                <dt className="text-mute">Standalone query</dt>
                <dd>{result.plan.standalone || "–"}</dd>
                <dt className="text-mute">Search queries</dt>
                <dd>{result.plan.search_queries.join("  ·  ") || "–"}</dd>
                <dt className="text-mute">Re-ranker used</dt>
                <dd>{result.reranker}</dd>
              </dl>
            </Card>
            <Card className="p-5">
              <h2 className="mb-2 text-[15px] font-semibold">Timings</h2>
              <dl className="grid grid-cols-2 gap-y-1.5 text-[13.5px]">
                {Object.entries(result.timings_ms).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-mute">{k.replace("_", "-")}</dt>
                    <dd className="text-right tabular-nums">{v} ms</dd>
                  </div>
                ))}
              </dl>
            </Card>
          </div>

          <Card className="p-5">
            <h2 className="mb-3 text-[15px] font-semibold">Final context sent to the model ({result.context.length})</h2>
            <ol className="flex flex-col gap-2.5">
              {result.context.map((c) => (
                <li key={c.chunk_id} className="rounded-xl border border-line-soft bg-subtle p-3">
                  <div className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-mute">
                    <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-accent px-1.5 font-semibold text-white">{c.n}</span>
                    <span className="font-medium text-ink">{c.filename}</span>
                    <span>{locationLabel(c.page, c.section)}</span>
                    <span className="font-mono">rerank {num(c.rerank_score, 3)} · fused {num(c.fused_score, 4)}</span>
                  </div>
                  <p className="whitespace-pre-line text-[13px] text-ink-2">{c.text}</p>
                </li>
              ))}
            </ol>
          </Card>

          <Card className="overflow-hidden">
            <h2 className="px-5 pt-4 text-[15px] font-semibold">All candidates after fusion and re-ranking</h2>
            <p className="px-5 pb-3 text-[12.5px] text-mute">Rank 1 = best. A dash means that search method did not return the passage.</p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-[13px]">
                <thead>
                  <tr className="border-y border-line bg-subtle text-left text-xs font-semibold text-mute">
                    <th className="px-5 py-2">#</th>
                    <th className="px-3 py-2">Passage</th>
                    <th className="px-3 py-2 text-right">Vector rank (score)</th>
                    <th className="px-3 py-2 text-right">Keyword rank (score)</th>
                    <th className="px-3 py-2 text-right">Fused (RRF)</th>
                    <th className="px-5 py-2 text-right">Re-rank</th>
                  </tr>
                </thead>
                <tbody>
                  {result.candidates.map((c, i) => (
                    <tr key={c.chunk_id} className="border-b border-line-soft align-top">
                      <td className="px-5 py-2 tabular-nums text-mute">{i + 1}</td>
                      <td className="px-3 py-2">
                        <div className="font-medium">{c.filename}</div>
                        <div className="text-xs text-mute">{locationLabel(c.page, c.section)}</div>
                        <div className="line-clamp-2 max-w-[440px] text-xs text-ink-2">{c.text}</div>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs">
                        {c.vector_rank ? `${c.vector_rank} (${num(c.vector_score, 3)})` : "–"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs">
                        {c.keyword_rank ? `${c.keyword_rank} (${num(c.keyword_score, 2)})` : "–"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs">{num(c.fused_score, 4)}</td>
                      <td className="px-5 py-2 text-right font-mono text-xs">{num(c.rerank_score, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

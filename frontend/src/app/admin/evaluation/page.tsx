"use client";

import { ChevronDown, ChevronRight, Download, FileArchive, Play, Trash2 } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { ErrorNote, PageHeader } from "@/components/admin/AdminShell";
import { Button, Card, Spinner, StatusPill } from "@/components/ui";
import { api } from "@/lib/api";
import { locationLabel, pct, timeAgo } from "@/lib/format";
import type { EvalResultRow, EvalRun, EvalRunDetail, GoldenQuestion, VariantSummary } from "@/lib/types";

const VARIANTS: Record<string, string> = {
  vector: "Vector",
  keyword: "Keyword (BM25)",
  hybrid: "Hybrid (RRF)",
  hybrid_rerank: "Hybrid + re-rank",
};

const METRICS: { key: keyof VariantSummary; label: string; help: string; group: string }[] = [
  { key: "quality_score", label: "Quality score", help: "Average of recall@5, key facts, correct refusals and faithfulness", group: "Overall" },
  { key: "hit@1", label: "Hit@1", help: "The right passage is ranked first", group: "Retrieval" },
  { key: "hit@5", label: "Hit@5", help: "The right passage is somewhere in the top 5", group: "Retrieval" },
  { key: "recall@5", label: "Recall@5", help: "Share of all needed passages found in the top 5", group: "Retrieval" },
  { key: "precision@5", label: "Precision@5", help: "Share of the top 5 that are needed passages", group: "Retrieval" },
  { key: "mrr", label: "MRR", help: "Mean of 1 / rank of the first right passage", group: "Retrieval" },
  { key: "key_facts", label: "Key facts", help: "Share of required facts that appear in the answer", group: "Answer" },
  { key: "answer_f1", label: "Answer F1", help: "Word overlap with the reference answer", group: "Answer" },
  { key: "refusal_correct", label: "Correct refusals", help: "Answers when it should, refuses when the documents don't say", group: "Answer" },
  { key: "refusal_accuracy_unanswerable", label: "Refuses the unanswerable", help: "Unanswerable questions correctly refused (should be 100%)", group: "Answer" },
  { key: "cited", label: "Cited", help: "Answers that include at least one citation", group: "Answer" },
  { key: "citation_precision", label: "Citation precision", help: "Cited passages that are actually the expected ones", group: "Answer" },
  { key: "faithfulness", label: "Faithfulness", help: "LLM judge: claims supported by the cited passages", group: "Judge" },
  { key: "relevance", label: "Relevance", help: "LLM judge: the answer addresses the question", group: "Judge" },
  { key: "correctness", label: "Correctness", help: "LLM judge: agrees with the reference answer", group: "Judge" },
  { key: "latency_ms", label: "Latency", help: "Average time per question", group: "Speed" },
];

function fmt(key: string, v: unknown) {
  if (typeof v !== "number") return "–";
  return key === "latency_ms" ? `${Math.round(v)} ms` : pct(v, 1);
}

function Check({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="text-faint">–</span>;
  return <span className={ok ? "text-ok" : "text-bad"}>{ok ? "✓" : "✗"}</span>;
}

export default function EvaluationPage() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [selected, setSelected] = useState<EvalRunDetail | null>(null);
  const [golden, setGolden] = useState<GoldenQuestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [variants, setVariants] = useState<string[]>(Object.keys(VARIANTS));
  const [generate, setGenerate] = useState(true);
  const [judge, setJudge] = useState(true);
  const [limit, setLimit] = useState<string>("");
  const [starting, setStarting] = useState(false);
  const [variantTab, setVariantTab] = useState<string>("hybrid_rerank");
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [showGolden, setShowGolden] = useState(false);

  const loadRuns = useCallback(async () => {
    try {
      const list = await api.listRuns();
      setRuns(list);
      return list;
    } catch (e) {
      setError((e as Error).message);
      return [];
    }
  }, []);

  const openRun = useCallback(async (id: string) => {
    try {
      const detail = await api.getRun(id);
      setSelected(detail);
      if (!detail.variants.includes(variantTab)) setVariantTab(detail.variants.at(-1) ?? "hybrid");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [variantTab]);

  useEffect(() => {
    loadRuns().then((list) => {
      const firstDone = list.find((r) => r.status === "done");
      if (firstDone) openRun(firstDone.id);
    });
    api.golden().then((g) => setGolden(g.questions)).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const active = runs.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(async () => {
      const list = await loadRuns();
      const justFinished = list.find((r) => r.status === "done" && (!selected || selected.id === r.id || selected.status !== "done"));
      if (!list.some((r) => r.status === "queued" || r.status === "running") && justFinished) openRun(list[0].id);
    }, 1500);
    return () => clearInterval(timer);
  }, [active, loadRuns, openRun, selected]);

  const start = async (preset?: "quick") => {
    setStarting(true);
    setError(null);
    try {
      const body =
        preset === "quick"
          ? { variants: Object.keys(VARIANTS), generate: false, judge: false, limit: null }
          : { variants, generate, judge: generate && judge, limit: limit ? Number(limit) : null };
      const run = await api.startRun(body);
      setRuns((prev) => [run, ...prev]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await api.deleteRun(id);
      if (selected?.id === id) setSelected(null);
      loadRuns();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const summary = selected?.summary ?? null;
  const shownMetrics = useMemo(
    () => METRICS.filter((m) => summary && Object.values(summary).some((s) => typeof s[m.key] === "number")),
    [summary],
  );
  const best = (key: string) => {
    if (!summary) return null;
    const values = Object.values(summary).map((s) => s[key as keyof VariantSummary]).filter((v): v is number => typeof v === "number");
    if (values.length < 2) return null;
    return key === "latency_ms" ? Math.min(...values) : Math.max(...values);
  };

  const rows: EvalResultRow[] = useMemo(() => {
    const all = (selected?.results ?? []).filter((r) => r.variant === variantTab);
    if (!onlyProblems) return all;
    return all.filter((r) => {
      const m = r.metrics;
      return m["hit@5"] === 0 || m.refusal_correct === 0 || (typeof m.key_facts === "number" && m.key_facts < 1) || (typeof m.faithfulness === "number" && m.faithfulness < 1) || !!m.error;
    });
  }, [selected, variantTab, onlyProblems]);

  return (
    <div className="mx-auto max-w-[1240px]">
      <PageHeader
        title="Evaluation"
        description="Run the golden question set against the test documents and compare pipeline variants. Retrieval is scored against expected passages, answers against key facts and reference answers, and an LLM judge checks faithfulness and correctness."
      />
      {error && <ErrorNote message={error} />}

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Card className="p-5">
          <h2 className="mb-1 text-[15px] font-semibold">Run an evaluation</h2>
          <p className="mb-3 text-[12.5px] text-mute">
            Runs on its own copy of the {golden.length ? `${golden.length}-question` : ""} golden set and test documents, so your library is never touched.
          </p>
          <fieldset className="mb-3">
            <legend className="mb-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-faint">Variants</legend>
            <div className="flex flex-wrap gap-2">
              {Object.entries(VARIANTS).map(([key, label]) => (
                <label key={key} className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-[13px]">
                  <input
                    type="checkbox"
                    checked={variants.includes(key)}
                    onChange={(e) => setVariants((v) => (e.target.checked ? [...v, key] : v.filter((x) => x !== key)))}
                  />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="mb-4 flex flex-wrap items-center gap-4 text-[13px]">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={generate} onChange={(e) => setGenerate(e.target.checked)} /> Generate answers
            </label>
            <label className={`flex items-center gap-2 ${generate ? "" : "opacity-40"}`}>
              <input type="checkbox" checked={judge && generate} disabled={!generate} onChange={(e) => setJudge(e.target.checked)} /> LLM judge
            </label>
            <label className="flex items-center gap-2">
              First
              <input value={limit} onChange={(e) => setLimit(e.target.value.replace(/\D/g, ""))} placeholder="all" className="w-14 rounded-lg border border-line px-2 py-1" />
              questions
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => start()} disabled={starting || active || variants.length === 0}>
              {starting ? <Spinner /> : <Play size={15} />} Start evaluation
            </Button>
            <Button onClick={() => start("quick")} disabled={starting || active}>
              Quick check: retrieval only
            </Button>
          </div>
          <p className="mt-2 text-xs text-faint">
            With a local model, a full run (4 variants, answers and judge) can take several minutes. The quick check needs no language model.
          </p>
        </Card>

        <Card className="p-5">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-[15px] font-semibold">Golden set and test documents</h2>
            <a href={api.samplesZipUrl()} className="inline-flex items-center gap-1.5 text-[13px] text-accent hover:underline">
              <FileArchive size={14} /> Download (.zip)
            </a>
          </div>
          <p className="mb-2 text-[12.5px] text-mute">
            {golden.filter((q) => q.answerable).length} answerable and {golden.filter((q) => !q.answerable).length} unanswerable questions across
            single-document, keyword, multi-document and follow-up cases.
          </p>
          <button type="button" onClick={() => setShowGolden((v) => !v)} className="inline-flex items-center gap-1 text-[13px] text-ink-2 hover:text-ink">
            {showGolden ? <ChevronDown size={15} /> : <ChevronRight size={15} />} {showGolden ? "Hide questions" : "Show questions"}
          </button>
          {showGolden && (
            <ul className="mt-2 max-h-[280px] space-y-2 overflow-y-auto pr-1">
              {golden.map((q) => (
                <li key={q.id} className="rounded-lg border border-line-soft p-2.5 text-[12.5px]">
                  <div className="flex gap-2">
                    <span className="font-mono text-faint">{q.id}</span>
                    <span className="rounded bg-[#f0f1f4] px-1.5 text-[11px] text-ink-2">{q.category}</span>
                  </div>
                  <div className="mt-1 font-medium">{q.question}</div>
                  <div className="text-mute">{q.answerable ? q.expected_sources.map((s) => `${s.file}: “${s.contains}”`).join(" · ") : "Should be refused"}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mb-4 overflow-hidden">
        <h2 className="px-5 pb-2 pt-4 text-[15px] font-semibold">Runs</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-[13.5px]">
            <thead>
              <tr className="border-y border-line bg-subtle text-left text-xs font-semibold text-mute">
                <th className="px-5 py-2">Started</th>
                <th className="px-3 py-2">Variants</th>
                <th className="px-3 py-2">Mode</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Best quality</th>
                <th className="px-5 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-6 text-center text-mute">
                    No runs yet.
                  </td>
                </tr>
              )}
              {runs.map((r) => {
                const bestQ = r.summary ? Math.max(...Object.values(r.summary).map((s) => s.quality_score ?? 0)) : null;
                const cfg = (r.config ?? {}) as { generate?: boolean; judge?: boolean };
                return (
                  <tr key={r.id} className={`border-b border-line-soft ${selected?.id === r.id ? "bg-[#f3f6fe]" : ""}`}>
                    <td className="px-5 py-2.5">{timeAgo(r.created_at)}</td>
                    <td className="px-3 py-2.5 text-ink-2">{r.variants.map((v) => VARIANTS[v] ?? v).join(", ")}</td>
                    <td className="px-3 py-2.5 text-ink-2">{cfg.generate === false ? "Retrieval only" : cfg.judge ? "Answers + judge" : "Answers"}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <StatusPill status={r.status} />
                        {r.status === "running" && r.total > 0 && (
                          <span className="text-xs tabular-nums text-mute">
                            {r.progress}/{r.total}
                          </span>
                        )}
                      </div>
                      {r.error && <div className="mt-1 max-w-[320px] text-xs text-bad">{r.error}</div>}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{bestQ !== null ? pct(bestQ, 1) : "–"}</td>
                    <td className="px-5 py-2.5">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" onClick={() => openRun(r.id)} disabled={r.status !== "done"}>
                          View
                        </Button>
                        {r.status === "done" && (
                          <a href={api.reportUrl(r.id)} aria-label="Download report" title="Download JSON report" className="rounded-lg p-2 text-mute hover:bg-[#eceef2]">
                            <Download size={15} />
                          </a>
                        )}
                        <button
                          type="button"
                          onClick={() => remove(r.id)}
                          disabled={r.status === "running" || r.status === "queued"}
                          aria-label="Delete run"
                          className="rounded-lg p-2 text-mute hover:bg-bad-soft hover:text-bad disabled:opacity-30"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {selected && summary && (
        <>
          <Card className="mb-4 overflow-hidden">
            <div className="px-5 pb-2 pt-4">
              <h2 className="text-[15px] font-semibold">Comparison</h2>
              <p className="text-[12.5px] text-mute">Best value in each row is highlighted. Retrieval metrics use answerable questions only.</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-[13.5px]">
                <thead>
                  <tr className="border-y border-line bg-subtle text-left text-xs font-semibold text-mute">
                    <th className="px-5 py-2">Metric</th>
                    {Object.keys(summary).map((v) => (
                      <th key={v} className="px-3 py-2 text-right">
                        {VARIANTS[v] ?? v}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shownMetrics.map((m, i) => {
                    const b = best(m.key as string);
                    const newGroup = i === 0 || shownMetrics[i - 1].group !== m.group;
                    return (
                      <Fragment key={m.key as string}>
                        {newGroup && (
                          <tr>
                            <td colSpan={Object.keys(summary).length + 1} className="bg-[#fbfbfc] px-5 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-[0.07em] text-faint">
                              {m.group}
                            </td>
                          </tr>
                        )}
                        <tr className="border-b border-line-soft">
                          <td className="px-5 py-2">
                            <div className="font-medium">{m.label}</div>
                            <div className="text-xs text-mute">{m.help}</div>
                          </td>
                          {Object.entries(summary).map(([v, s]) => {
                            const value = s[m.key];
                            const isBest = typeof value === "number" && b !== null && value === b;
                            return (
                              <td key={v} className={`px-3 py-2 text-right tabular-nums ${isBest ? "font-semibold text-ok" : ""}`}>
                                {fmt(m.key as string, value)}
                              </td>
                            );
                          })}
                        </tr>
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 pb-3 pt-4">
              <h2 className="text-[15px] font-semibold">Question by question</h2>
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex rounded-[10px] border border-line p-0.5 text-[13px]" role="tablist">
                  {selected.variants.map((v) => (
                    <button
                      key={v}
                      type="button"
                      role="tab"
                      aria-selected={variantTab === v}
                      onClick={() => setVariantTab(v)}
                      className={`rounded-[8px] px-2.5 py-1 ${variantTab === v ? "bg-[#eceef2] font-medium" : "text-mute"}`}
                    >
                      {VARIANTS[v] ?? v}
                    </button>
                  ))}
                </div>
                <label className="flex items-center gap-2 text-[13px]">
                  <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} /> Only problems
                </label>
              </div>
            </div>

            {summary[variantTab]?.by_category && (
              <div className="overflow-x-auto px-5 pb-3">
                <table className="w-full min-w-[560px] text-[12.5px]">
                  <thead>
                    <tr className="text-left text-xs text-mute">
                      <th className="py-1 pr-3 font-semibold">Category</th>
                      <th className="py-1 pr-3 text-right font-semibold">Questions</th>
                      <th className="py-1 pr-3 text-right font-semibold">Hit@5</th>
                      <th className="py-1 pr-3 text-right font-semibold">Recall@5</th>
                      <th className="py-1 pr-3 text-right font-semibold">Key facts</th>
                      <th className="py-1 text-right font-semibold">Correct refusals</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(summary[variantTab].by_category ?? {}).map(([cat, s]) => (
                      <tr key={cat} className="border-t border-line-soft">
                        <td className="py-1.5 pr-3">{cat}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{s.questions}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{pct(s["hit@5"])}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{pct(s["recall@5"])}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{pct(s.key_facts)}</td>
                        <td className="py-1.5 text-right tabular-nums">{pct(s.refusal_correct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-[13px]">
                <thead>
                  <tr className="border-y border-line bg-subtle text-left text-xs font-semibold text-mute">
                    <th className="w-8 px-3 py-2" />
                    <th className="px-2 py-2">Question</th>
                    <th className="px-2 py-2 text-center">Hit@5</th>
                    <th className="px-2 py-2 text-right">MRR</th>
                    <th className="px-2 py-2 text-right">Key facts</th>
                    <th className="px-2 py-2 text-center">Refusal OK</th>
                    <th className="px-2 py-2 text-right">Faithful</th>
                    <th className="px-4 py-2 text-right">Correct</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const m = r.metrics;
                    const key = `${r.variant}-${r.question_id}`;
                    const isOpen = open === key;
                    return (
                      <Fragment key={key}>
                        <tr className="cursor-pointer border-b border-line-soft hover:bg-subtle" onClick={() => setOpen(isOpen ? null : key)}>
                          <td className="px-3 py-2 text-mute">{isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
                          <td className="px-2 py-2">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-xs text-faint">{r.question_id}</span>
                              <span className="rounded bg-[#f0f1f4] px-1.5 text-[11px] text-ink-2">{r.category}</span>
                            </div>
                            <div className="font-medium">{r.question}</div>
                          </td>
                          <td className="px-2 py-2 text-center">
                            <Check ok={typeof m["hit@5"] === "number" ? m["hit@5"] === 1 : null} />
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums">{typeof m.mrr === "number" ? m.mrr.toFixed(2) : "–"}</td>
                          <td className="px-2 py-2 text-right tabular-nums">{typeof m.key_facts === "number" ? pct(m.key_facts) : "–"}</td>
                          <td className="px-2 py-2 text-center">
                            <Check ok={typeof m.refusal_correct === "number" ? m.refusal_correct === 1 : null} />
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums">{typeof m.faithfulness === "number" ? pct(m.faithfulness) : "–"}</td>
                          <td className="px-4 py-2 text-right tabular-nums">{typeof m.correctness === "number" ? pct(m.correctness) : "–"}</td>
                        </tr>
                        {isOpen && (
                          <tr className="border-b border-line-soft bg-[#fbfbfc]">
                            <td />
                            <td colSpan={7} className="px-2 py-3">
                              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                                <div>
                                  <div className="mb-1 text-xs font-semibold uppercase tracking-[0.06em] text-faint">Answer</div>
                                  <p className="whitespace-pre-wrap text-[13px]">{r.answer || "(retrieval-only run)"}</p>
                                  {golden.find((g) => g.id === r.question_id) && (
                                    <>
                                      <div className="mb-1 mt-3 text-xs font-semibold uppercase tracking-[0.06em] text-faint">Reference</div>
                                      <p className="text-[13px] text-mute">{golden.find((g) => g.id === r.question_id)?.reference}</p>
                                    </>
                                  )}
                                </div>
                                <div>
                                  <div className="mb-1 text-xs font-semibold uppercase tracking-[0.06em] text-faint">Passages sent to the model</div>
                                  <ol className="space-y-1.5">
                                    {r.retrieved.map((s) => (
                                      <li key={s.n} className={`rounded-lg border p-2 text-xs ${s.relevant ? "border-[#b7e0cb] bg-ok-soft/50" : "border-line-soft bg-panel"}`}>
                                        <div className="flex flex-wrap gap-x-2 font-medium">
                                          <span>[{s.n}]</span>
                                          <span>{s.filename}</span>
                                          <span className="font-normal text-mute">{locationLabel(s.page, s.section)}</span>
                                          {s.relevant && <span className="text-ok">expected</span>}
                                          {s.cited && <span className="text-accent">cited</span>}
                                        </div>
                                        <div className="mt-0.5 line-clamp-2 text-ink-2">{s.text}</div>
                                      </li>
                                    ))}
                                  </ol>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-5 py-6 text-center text-mute">
                        {onlyProblems ? "No problems in this variant." : "No results."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

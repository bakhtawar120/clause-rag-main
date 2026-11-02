"""Run the golden set against one or more pipeline variants and score every answer.

The runner builds its own in-memory engine over the sample documents, so a run is reproducible
and independent of whatever users uploaded.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.eval.dataset import GoldenQuestion, load_golden_set
from app.eval.judge import LLMJudge
from app.eval.metrics import (
    citation_precision,
    key_fact_coverage,
    retrieval_metrics,
    summarize,
    token_f1,
)
from app.rag.chunking import chunk_pages
from app.rag.context import ChunkRecord, format_sources, is_refusal
from app.rag.engine import RAGEngine
from app.rag.loaders import file_type_for, load_file
from app.rag.models import build_chat_model
from app.rag.preprocess import preprocess

log = logging.getLogger(__name__)

VARIANT_INFO = {
    "vector": "Meaning search only (embeddings)",
    "keyword": "Keyword search only (BM25)",
    "hybrid": "Meaning + keywords, fused with RRF",
    "hybrid_rerank": "Hybrid search, then re-ranking",
}

RETRIEVAL_KEYS = ["hit@1", "hit@3", "hit@5", "recall@5", "precision@5", "mrr"]
ANSWER_KEYS = ["refusal_correct", "key_facts", "answer_f1", "cited", "citation_precision"]
JUDGE_KEYS = ["faithfulness", "relevance", "correctness"]


def variant_config(name: str, settings: Settings) -> dict:
    if name == "vector":
        return {"mode": "vector", "reranker": "none"}
    if name == "keyword":
        return {"mode": "keyword", "reranker": "none"}
    if name == "hybrid":
        return {"mode": "hybrid", "reranker": "none"}
    if name == "hybrid_rerank":
        return {"mode": "hybrid", "reranker": settings.reranker if settings.reranker != "none" else "lexical"}
    raise ValueError(f"Unknown variant: {name}. Choose from {', '.join(VARIANT_INFO)}")


@dataclass
class EvalReport:
    started_at: str
    finished_at: str = ""
    config: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)  # variant -> metrics
    results: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "config": self.config,
            "summary": self.summary,
            "results": self.results,
        }


def build_eval_engine(settings: Settings, *, embeddings=None, llm=None) -> RAGEngine:
    golden = load_golden_set(settings.golden_set_path)
    engine = RAGEngine(settings, persist=False, embeddings=embeddings, llm=llm)
    records: list[ChunkRecord] = []
    next_id = 1
    for name in golden.documents:
        path = settings.samples_dir / name
        drafts = chunk_pages(preprocess(load_file(path, name)), settings.chunk_size, settings.chunk_overlap)
        for d in drafts:
            records.append(ChunkRecord(next_id, f"sample:{name}", name, file_type_for(name), d.text, d.chunk_index, d.page, d.section))
            next_id += 1
    engine.add_chunks(records)
    return engine


def _score_question(
    engine: RAGEngine,
    judge: LLMJudge | None,
    q: GoldenQuestion,
    cfg: dict,
    generate: bool,
) -> dict:
    t0 = time.perf_counter()
    history = [tuple(h) for h in q.history]
    if generate:
        outcome = engine.answer(q.question, history=history, strict=True, mode=cfg["mode"], reranker=cfg["reranker"])
        sources, answer, refused = outcome.sources, outcome.answer, outcome.refused
        standalone = outcome.plan.standalone
    else:
        r = engine.retrieve(q.question, history=history, mode=cfg["mode"], reranker=cfg["reranker"])
        sources, answer, refused, standalone = r.sources, "", None, r.plan.standalone
    latency = round((time.perf_counter() - t0) * 1000, 1)

    retrieved = [(s.chunk.filename, s.chunk.text) for s in sources]
    m: dict = {"answerable": q.answerable, "latency_ms": latency}
    if q.answerable:
        m.update(retrieval_metrics(q.expected_sources, retrieved))
    if generate:
        m["refusal_correct"] = 1.0 if (refused == (not q.answerable)) else 0.0
        if q.answerable:
            m["key_facts"] = key_fact_coverage(answer, q.must_include)
            m["answer_f1"] = round(token_f1(answer, q.reference), 4)
            cited = [(s.chunk.filename, s.chunk.text) for s in sources if s.cited]
            m["cited"] = 1.0 if (cited or refused) and not refused else 0.0
            m["citation_precision"] = citation_precision(cited, q.expected_sources)
        if judge is not None and answer and not refused:
            context = format_sources([s for s in sources if s.cited] or sources)
            m["faithfulness"] = judge.faithfulness(context, answer)
            m["relevance"] = judge.relevance(q.question, answer)
            if q.answerable:
                m["correctness"] = judge.correctness(q.question, q.reference, answer)
    return {
        "question_id": q.id,
        "category": q.category,
        "question": q.question,
        "standalone_query": standalone,
        "answer": answer,
        "metrics": m,
        "retrieved": [
            {
                "n": s.n,
                "filename": s.chunk.filename,
                "page": s.chunk.page,
                "section": s.chunk.section,
                "cited": s.cited,
                "score": round(s.score, 4),
                "text": s.chunk.text[:400],
                "relevant": any(
                    e.file == s.chunk.filename and e.contains.lower() in " ".join(s.chunk.text.split()).lower()
                    for e in q.expected_sources
                ),
            }
            for s in sources
        ],
    }


def _summary(rows: list[dict], generate: bool, judged: bool) -> dict:
    answerable = [r["metrics"] for r in rows if r["metrics"]["answerable"]]
    allm = [r["metrics"] for r in rows]
    out: dict = {"questions": len(rows), "answerable": len(answerable)}
    out.update(summarize(answerable, RETRIEVAL_KEYS))
    if generate:
        out.update(summarize(allm, ["refusal_correct"]))
        out.update(summarize(answerable, ["key_facts", "answer_f1", "cited", "citation_precision"]))
        unans = [m for m in allm if not m["answerable"]]
        out["refusal_accuracy_unanswerable"] = summarize(unans, ["refusal_correct"])["refusal_correct"]
    if judged:
        out.update(summarize(allm, ["faithfulness", "relevance"]))
        out.update(summarize(answerable, ["correctness"]))
    out["latency_ms"] = summarize(allm, ["latency_ms"])["latency_ms"]
    parts = [out.get("recall@5")]
    if generate:
        parts += [out.get("key_facts"), out.get("refusal_correct")]
    if judged:
        parts += [out.get("faithfulness")]
    parts = [p for p in parts if p is not None]
    out["quality_score"] = round(sum(parts) / len(parts), 4) if parts else None
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["metrics"])
    out["by_category"] = {
        cat: {
            "questions": len(ms),
            **summarize([m for m in ms if m["answerable"]], ["hit@5", "recall@5"]),
            **(summarize(ms, ["refusal_correct"]) if generate else {}),
            **(summarize([m for m in ms if m["answerable"]], ["key_facts"]) if generate else {}),
        }
        for cat, ms in by_cat.items()
    }
    return out


def run_evaluation(
    settings: Settings,
    *,
    variants: list[str] | None = None,
    generate: bool = True,
    judge: bool = True,
    limit: int | None = None,
    question_ids: list[str] | None = None,
    engine: RAGEngine | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> EvalReport:
    variants = variants or list(VARIANT_INFO)
    configs = {v: variant_config(v, settings) for v in variants}
    golden = load_golden_set(settings.golden_set_path)
    questions = golden.questions
    if question_ids:
        questions = [q for q in questions if q.id in set(question_ids)]
    if limit:
        questions = questions[:limit]

    engine = engine or build_eval_engine(settings)
    judge_obj = LLMJudge(build_chat_model(settings, purpose="judge")) if (generate and judge) else None

    report = EvalReport(
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        config={
            "variants": {v: {**configs[v], "description": VARIANT_INFO[v]} for v in variants},
            "generate": generate,
            "judge": bool(judge_obj),
            "questions": len(questions),
            "golden_set_version": golden.version,
            "settings": settings.public_dict(),
        },
    )
    total, done = len(questions) * len(variants), 0
    for variant in variants:
        rows = []
        for q in questions:
            try:
                row = _score_question(engine, judge_obj, q, configs[variant], generate)
            except Exception as exc:  # one failing question must not kill the run
                log.exception("Evaluation failed on %s/%s", variant, q.id)
                row = {"question_id": q.id, "category": q.category, "question": q.question, "standalone_query": "",
                       "answer": f"[error] {exc}", "metrics": {"answerable": q.answerable, "error": str(exc)}, "retrieved": []}
            row["variant"] = variant
            rows.append(row)
            report.results.append(row)
            done += 1
            if progress:
                progress(done, total)
        report.summary[variant] = _summary(rows, generate, bool(judge_obj))
    report.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return report


def save_report(report: EvalReport, directory: Path, run_id: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"eval_{run_id}.json"
    path.write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    return path


def format_table(summary: dict) -> str:
    cols = ["hit@1", "hit@5", "recall@5", "mrr", "key_facts", "refusal_correct", "faithfulness", "correctness", "quality_score"]
    header = f"{'variant':<15}" + "".join(f"{c:>16}" for c in cols)
    lines = [header, "-" * len(header)]
    for variant, s in summary.items():
        cells = "".join(f"{('-' if s.get(c) is None else f'{s[c]:.3f}'):>16}" for c in cols)
        lines.append(f"{variant:<15}{cells}")
    return "\n".join(lines)

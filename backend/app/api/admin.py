"""Admin endpoints: health, public config, stats, retrieval lab, evaluation runs."""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import get_engine, settings_dep
from app.core.config import Settings
from app.db.database import get_db
from app.db.models import Chunk, Conversation, Document, EvalResult, EvalRun, Message
from app.eval.dataset import load_golden_set
from app.eval.runner import VARIANT_INFO
from app.rag.engine import EmbeddingError, RAGEngine
from app.schemas import EvalRunIn, EvalRunOut, RetrievalTestIn
from app.services.evaluation import create_run, execute_run

router = APIRouter(tags=["admin"])


@router.get("/health")
def health(deep: bool = False, engine: RAGEngine = Depends(get_engine), settings: Settings = Depends(settings_dep)):
    out = {
        "status": "ok",
        "version": __version__,
        "chat_model": f"{settings.chat_provider}:{settings.chat_model}",
        "embedding_model": f"{settings.embedding_provider}:{settings.embedding_model}",
        "index": engine.stats(),
    }
    if deep:
        try:
            engine.embeddings.embed_query("ping")
            out["embeddings_reachable"] = True
        except Exception as exc:
            out["embeddings_reachable"] = False
            out["embeddings_error"] = str(exc)[:300]
            out["status"] = "degraded"
    return out


@router.get("/config")
def public_config(settings: Settings = Depends(settings_dep)):
    return settings.public_dict()


@router.get("/stats")
def stats(db: Session = Depends(get_db), engine: RAGEngine = Depends(get_engine)):
    by_status = dict(db.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    assistant = db.scalars(select(Message).where(Message.role == "assistant").order_by(Message.id.desc()).limit(500)).all()
    refused = [m for m in assistant if (m.meta or {}).get("refused")]
    gaps = []
    for m in refused[:8]:
        question = db.scalars(
            select(Message.content).where(Message.conversation_id == m.conversation_id, Message.role == "user", Message.id < m.id)
            .order_by(Message.id.desc()).limit(1)
        ).first()
        if question:
            gaps.append({"question": question, "asked_at": m.created_at})
    last_run = db.scalars(select(EvalRun).where(EvalRun.status == "done").order_by(EvalRun.created_at.desc()).limit(1)).first()
    recent_docs = db.scalars(select(Document).order_by(Document.created_at.desc()).limit(6)).all()
    return {
        "documents": {
            "total": sum(by_status.values()),
            "ready": by_status.get("ready", 0),
            "processing": by_status.get("processing", 0),
            "failed": by_status.get("failed", 0),
        },
        "chunks": db.scalar(select(func.count()).select_from(Chunk)) or 0,
        "index": engine.stats(),
        "conversations": db.scalar(select(func.count()).select_from(Conversation)) or 0,
        "questions": db.scalar(select(func.count()).select_from(Message).where(Message.role == "user")) or 0,
        "answers": len(assistant),
        "not_found_rate": round(len(refused) / len(assistant), 4) if assistant else None,
        "feedback": {
            "up": sum(1 for m in assistant if m.feedback == 1),
            "down": sum(1 for m in assistant if m.feedback == -1),
        },
        "content_gaps": gaps,
        "recent_documents": [
            {"id": d.id, "filename": d.filename, "status": d.status, "chunk_count": d.chunk_count, "created_at": d.created_at,
             "in_chat": d.conversation_id is not None}
            for d in recent_docs
        ],
        "last_eval": None if last_run is None else {"id": last_run.id, "created_at": last_run.created_at, "summary": last_run.summary},
    }


@router.post("/retrieval/test")
def retrieval_test(body: RetrievalTestIn, engine: RAGEngine = Depends(get_engine)):
    """Retrieval lab: see every stage for one query, without generating an answer."""
    try:
        r = engine.retrieve(body.query, mode=body.mode, reranker=body.reranker, top_n=body.top_n)
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def describe(cid: int) -> dict:
        c = engine.chunks.get(cid)
        if c is None:
            return {}
        return {"filename": c.filename, "page": c.page, "section": c.section, "text": c.text}

    return {
        "plan": {"route": r.plan.route, "standalone": r.plan.standalone, "sub_queries": r.plan.sub_queries,
                 "search_queries": r.plan.search_queries},
        "reranker": r.reranker_used,
        "timings_ms": r.timings,
        "candidates": [{**c.as_debug(), **describe(c.chunk_id)} for c in r.candidates[:20]],
        "context": [{"n": s.n, "score": round(s.score, 4), **s.debug, **describe(s.chunk.chunk_id)} for s in r.sources],
    }


# ------------------------------------------------------------------ evaluation
@router.get("/eval/golden")
def golden_set(settings: Settings = Depends(settings_dep)):
    golden = load_golden_set(settings.golden_set_path)
    return {"documents": golden.documents, "questions": [q.model_dump() for q in golden.questions], "variants": VARIANT_INFO}


@router.post("/eval/runs", response_model=EvalRunOut, status_code=202)
def start_eval(body: EvalRunIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    running = db.scalars(select(EvalRun).where(EvalRun.status.in_(["queued", "running"]))).first()
    if running:
        raise HTTPException(status_code=409, detail="An evaluation is already running. Wait for it to finish.")
    run = create_run(db, variants=list(body.variants), generate=body.generate, judge=body.judge, limit=body.limit)
    background.add_task(execute_run, run.id)
    return run


@router.get("/eval/runs", response_model=list[EvalRunOut])
def list_eval_runs(db: Session = Depends(get_db)):
    return db.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(50)).all()


@router.get("/eval/runs/{run_id}")
def get_eval_run(run_id: str, variant: str | None = Query(default=None), db: Session = Depends(get_db)):
    run = db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    stmt = select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.id)
    if variant:
        stmt = stmt.where(EvalResult.variant == variant)
    results = [
        {"variant": r.variant, "question_id": r.question_id, "category": r.category, "question": r.question,
         "answer": r.answer, "metrics": r.metrics, "retrieved": r.retrieved}
        for r in db.scalars(stmt).all()
    ]
    return {**EvalRunOut.model_validate(run).model_dump(mode="json"), "results": results}


@router.get("/eval/runs/{run_id}/report")
def download_eval_report(run_id: str, settings: Settings = Depends(settings_dep)):
    path = settings.reports_dir / f"eval_{run_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(path, filename=f"clause-eval-{run_id[:8]}.json", media_type="application/json")


@router.delete("/eval/runs/{run_id}", status_code=204)
def delete_eval_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    if run.status in ("queued", "running"):
        raise HTTPException(status_code=409, detail="This run is still in progress.")
    db.delete(run)
    db.commit()


def _json(obj) -> str:  # pragma: no cover - helper for debugging
    return json.dumps(obj, indent=2, default=str)

"""Evaluation runs triggered from the admin console (background tasks, results stored in the database)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import session_scope
from app.db.models import EvalResult, EvalRun
from app.eval.runner import run_evaluation, save_report

log = logging.getLogger(__name__)


def create_run(db: Session, *, variants: list[str], generate: bool, judge: bool, limit: int | None) -> EvalRun:
    run = EvalRun(status="queued", variants=variants, config={"generate": generate, "judge": judge, "limit": limit})
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def execute_run(run_id: str) -> None:
    settings = get_settings()
    with session_scope() as db:
        run = db.get(EvalRun, run_id)
        if run is None:
            return
        run.status = "running"
        opts = dict(run.config or {})
        variants = list(run.variants)

    def progress(done: int, total: int) -> None:
        if done == 1 or done % 5 == 0 or done == total:
            with session_scope() as db2:
                r = db2.get(EvalRun, run_id)
                if r is not None:
                    r.progress, r.total = done, total

    try:
        report = run_evaluation(
            settings,
            variants=variants,
            generate=bool(opts.get("generate", True)),
            judge=bool(opts.get("judge", True)),
            limit=opts.get("limit"),
            progress=progress,
        )
        save_report(report, settings.reports_dir, run_id)
        with session_scope() as db:
            run = db.get(EvalRun, run_id)
            for row in report.results:
                db.add(
                    EvalResult(
                        run_id=run_id,
                        variant=row["variant"],
                        question_id=row["question_id"],
                        category=row["category"],
                        question=row["question"],
                        answer=row["answer"],
                        metrics=row["metrics"],
                        retrieved=row["retrieved"],
                    )
                )
            run.summary = report.summary
            run.config = {**opts, **report.config}
            run.status = "done"
            run.finished_at = datetime.now(timezone.utc)
    except Exception as exc:
        log.exception("Evaluation run %s failed", run_id)
        with session_scope() as db:
            run = db.get(EvalRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = str(exc) or exc.__class__.__name__
                run.finished_at = datetime.now(timezone.utc)

"""Command-line evaluation.

  uv run python -m app.eval.cli                      # all variants, answers + judge
  uv run python -m app.eval.cli --no-generate        # retrieval metrics only (fast, no LLM)
  uv run python -m app.eval.cli --variants hybrid_rerank --min-hit5 0.9 --min-refusal 0.75   # CI quality gate
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid

from app.core.config import get_settings
from app.eval.runner import VARIANT_INFO, format_table, run_evaluation, save_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Clause against the golden set.")
    parser.add_argument("--variants", nargs="+", default=list(VARIANT_INFO), choices=list(VARIANT_INFO))
    parser.add_argument("--no-generate", action="store_true", help="Retrieval metrics only (no answers, no judge).")
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM-as-judge metrics.")
    parser.add_argument("--limit", type=int, default=None, help="Only the first N questions.")
    parser.add_argument("--min-hit5", type=float, default=None, help="Fail if hit@5 of the last variant is lower.")
    parser.add_argument("--min-refusal", type=float, default=None, help="Fail if refusal accuracy is lower.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    settings = get_settings()
    print(f"Chat: {settings.chat_provider}:{settings.chat_model} | Embeddings: {settings.embedding_provider}:{settings.embedding_model}")

    def progress(done: int, total: int) -> None:
        if done % 10 == 0 or done == total:
            print(f"  {done}/{total} answers scored", flush=True)

    report = run_evaluation(
        settings, variants=args.variants, generate=not args.no_generate, judge=not args.no_judge,
        limit=args.limit, progress=progress,
    )
    print()
    path = save_report(report, settings.reports_dir, uuid.uuid4().hex[:8])
    print(format_table(report.summary))
    print(f"\nFull report: {path}")

    last = report.summary[args.variants[-1]]
    failed = False
    if args.min_hit5 is not None and (last.get("hit@5") or 0) < args.min_hit5:
        print(f"FAIL hit@5 {last.get('hit@5')} < {args.min_hit5}")
        failed = True
    if args.min_refusal is not None and (last.get("refusal_correct") or 0) < args.min_refusal:
        print(f"FAIL refusal accuracy {last.get('refusal_correct')} < {args.min_refusal}")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

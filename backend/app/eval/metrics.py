"""Deterministic evaluation metrics (no model needed).

Retrieval (answerable questions only), computed on the final ranked context sent to the model:
  hit@k        1 if any expected source is in the top k
  recall@k     share of expected sources found in the top k
  precision@k  share of the top k that match an expected source
  mrr          1 / rank of the first matching source (0 if none)

Answer:
  refusal_correct   unanswerable -> refused; answerable -> not refused
  key_facts         share of must_include groups present in the answer
  answer_f1         token F1 against the reference answer
  cited             answerable and answered -> has at least one citation
  citation_precision share of cited sources that match an expected source
"""

from __future__ import annotations

import re
from statistics import mean

from app.eval.dataset import ExpectedSource
from app.rag.text import squash, tokenize

KS = (1, 3, 5)


def source_matches(expected: ExpectedSource, filename: str, text: str) -> bool:
    return filename == expected.file and squash(expected.contains) in squash(text)


def retrieval_metrics(expected: list[ExpectedSource], retrieved: list[tuple[str, str]]) -> dict[str, float]:
    """retrieved = [(filename, text), ...] in rank order."""
    relevant = [any(source_matches(e, f, t) for e in expected) for f, t in retrieved]
    out: dict[str, float] = {}
    for k in KS:
        top = retrieved[:k]
        found = sum(1 for e in expected if any(source_matches(e, f, t) for f, t in top))
        out[f"hit@{k}"] = 1.0 if found else 0.0
        out[f"recall@{k}"] = found / len(expected) if expected else 0.0
        out[f"precision@{k}"] = sum(relevant[:k]) / k
    first = next((i for i, rel in enumerate(relevant, start=1) if rel), None)
    out["mrr"] = 1.0 / first if first else 0.0
    return out


def key_fact_coverage(answer: str, groups: list[list[str]]) -> float:
    if not groups:
        return 1.0
    text = squash(answer)
    return sum(1 for group in groups if any(squash(alt) in text for alt in group)) / len(groups)


def token_f1(answer: str, reference: str) -> float:
    a = tokenize(re.sub(r"\[\d+\]", "", answer))
    r = tokenize(reference)
    if not a or not r:
        return 0.0
    common = sum(min(a.count(t), r.count(t)) for t in set(r))
    if common == 0:
        return 0.0
    precision, recall = common / len(a), common / len(r)
    return 2 * precision * recall / (precision + recall)


def citation_precision(cited: list[tuple[str, str]], expected: list[ExpectedSource]) -> float | None:
    if not cited:
        return None
    return sum(1 for f, t in cited if any(source_matches(e, f, t) for e in expected)) / len(cited)


def summarize(rows: list[dict], keys: list[str]) -> dict[str, float | None]:
    """Mean of each metric over the rows where it applies (None values are skipped)."""
    out: dict[str, float | None] = {}
    for key in keys:
        values = [r[key] for r in rows if r.get(key) is not None]
        out[key] = round(mean(values), 4) if values else None
    return out

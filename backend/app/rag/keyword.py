"""Keyword search (BM25) for exact terms that embeddings miss: product codes, numbers, names."""

from __future__ import annotations

import math
import threading

from rank_bm25 import BM25Okapi

from app.rag.text import tokenize


class BM25Index:
    def __init__(self) -> None:
        self._ids: list[int] = []
        self._docs: dict[int, list[str]] = {}
        self._bm25: BM25Okapi | None = None
        self._df: dict[str, int] = {}
        self._lock = threading.RLock()

    def build(self, texts: dict[int, str]) -> None:
        with self._lock:
            self._docs = {cid: tokenize(text) for cid, text in texts.items()}
            self._rebuild()

    def add(self, texts: dict[int, str]) -> None:
        with self._lock:
            self._docs.update({cid: tokenize(text) for cid, text in texts.items()})
            self._rebuild()

    def delete(self, ids) -> None:
        with self._lock:
            for cid in ids:
                self._docs.pop(cid, None)
            self._rebuild()

    def _rebuild(self) -> None:
        self._ids = [cid for cid, toks in self._docs.items() if toks]
        corpus = [self._docs[cid] for cid in self._ids]
        self._bm25 = BM25Okapi(corpus) if corpus else None
        df: dict[str, int] = {}
        for toks in corpus:
            for term in set(toks):
                df[term] = df.get(term, 0) + 1
        self._df = df

    def search(self, query: str, k: int, allowed_ids: set[int] | None = None) -> list[tuple[int, float]]:
        terms = tokenize(query)
        with self._lock:
            if self._bm25 is None or not terms or k <= 0:
                return []
            scores = self._bm25.get_scores(terms)
            ranked = sorted(zip(self._ids, scores), key=lambda pair: pair[1], reverse=True)
        hits = []
        for cid, score in ranked:
            if score <= 0:
                break
            if allowed_ids is not None and cid not in allowed_ids:
                continue
            hits.append((cid, float(score)))
            if len(hits) >= k:
                break
        return hits

    def idf(self, term: str) -> float:
        """Smoothed inverse document frequency, used by the lexical reranker."""
        n = len(self._ids) or 1
        return math.log(1 + (n - self._df.get(term, 0) + 0.5) / (self._df.get(term, 0) + 0.5))

    def count(self) -> int:
        return len(self._ids)

"""Retrieval: hybrid search (vectors + BM25) fused with Reciprocal Rank Fusion.

Includes metadata filtering (only the documents a chat may see) and vector-outlier exclusion
(drop weak vector hits that would otherwise sneak into the fused list).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Candidate:
    chunk_id: int
    fused_score: float = 0.0
    vector_score: float | None = None
    vector_rank: int | None = None
    keyword_score: float | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None
    matched_queries: set[int] = field(default_factory=set)

    def as_debug(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "fused_score": round(self.fused_score, 5),
            "vector_score": None if self.vector_score is None else round(self.vector_score, 4),
            "vector_rank": self.vector_rank,
            "keyword_score": None if self.keyword_score is None else round(self.keyword_score, 4),
            "keyword_rank": self.keyword_rank,
            "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 4),
        }


def exclude_vector_outliers(hits: list[tuple[int, float]], min_score: float, max_gap: float) -> list[tuple[int, float]]:
    """Keep hits that are good in absolute terms and not far behind the best hit."""
    if not hits:
        return []
    best = hits[0][1]
    return [(cid, s) for cid, s in hits if s >= min_score and (best - s) <= max_gap]


def rrf_fuse(ranked_lists: list[tuple[list[int], float]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion: score(d) = sum(weight / (k + rank)). Rank starts at 1."""
    scores: dict[int, float] = {}
    for ids, weight in ranked_lists:
        for rank, cid in enumerate(ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + weight / (k + rank)
    return scores


def hybrid_search(
    *,
    queries: list[str],
    embed_query,
    vector_store,
    keyword_index,
    allowed_ids: set[int] | None,
    mode: str,
    vector_top_k: int,
    keyword_top_k: int,
    rrf_k: int,
    vector_weight: float,
    keyword_weight: float,
    min_vector_score: float,
    vector_score_gap: float,
    limit: int,
) -> list[Candidate]:
    candidates: dict[int, Candidate] = {}
    ranked_lists: list[tuple[list[int], float]] = []

    for qi, query in enumerate(queries):
        if mode in ("hybrid", "vector"):
            vector = np.asarray(embed_query(query), dtype=np.float32)
            hits = vector_store.search(vector, vector_top_k, allowed_ids)
            hits = exclude_vector_outliers(hits, min_vector_score, vector_score_gap)
            ranked_lists.append(([cid for cid, _ in hits], vector_weight))
            for rank, (cid, score) in enumerate(hits, start=1):
                c = candidates.setdefault(cid, Candidate(cid))
                c.matched_queries.add(qi)
                if c.vector_score is None or score > c.vector_score:
                    c.vector_score, c.vector_rank = score, rank
        if mode in ("hybrid", "keyword"):
            hits = keyword_index.search(query, keyword_top_k, allowed_ids)
            ranked_lists.append(([cid for cid, _ in hits], keyword_weight))
            for rank, (cid, score) in enumerate(hits, start=1):
                c = candidates.setdefault(cid, Candidate(cid))
                c.matched_queries.add(qi)
                if c.keyword_score is None or score > c.keyword_score:
                    c.keyword_score, c.keyword_rank = score, rank

    fused = rrf_fuse(ranked_lists, k=rrf_k)
    for cid, score in fused.items():
        candidates[cid].fused_score = score
    ordered = sorted(candidates.values(), key=lambda c: c.fused_score, reverse=True)
    return ordered[:limit]

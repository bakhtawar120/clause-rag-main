"""Post-retrieval · re-ranking.

- "flashrank": a small cross-encoder (ms-marco MiniLM, ONNX) that reads query and passage together.
  Downloads the model (~30 MB) into DATA_DIR/models on first use. Falls back to "lexical" if unavailable.
- "llm":       asks the chat model to score each passage 0-10 (slower, no extra model).
- "lexical":   IDF-weighted query coverage blended with the fused rank (offline, instant).
- "none":      keep the hybrid-search order.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.rag.models import message_text
from app.rag.prompts import RERANK_SYSTEM, RERANK_USER
from app.rag.retrieval import Candidate
from app.rag.text import tokenize

log = logging.getLogger(__name__)


class Reranker:
    name = "none"

    def __init__(self) -> None:
        self.active_name = self.name  # may differ when a fallback is used

    def rerank(self, query: str, candidates: list[Candidate], texts: dict[int, str], idf=None) -> list[Candidate]:
        return candidates


class LexicalReranker(Reranker):
    name = "lexical"

    def rerank(self, query, candidates, texts, idf=None):
        terms = list(dict.fromkeys(tokenize(query)))
        if not terms or not candidates:
            return candidates
        weight = {t: (idf(t) if idf else 1.0) for t in terms}
        total = sum(weight.values()) or 1.0
        top_fused = max(c.fused_score for c in candidates) or 1.0
        for c in candidates:
            passage = set(tokenize(texts.get(c.chunk_id, "")))
            coverage = sum(w for t, w in weight.items() if t in passage) / total
            c.rerank_score = 0.75 * coverage + 0.25 * (c.fused_score / top_fused)
        return sorted(candidates, key=lambda c: c.rerank_score or 0.0, reverse=True)


class FlashRankReranker(Reranker):
    name = "flashrank"

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        super().__init__()
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._ranker = None
        self._failed = False
        self._fallback = LexicalReranker()

    def _get(self):
        if self._ranker is None and not self._failed:
            try:
                from flashrank import Ranker

                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._ranker = Ranker(model_name=self.model_name, cache_dir=str(self.cache_dir))
            except Exception as exc:
                self._failed = True
                log.warning("FlashRank unavailable (%s). Falling back to the lexical reranker.", exc)
        return self._ranker

    def rerank(self, query, candidates, texts, idf=None):
        ranker = self._get()
        if ranker is None or not candidates:
            self.active_name = "lexical (fallback)"
            return self._fallback.rerank(query, candidates, texts, idf)
        from flashrank import RerankRequest

        passages = [{"id": c.chunk_id, "text": texts.get(c.chunk_id, "")} for c in candidates]
        try:
            results = ranker.rerank(RerankRequest(query=query, passages=passages))
        except Exception as exc:
            log.warning("FlashRank failed (%s). Using the lexical reranker for this query.", exc)
            self.active_name = "lexical (fallback)"
            return self._fallback.rerank(query, candidates, texts, idf)
        self.active_name = self.name
        by_id = {c.chunk_id: c for c in candidates}
        ordered = []
        for item in results:
            c = by_id[int(item["id"])]
            c.rerank_score = float(item["score"])
            ordered.append(c)
        return ordered


class LLMReranker(Reranker):
    name = "llm"

    def __init__(self, llm) -> None:
        super().__init__()
        self.llm = llm
        self._fallback = LexicalReranker()

    def rerank(self, query, candidates, texts, idf=None):
        if not candidates:
            return candidates
        passages = "\n\n".join(f"[{i}] {texts.get(c.chunk_id, '')[:700]}" for i, c in enumerate(candidates, start=1))
        try:
            reply = message_text(
                self.llm.invoke([SystemMessage(RERANK_SYSTEM), HumanMessage(RERANK_USER.format(question=query, passages=passages))])
            )
            match = re.search(r"\{.*\}", reply, re.DOTALL)
            scores = json.loads(match.group(0))["scores"] if match else []
            if len(scores) != len(candidates):
                raise ValueError(f"expected {len(candidates)} scores, got {len(scores)}")
        except Exception as exc:
            log.warning("LLM rerank failed (%s). Using the lexical reranker.", exc)
            self.active_name = "lexical (fallback)"
            return self._fallback.rerank(query, candidates, texts, idf)
        self.active_name = self.name
        for c, s in zip(candidates, scores):
            c.rerank_score = max(0.0, min(1.0, float(s) / 10.0))
        return sorted(candidates, key=lambda c: c.rerank_score or 0.0, reverse=True)


def build_reranker(kind: str, *, llm=None, model_name: str = "", cache_dir: Path | None = None) -> Reranker:
    if kind == "lexical":
        return LexicalReranker()
    if kind == "flashrank":
        return FlashRankReranker(model_name, cache_dir or Path("data/models"))
    if kind == "llm":
        return LLMReranker(llm)
    return Reranker()

"""The RAG engine: ties indexing, pre-retrieval, retrieval, post-retrieval and generation together.

One engine serves the API (persistent FAISS index on disk). Evaluation runs build their own
in-memory engine over the sample documents, so results are reproducible and never touch user data.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.core.config import Settings
from app.rag.chunking import contextual_text
from app.rag.context import (
    ChunkRecord,
    Source,
    attach_citations,
    format_sources,
    is_refusal,
    select_context,
)
from app.rag.keyword import BM25Index
from app.rag.models import build_chat_model, build_embeddings, embedding_signature, message_text
from app.rag.prompts import ANSWER_SYSTEM_OPEN, ANSWER_SYSTEM_STRICT, ANSWER_USER, NOT_FOUND, SMALLTALK_REPLY
from app.rag.query import QueryPlan, plan_query
from app.rag.rerank import Reranker, build_reranker
from app.rag.retrieval import Candidate, hybrid_search
from app.rag.vectorstore import FaissVectorStore

log = logging.getLogger(__name__)

NO_DOCUMENTS = "There are no documents to search yet. Add a file to get started."


class EmbeddingError(RuntimeError):
    """The embedding model could not be reached or failed."""


@dataclass
class RetrievalOutcome:
    plan: QueryPlan
    candidates: list[Candidate]
    sources: list[Source]
    reranker_used: str
    timings: dict = field(default_factory=dict)


@dataclass
class AnswerOutcome:
    answer: str
    sources: list[Source]
    plan: QueryPlan
    refused: bool
    reranker_used: str
    timings: dict = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)

    def meta(self) -> dict:
        """Technical details for the admin console (never shown in the chat UI)."""
        return {
            "route": self.plan.route,
            "standalone_query": self.plan.standalone,
            "sub_queries": self.plan.sub_queries,
            "reranker": self.reranker_used,
            "refused": self.refused,
            "timings_ms": self.timings,
            "context": [{"n": s.n, "chunk_id": s.chunk.chunk_id, **s.debug} for s in self.sources],
        }


class RAGEngine:
    def __init__(self, settings: Settings, *, persist: bool = True, embeddings=None, llm=None) -> None:
        self.settings = settings
        self.embeddings = embeddings if embeddings is not None else build_embeddings(settings)
        self.llm = llm if llm is not None else build_chat_model(settings)
        self.signature = embedding_signature(settings)
        self.vector_store = FaissVectorStore(settings.index_dir if persist else None, self.signature)
        self.keyword_index = BM25Index()
        self.chunks: dict[int, ChunkRecord] = {}
        self._rerankers: dict[str, Reranker] = {}
        self._lock = threading.RLock()

    # ===================================================================== indexing
    def _index_text(self, r: ChunkRecord) -> str:
        """Text used for embeddings and keyword search: the chunk plus its file and section."""
        return contextual_text(r.filename, r.section, r.text) if self.settings.contextual_headers else r.text

    def _embed(self, records: list[ChunkRecord]) -> np.ndarray:
        texts = [self._index_text(r) for r in records]
        vectors: list[list[float]] = []
        size = max(1, self.settings.embedding_batch_size)
        try:
            for start in range(0, len(texts), size):
                vectors.extend(self.embeddings.embed_documents(texts[start : start + size]))
        except Exception as exc:
            raise EmbeddingError(
                "The embedding model could not be reached. Check that it is running and the settings in .env are correct."
            ) from exc
        return np.asarray(vectors, dtype=np.float32)

    def load(self, records: list[ChunkRecord]) -> dict:
        """Called at startup with every ready chunk from the database."""
        with self._lock:
            self.chunks = {r.chunk_id: r for r in records}
            self.keyword_index.build({r.chunk_id: self._index_text(r) for r in records})
            reason = None
            if not self.vector_store.signature_matches():
                reason = "embedding model changed"
            elif self.vector_store.count() != len(records):
                reason = "index out of sync with the database"
        if reason:
            log.warning("Rebuilding the vector index (%s): %d chunks", reason, len(records))
            self.rebuild(records)
        return {"chunks": len(records), "rebuilt": bool(reason), "reason": reason}

    def rebuild(self, records: list[ChunkRecord]) -> None:
        vectors = self._embed(records) if records else np.zeros((0, 1), dtype=np.float32)
        with self._lock:
            self.vector_store.reset(self.signature)
            if records:
                self.vector_store.add([r.chunk_id for r in records], vectors)
            self.chunks = {r.chunk_id: r for r in records}
            self.keyword_index.build({r.chunk_id: self._index_text(r) for r in records})
            self.vector_store.save()

    def add_chunks(self, records: list[ChunkRecord]) -> None:
        if not records:
            return
        vectors = self._embed(records)  # slow part, outside the lock
        with self._lock:
            self.vector_store.add([r.chunk_id for r in records], vectors)
            self.chunks.update({r.chunk_id: r for r in records})
            self.keyword_index.add({r.chunk_id: self._index_text(r) for r in records})
            self.vector_store.save()

    def remove_chunks(self, chunk_ids: list[int]) -> None:
        if not chunk_ids:
            return
        with self._lock:
            self.vector_store.delete(chunk_ids)
            for cid in chunk_ids:
                self.chunks.pop(cid, None)
            self.keyword_index.delete(chunk_ids)
            self.vector_store.save()

    def stats(self) -> dict:
        return {"chunks": len(self.chunks), "vectors": self.vector_store.count(), "keyword_docs": self.keyword_index.count()}

    # ===================================================================== retrieval
    def _reranker(self, kind: str) -> Reranker:
        if kind not in self._rerankers:
            self._rerankers[kind] = build_reranker(
                kind, llm=self.llm, model_name=self.settings.flashrank_model, cache_dir=self.settings.models_dir
            )
        return self._rerankers[kind]

    def allowed_chunk_ids(self, document_ids: set[str] | None) -> set[int] | None:
        """Metadata filter: restrict search to the documents this chat may use."""
        if document_ids is None:
            return None
        return {cid for cid, rec in self.chunks.items() if rec.document_id in document_ids}

    def retrieve(
        self,
        question: str,
        *,
        document_ids: set[str] | None = None,
        history: list[tuple[str, str]] | None = None,
        mode: str | None = None,
        reranker: str | None = None,
        top_n: int | None = None,
        plan: QueryPlan | None = None,
    ) -> RetrievalOutcome:
        s = self.settings
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        if plan is None:
            plan = plan_query(
                self.llm,
                question,
                history or [],
                rewrite=s.query_rewrite,
                expand=s.query_expansion,
                max_sub_queries=s.max_sub_queries,
            )
        timings["pre_retrieval"] = round((time.perf_counter() - t0) * 1000, 1)
        if plan.route != "documents":
            return RetrievalOutcome(plan, [], [], "none", timings)

        t1 = time.perf_counter()
        allowed = self.allowed_chunk_ids(document_ids)
        try:
            candidates = hybrid_search(
                queries=plan.search_queries,
                embed_query=self.embeddings.embed_query,
                vector_store=self.vector_store,
                keyword_index=self.keyword_index,
                allowed_ids=allowed,
                mode=mode or s.retrieval_mode,
                vector_top_k=s.vector_top_k,
                keyword_top_k=s.keyword_top_k,
                rrf_k=s.rrf_k,
                vector_weight=s.vector_weight,
                keyword_weight=s.keyword_weight,
                min_vector_score=s.min_vector_score,
                vector_score_gap=s.vector_score_gap,
                limit=s.rerank_candidates,
            )
        except Exception as exc:
            raise EmbeddingError(
                "The embedding model could not be reached. Check that it is running and the settings in .env are correct."
            ) from exc
        timings["retrieval"] = round((time.perf_counter() - t1) * 1000, 1)

        t2 = time.perf_counter()
        ranker = self._reranker(reranker or s.reranker)
        texts = {c.chunk_id: self._index_text(self.chunks[c.chunk_id]) for c in candidates if c.chunk_id in self.chunks}
        ranked = ranker.rerank(plan.standalone or question, list(candidates), texts, self.keyword_index.idf)
        sources = select_context(
            ranked, self.chunks, top_n=top_n or s.rerank_top_n, max_chars=s.max_context_chars, min_score=s.min_rerank_score
        )
        timings["post_retrieval"] = round((time.perf_counter() - t2) * 1000, 1)
        return RetrievalOutcome(plan, ranked, sources, ranker.active_name, timings)

    # ===================================================================== generation
    def _messages(self, question: str, sources: list[Source], history: list[tuple[str, str]], strict: bool) -> list[BaseMessage]:
        """The model answers the user's own words (with recent turns for context).

        The rewritten standalone query is used only for searching, so a bad rewrite can never
        make the model answer a different question than the one the user asked.
        """
        import re

        messages: list[BaseMessage] = [SystemMessage(ANSWER_SYSTEM_STRICT if strict else ANSWER_SYSTEM_OPEN)]
        for role, text in history[-2 * self.settings.history_turns :]:
            clean = re.sub(r"\[\d+\]", "", text)
            messages.append(HumanMessage(clean) if role == "user" else AIMessage(clean))
        if sources:
            messages.append(HumanMessage(ANSWER_USER.format(sources=format_sources(sources), question=question)))
        else:
            messages.append(HumanMessage(question))  # open mode with nothing relevant: plain chat
        return messages

    def _has_searchable(self, document_ids: set[str] | None) -> bool:
        allowed = self.allowed_chunk_ids(document_ids)
        return bool(self.chunks) and (allowed is None or bool(allowed))

    def _retrieve_for_answer(
        self, question: str, document_ids: set[str] | None, history: list[tuple[str, str]], strict: bool, **kwargs
    ) -> RetrievalOutcome:
        """Open mode with no documents to search skips retrieval and goes straight to the model."""
        if not strict and not self._has_searchable(document_ids):
            return RetrievalOutcome(QueryPlan(original=question, route="chat"), [], [], "none", {})
        return self.retrieve(question, document_ids=document_ids, history=history, **kwargs)

    def _early_answer(self, outcome: RetrievalOutcome, document_ids: set[str] | None, strict: bool) -> str | None:
        """Canned replies are for "Sources only" mode. With it off, the model answers like a normal chat."""
        if not strict:
            return None
        if outcome.plan.route == "smalltalk":
            return SMALLTALK_REPLY
        allowed = self.allowed_chunk_ids(document_ids)
        if not self.chunks or (allowed is not None and not allowed):
            return NO_DOCUMENTS
        if not outcome.sources:
            return NOT_FOUND
        return None

    def answer(
        self,
        question: str,
        *,
        document_ids: set[str] | None = None,
        history: list[tuple[str, str]] | None = None,
        strict: bool | None = None,
        mode: str | None = None,
        reranker: str | None = None,
    ) -> AnswerOutcome:
        history = history or []
        strict = self.settings.strict_sources if strict is None else strict
        r = self._retrieve_for_answer(question, document_ids, history, strict, mode=mode, reranker=reranker)
        early = self._early_answer(r, document_ids, strict)
        if early is not None:
            return AnswerOutcome(early, [], r.plan, early != SMALLTALK_REPLY, r.reranker_used, r.timings, r.candidates)
        t = time.perf_counter()
        reply = message_text(self.llm.invoke(self._messages(question, r.sources, history, strict)))
        r.timings["generation"] = round((time.perf_counter() - t) * 1000, 1)
        text, sources = attach_citations(reply.strip() or NOT_FOUND, r.sources)
        return AnswerOutcome(text, sources, r.plan, is_refusal(text), r.reranker_used, r.timings, r.candidates)

    def stream(
        self,
        question: str,
        *,
        document_ids: set[str] | None = None,
        history: list[tuple[str, str]] | None = None,
        strict: bool | None = None,
    ) -> Iterator[dict]:
        """Yields events: status, sources, token..., then done (with the final AnswerOutcome)."""
        history = history or []
        strict = self.settings.strict_sources if strict is None else strict
        if strict or self._has_searchable(document_ids):
            yield {"type": "status", "message": "Searching your documents"}
        r = self._retrieve_for_answer(question, document_ids, history, strict)
        early = self._early_answer(r, document_ids, strict)
        if early is not None:
            outcome = AnswerOutcome(early, [], r.plan, early != SMALLTALK_REPLY, r.reranker_used, r.timings, r.candidates)
            yield {"type": "token", "text": early}
            yield {"type": "done", "outcome": outcome}
            return
        yield {"type": "sources", "sources": [s.public() for s in r.sources]}
        yield {"type": "status", "message": "Writing the answer" if r.sources else "Thinking"}
        t = time.perf_counter()
        parts: list[str] = []
        for chunk in self.llm.stream(self._messages(question, r.sources, history, strict)):
            piece = message_text(chunk)
            if piece:
                parts.append(piece)
                yield {"type": "token", "text": piece}
        r.timings["generation"] = round((time.perf_counter() - t) * 1000, 1)
        text, sources = attach_citations("".join(parts).strip() or NOT_FOUND, r.sources)
        yield {"type": "done", "outcome": AnswerOutcome(text, sources, r.plan, is_refusal(text), r.reranker_used, r.timings, r.candidates)}

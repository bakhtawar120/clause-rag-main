"""Retrieval and post-retrieval building blocks."""

import numpy as np
import pytest

from app.rag.context import (
    ChunkRecord,
    attach_citations,
    extract_citations,
    is_refusal,
    sanitize_citations,
    select_context,
)
from app.rag.keyword import BM25Index
from app.rag.models import ExtractiveChatModel, HashingEmbeddings
from app.rag.query import plan_query, route_query
from app.rag.rerank import FlashRankReranker, LexicalReranker, LLMReranker
from app.rag.retrieval import Candidate, exclude_vector_outliers, rrf_fuse
from app.rag.vectorstore import FaissVectorStore


# ---------------------------------------------------------------- vector store
def test_faiss_add_search_delete_and_filter():
    emb = HashingEmbeddings()
    store = FaissVectorStore()
    texts = {1: "annual leave days", 2: "supplier invoice payment", 3: "delivery on sundays"}
    store.add(list(texts), np.asarray(emb.embed_documents(list(texts.values()))))
    query = np.asarray(emb.embed_query("how many leave days"))
    assert store.search(query, 1)[0][0] == 1
    assert store.search(query, 3, allowed_ids={2, 3})[0][0] in {2, 3}
    assert store.search(query, 3, allowed_ids=set()) == []
    store.delete([1])
    assert store.count() == 2 and all(cid != 1 for cid, _ in store.search(query, 3))


def test_faiss_persists_and_detects_embedding_change(tmp_path):
    emb = HashingEmbeddings()
    store = FaissVectorStore(tmp_path, signature="model-a")
    store.add([7], np.asarray(emb.embed_documents(["hello world"])))
    store.save()
    reloaded = FaissVectorStore(tmp_path, signature="model-a")
    assert reloaded.count() == 1 and reloaded.signature_matches()
    assert not FaissVectorStore(tmp_path, signature="model-b").signature_matches()


# ---------------------------------------------------------------- keyword search
def test_bm25_finds_exact_codes():
    index = BM25Index()
    index.build({1: "X200 headphones SKU-4471 costs 24,999", 2: "A50 earbuds SKU-3302", 3: "Delivery policy"})
    hits = index.search("SKU-4471", 3)
    assert hits[0][0] == 1 and hits[0][1] > hits[1][1]  # exact code beats a partial "sku" match
    assert index.search("SKU-4471", 3, allowed_ids={3}) == []
    index.delete([1])
    assert index.search("SKU-4471", 3) == []


# ---------------------------------------------------------------- fusion and outliers
def test_rrf_fusion_math():
    scores = rrf_fuse([([1, 2, 3], 1.0), ([3, 1], 1.0)], k=60)
    assert scores[1] == pytest.approx(1 / 61 + 1 / 62)
    assert scores[3] == pytest.approx(1 / 63 + 1 / 61)
    assert max(scores, key=scores.get) == 1


def test_rrf_weights():
    scores = rrf_fuse([([1], 1.0), ([2], 2.0)], k=60)
    assert scores[2] == pytest.approx(2 * scores[1])


def test_vector_outlier_exclusion():
    hits = [(1, 0.82), (2, 0.70), (3, 0.25), (4, 0.05)]
    assert [c for c, _ in exclude_vector_outliers(hits, min_score=0.1, max_gap=0.5)] == [1, 2]


# ---------------------------------------------------------------- pre-retrieval
def test_routing():
    assert route_query("hello!") == "smalltalk"
    assert route_query("Thanks") == "smalltalk"
    assert route_query("Hello, what is the notice period?") == "documents"


def test_query_rewrite_uses_history():
    plan = plan_query(
        ExtractiveChatModel(), "How many of those can be carried over?",
        [("user", "How many days of annual leave do employees get?"), ("assistant", "20 days [1].")],
        rewrite=True, expand=False, max_sub_queries=3,
    )
    assert "annual leave" in plan.standalone
    assert plan.search_queries[0] == plan.standalone


def test_no_rewrite_without_history():
    plan = plan_query(ExtractiveChatModel(), "What is the price of SKU-4471?", [], rewrite=True, expand=True, max_sub_queries=3)
    assert plan.standalone == "What is the price of SKU-4471?"
    assert plan.search_queries == ["What is the price of SKU-4471?"]


# ---------------------------------------------------------------- re-ranking
def _cands(n):
    return [Candidate(chunk_id=i, fused_score=1.0 / (60 + i)) for i in range(1, n + 1)]


def test_lexical_reranker_promotes_the_best_passage():
    texts = {1: "Delivery takes 3 to 5 days.", 2: "Express delivery takes 1 business day in Lahore.", 3: "Refunds policy."}
    ranked = LexicalReranker().rerank("express delivery Lahore", _cands(3), texts)
    assert ranked[0].chunk_id == 2 and ranked[0].rerank_score is not None


def test_flashrank_falls_back_when_model_is_unavailable(tmp_path, monkeypatch):
    import flashrank

    def boom(*args, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr(flashrank, "Ranker", boom)
    reranker = FlashRankReranker("ms-marco-MiniLM-L-12-v2", tmp_path)
    ranked = reranker.rerank("express delivery", _cands(2), {1: "refunds", 2: "express delivery"})
    assert reranker.active_name == "lexical (fallback)"
    assert ranked[0].chunk_id == 2


def test_llm_reranker_with_offline_model():
    texts = {1: "Refunds take 5 to 7 business days.", 2: "Sale items are final sale."}
    ranked = LLMReranker(ExtractiveChatModel()).rerank("are sale items final", _cands(2), texts)
    assert ranked[0].chunk_id == 2


# ---------------------------------------------------------------- context and citations
def _rec(cid, text, doc="d1", name="a.pdf"):
    return ChunkRecord(cid, doc, name, "pdf", text, 0, 1, "S")


def test_context_dedupes_and_respects_budget():
    chunks = {1: _rec(1, "Returns are accepted within 7 days of delivery."),
              2: _rec(2, "Returns are accepted within 7 days of delivery."),
              3: _rec(3, "x" * 500)}
    sources = select_context(_cands(3), chunks, top_n=5, max_chars=300)
    assert [s.chunk.chunk_id for s in sources] == [1]
    assert sources[0].n == 1


def test_citation_helpers():
    assert extract_citations("A [1]. B [2][1]. C [3, 4].") == [1, 2, 3, 4]
    assert sanitize_citations("Fact [1][7].", {1, 2}) == "Fact [1]."
    assert is_refusal("I couldn't find this in your documents.")
    assert not is_refusal("Returns are accepted within 7 days [1].")


def test_attach_citations_marks_cited_and_highlights():
    chunks = {1: _rec(1, "Intro line. Returns are accepted within 7 days of delivery. Other text."), 2: _rec(2, "Unrelated.")}
    sources = select_context(_cands(2), chunks, top_n=5, max_chars=5000)
    text, sources = attach_citations("You can return items within 7 days [1]. Bad cite [9].", sources)
    assert "[9]" not in text
    assert sources[0].cited and not sources[1].cited
    assert sources[0].highlight == "Returns are accepted within 7 days of delivery."

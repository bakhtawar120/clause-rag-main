"""Evaluation metrics, golden set validity, and the quality gate."""

import pytest

from app.eval.dataset import ExpectedSource, load_golden_set
from app.eval.judge import LLMJudge
from app.eval.metrics import citation_precision, key_fact_coverage, retrieval_metrics, token_f1
from app.eval.runner import build_eval_engine, format_table, run_evaluation
from app.rag.loaders import load_file
from app.rag.models import ExtractiveChatModel
from app.rag.preprocess import preprocess
from app.rag.text import squash


# ---------------------------------------------------------------- metrics
def test_retrieval_metrics():
    expected = [ExpectedSource(file="a.pdf", contains="30 days"), ExpectedSource(file="b.docx", contains="HR Director")]
    retrieved = [("c.md", "nothing"), ("a.pdf", "Notice is 30 days."), ("b.docx", "Approval by the HR Director.")]
    m = retrieval_metrics(expected, retrieved)
    assert m["hit@1"] == 0 and m["hit@3"] == 1
    assert m["recall@3"] == 1.0 and m["recall@1"] == 0.0
    assert m["precision@3"] == pytest.approx(2 / 3)
    assert m["mrr"] == pytest.approx(0.5)


def test_answer_metrics():
    assert key_fact_coverage("It is thirty (30) days.", [["30", "thirty"]]) == 1.0
    assert key_fact_coverage("It is a month.", [["30", "thirty"], ["notice"]]) == 0.0
    assert token_f1("Notice is 30 days [1].", "The notice period is 30 days.") > 0.5
    assert token_f1("", "anything") == 0.0
    assert citation_precision([("a.pdf", "Notice is 30 days.")], [ExpectedSource(file="a.pdf", contains="30 days")]) == 1.0
    assert citation_precision([], []) is None


def test_offline_judge_scores():
    judge = LLMJudge(ExtractiveChatModel())
    assert judge.faithfulness("Returns are accepted within 7 days of delivery.", "Returns are accepted within 7 days.") == 1.0
    assert judge.faithfulness("Returns are accepted within 7 days.", "The CEO is Jane Smith, appointed in 2019.") == 0.0
    assert judge.faithfulness("ctx", "I couldn't find this in your documents.") is None
    assert judge.correctness("q", "Returns within 7 days.", "Returns within 7 days.") == 1.0


# ---------------------------------------------------------------- golden set
def test_golden_set_is_valid_and_matches_the_documents(settings):
    golden = load_golden_set(settings.golden_set_path)
    assert len(golden.questions) >= 30
    categories = {q.category for q in golden.questions}
    assert {"single-doc", "keyword", "multi-doc", "follow-up", "unanswerable"} <= categories
    texts = {}
    for name in golden.documents:
        texts[name] = squash(" ".join(p.text for p in preprocess(load_file(settings.samples_dir / name))))
    for q in golden.questions:
        for src in q.expected_sources:
            assert squash(src.contains) in texts[src.file], f"{q.id}: '{src.contains}' not found in {src.file}"


# ---------------------------------------------------------------- quality gate
@pytest.fixture(scope="module")
def report(tmp_path_factory):
    import os

    from app.core.config import get_settings

    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("evaldata"))
    get_settings.cache_clear()
    settings = get_settings()
    engine = build_eval_engine(settings)
    yield run_evaluation(settings, engine=engine)
    get_settings.cache_clear()


def test_quality_gate_retrieval(report):
    hybrid = report.summary["hybrid"]
    reranked = report.summary["hybrid_rerank"]
    assert hybrid["hit@5"] >= 0.95
    assert hybrid["recall@5"] >= 0.95
    assert reranked["hit@1"] >= 0.9
    assert reranked["mrr"] >= 0.9
    # Hybrid search must not be worse than either single method on recall
    assert hybrid["recall@5"] >= report.summary["vector"]["recall@5"]


def test_quality_gate_answers(report):
    s = report.summary["hybrid_rerank"]
    assert s["refusal_accuracy_unanswerable"] == 1.0  # never invents an answer the documents do not contain
    assert s["refusal_correct"] >= 0.9
    assert s["key_facts"] >= 0.85
    assert s["faithfulness"] >= 0.9
    assert s["cited"] >= 0.9


def test_report_structure(report):
    assert len(report.results) == 4 * report.config["questions"]
    row = report.results[0]
    assert {"variant", "question_id", "answer", "metrics", "retrieved"} <= set(row)
    assert "hybrid_rerank" in format_table(report.summary)
    assert set(report.summary["hybrid"]["by_category"]) >= {"single-doc", "keyword", "multi-doc", "follow-up", "unanswerable"}

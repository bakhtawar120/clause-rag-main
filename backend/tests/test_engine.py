"""The full pipeline over the sample documents, with offline models."""

import pytest

from app.eval.runner import build_eval_engine
from app.rag.engine import NO_DOCUMENTS, RAGEngine
from app.rag.prompts import NOT_FOUND, SMALLTALK_REPLY


@pytest.fixture
def engine(settings):
    return build_eval_engine(settings)


def test_answer_is_grounded_and_cited(engine):
    out = engine.answer("What is the price of SKU-4471?")
    assert "24,999" in out.answer
    cited = [s for s in out.sources if s.cited]
    assert cited and cited[0].chunk.filename == "Price_List_Q3_2026.csv"
    assert not out.refused


def test_unanswerable_question_is_refused(engine):
    out = engine.answer("Who is the CEO of Acme?")
    assert out.answer == NOT_FOUND and out.refused


def test_smalltalk_skips_retrieval(engine):
    out = engine.answer("hello")
    assert out.answer == SMALLTALK_REPLY and out.sources == [] and not out.refused


def test_metadata_filter_limits_documents(engine):
    hr_ids = {cid for cid, r in engine.chunks.items() if r.filename == "HR_Policy_v7.pdf"}
    doc_id = engine.chunks[next(iter(hr_ids))].document_id
    r = engine.retrieve("What is the price of SKU-4471?", document_ids={doc_id})
    assert all(s.chunk.filename == "HR_Policy_v7.pdf" for s in r.sources)


def test_empty_scope_says_there_are_no_documents(engine):
    out = engine.answer("What is the notice period?", document_ids=set())
    assert out.answer == NO_DOCUMENTS


def test_stream_emits_events_in_order(engine):
    events = list(engine.stream("How long do customers have to return a product?"))
    types = [e["type"] for e in events]
    assert types[0] == "status" and "sources" in types and types[-1] == "done"
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    final = events[-1]["outcome"]
    assert "7 days" in final.answer and tokens.strip().startswith(final.answer.split("[")[0].strip()[:20])


def test_follow_up_uses_rewritten_query(engine):
    history = [("user", "How many days of paid annual leave do employees get?"), ("assistant", "20 working days [1].")]
    out = engine.answer("How many of those days can be carried over?", history=history)
    assert out.plan.standalone != "How many of those days can be carried over?"
    assert any("Up to 5 unused days" in s.chunk.text for s in out.sources)


def test_index_rebuilds_when_embedding_model_changes(settings):
    from app.rag.context import ChunkRecord

    records = [ChunkRecord(1, "d", "a.txt", "text", "annual leave is 20 days"), ChunkRecord(2, "d", "a.txt", "text", "notice is 30 days")]
    first = RAGEngine(settings)
    first.rebuild(records)
    second = RAGEngine(settings)
    second.signature = second.vector_store.signature = "fake:other-model"
    info = second.load(records)
    assert info["rebuilt"] and info["reason"] == "embedding model changed"
    assert second.vector_store.count() == 2


def test_topic_change_in_a_conversation_is_answered_on_its_own(engine):
    history = [("user", "Who has to approve a payment in lieu of notice?"), ("assistant", "The HR Director [1].")]
    out = engine.answer("Can I bring my dog to the office?", history=history)
    assert out.refused and "HR Director" not in out.answer


# ---------------------------------------------------------------- "Sources only" off: normal chat
class _RecordingLLM:
    """Stands in for the chat model and remembers what it was asked."""

    def __init__(self, reply: str = "Hello! How can I help you today?"):
        self.reply, self.calls = reply, []

    def invoke(self, messages, *args, **kwargs):
        from langchain_core.messages import AIMessage

        self.calls.append(messages)
        return AIMessage(self.reply)

    def stream(self, messages, *args, **kwargs):
        from langchain_core.messages import AIMessageChunk

        self.calls.append(messages)
        yield AIMessageChunk(content=self.reply)


def test_open_mode_smalltalk_goes_to_the_model(engine):
    engine.llm = llm = _RecordingLLM()
    out = engine.answer("hello", strict=False)
    assert out.answer == llm.reply and not out.refused
    assert llm.calls and llm.calls[-1][-1].content == "hello"  # plain chat turn, no SOURCES block


def test_open_mode_answers_without_any_documents(engine):
    engine.llm = llm = _RecordingLLM("Paris is the capital of France.")
    out = engine.answer("What is the capital of France?", document_ids=set(), strict=False)
    assert out.answer == llm.reply and out.sources == [] and not out.refused


def test_open_mode_stream_without_documents_skips_search(engine):
    engine.llm = _RecordingLLM("Hi there!")
    events = list(engine.stream("hi", document_ids=set(), strict=False))
    assert not any(e.get("message") == "Searching your documents" for e in events)
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Hi there!"
    assert events[-1]["type"] == "done"


def test_strict_mode_still_refuses_without_documents(engine):
    engine.llm = llm = _RecordingLLM()
    out = engine.answer("What is the capital of France?", document_ids=set(), strict=True)
    assert out.answer == NO_DOCUMENTS and not llm.calls

"""HTTP API, end to end, with offline models."""

import json

from tests.conftest import SAMPLES


def _upload(client, names, conversation_id=None):
    files = [("files", (n, (SAMPLES / n).read_bytes())) for n in names]
    data = {"conversation_id": conversation_id} if conversation_id else {}
    resp = client.post("/api/documents", files=files, data=data)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_health_and_config(client):
    assert client.get("/api/health").json()["status"] == "ok"
    deep = client.get("/api/health", params={"deep": True}).json()
    assert deep["embeddings_reachable"] is True
    cfg = client.get("/api/config").json()
    assert cfg["retrieval"]["mode"] == "hybrid"
    assert "api_key" not in json.dumps(cfg)


def test_upload_many_files_and_inspect(client):
    results = _upload(client, ["HR_Policy_v7.pdf", "Price_List_Q3_2026.csv", "Employment_Contract_Template.docx"])
    assert [r["document"]["status"] for r in results] == ["ready", "ready", "ready"]
    doc = results[0]["document"]
    assert doc["pages"] == 3 and doc["chunk_count"] > 5

    chunks = client.get(f"/api/documents/{doc['id']}/chunks").json()
    assert any(c["section"] and "Notice periods" in c["section"] for c in chunks)

    original = client.get(f"/api/documents/{doc['id']}/file")
    assert original.status_code == 200 and original.content[:4] == b"%PDF"

    assert len(client.get("/api/documents").json()) == 3


def test_duplicates_and_bad_files(client):
    _upload(client, ["Delivery_Policy.txt"])
    again = _upload(client, ["Delivery_Policy.txt"])[0]
    assert again["duplicate"] is True
    bad = client.post("/api/documents", files=[("files", ("virus.exe", b"MZ..."))]).json()[0]
    assert bad["document"] is None and "not supported" in bad["error"]
    empty = client.post("/api/documents", files=[("files", ("empty.txt", b""))]).json()[0]
    assert "empty" in empty["error"]


def test_chat_answers_with_citations(client):
    _upload(client, ["Price_List_Q3_2026.csv", "Returns_and_Warranty_FAQ.md"])
    resp = client.post("/api/chat", json={"question": "What is the price of SKU-4471?"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "24,999" in body["message"]["content"]
    cited = [s for s in body["message"]["sources"] if s["cited"]]
    assert cited and cited[0]["filename"] == "Price_List_Q3_2026.csv" and cited[0]["highlight"]
    # the chat UI payload carries no internal scores
    assert "score" not in cited[0] and "chunk_id" not in cited[0]

    conv = client.get(f"/api/conversations/{body['conversation_id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]


def test_chat_refuses_when_documents_do_not_cover_it(client):
    _upload(client, ["HR_Policy_v7.pdf"])
    body = client.post("/api/chat", json={"question": "Who is the CEO of Acme?"}).json()
    assert body["refused"] is True and "couldn't find" in body["message"]["content"]


def test_streaming_chat(client):
    _upload(client, ["Delivery_Policy.txt"])
    with client.stream("POST", "/api/chat/stream", json={"question": "How long does express delivery take?"}) as resp:
        assert resp.status_code == 200
        events = [json.loads(line) for line in resp.iter_lines() if line]
    types = [e["type"] for e in events]
    assert types[0] == "conversation" and "sources" in types and types[-1] == "done"
    assert "1 business day" in events[-1]["message"]["content"]


def test_chat_scope_only_uses_files_in_that_chat(client):
    _upload(client, ["Price_List_Q3_2026.csv"])  # library
    conv = client.post("/api/conversations", json={}).json()
    _upload(client, ["Delivery_Policy.txt"], conversation_id=conv["id"])  # private to this chat
    body = client.post(
        "/api/chat", json={"question": "What is the price of SKU-4471?", "conversation_id": conv["id"], "scope": "chat"}
    ).json()
    assert all(s["filename"] == "Delivery_Policy.txt" for s in body["message"]["sources"])
    # chat files are not listed in the shared library
    assert [d["filename"] for d in client.get("/api/documents").json()] == ["Price_List_Q3_2026.csv"]


def test_follow_up_question_in_same_conversation(client):
    _upload(client, ["HR_Policy_v7.pdf"])
    first = client.post("/api/chat", json={"question": "How many days of paid annual leave do employees get?"}).json()
    second = client.post(
        "/api/chat", json={"question": "How many unused days can be carried over?", "conversation_id": first["conversation_id"]}
    ).json()
    assert "5" in second["message"]["content"]


def test_feedback_and_stats(client):
    _upload(client, ["Returns_and_Warranty_FAQ.md"])
    body = client.post("/api/chat", json={"question": "Can sale items be returned?"}).json()
    client.post("/api/chat", json={"question": "Can I bring my dog to the office?"})
    msg_id = body["message"]["id"]
    assert client.post(f"/api/messages/{msg_id}/feedback", json={"value": 1}).json()["feedback"] == 1
    stats = client.get("/api/stats").json()
    assert stats["documents"]["ready"] == 1 and stats["questions"] == 2
    assert stats["feedback"]["up"] == 1 and stats["not_found_rate"] == 0.5
    assert stats["content_gaps"][0]["question"] == "Can I bring my dog to the office?"


def test_delete_document_removes_it_from_search(client):
    doc = _upload(client, ["Price_List_Q3_2026.csv"])[0]["document"]
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    body = client.post("/api/chat", json={"question": "What is the price of SKU-4471?"}).json()
    assert body["message"]["sources"] == []
    assert client.get("/api/health").json()["index"]["vectors"] == 0


def test_reindex_document(client):
    doc = _upload(client, ["Travel_and_Expenses_Policy.html"])[0]["document"]
    again = client.post(f"/api/documents/{doc['id']}/reindex").json()
    assert again["status"] == "ready" and again["chunk_count"] == doc["chunk_count"]
    assert client.get("/api/health").json()["index"]["vectors"] == doc["chunk_count"]


def test_index_survives_restart(settings):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        _upload(c, ["Delivery_Policy.txt"])
    with TestClient(app) as c:  # new lifespan: reloads from SQLite + FAISS on disk
        body = c.post("/api/chat", json={"question": "Is there delivery on Sundays?"}).json()
        assert body["message"]["sources"]


def test_samples_list_download_zip_and_import(client):
    samples = client.get("/api/samples").json()
    assert len(samples) == 7
    one = client.get("/api/samples/HR_Policy_v7.pdf")
    assert one.status_code == 200 and "attachment" in one.headers["content-disposition"]
    assert client.get("/api/samples/../../etc/passwd").status_code == 404
    archive = client.get("/api/samples/archive")
    assert archive.status_code == 200 and archive.content[:2] == b"PK"
    imported = client.post("/api/samples/import").json()
    assert sum(1 for r in imported if r["document"] and r["document"]["status"] == "ready") == 7


def test_retrieval_lab(client):
    client.post("/api/samples/import")
    body = client.post("/api/retrieval/test", json={"query": "price of SKU-4471", "mode": "hybrid"}).json()
    assert body["context"][0]["filename"] == "Price_List_Q3_2026.csv"
    first = body["candidates"][0]
    assert {"vector_rank", "keyword_rank", "fused_score", "rerank_score"} <= set(first)


def test_evaluation_run_via_api(client):
    resp = client.post("/api/eval/runs", json={"variants": ["hybrid"], "generate": True, "judge": True, "limit": 5})
    assert resp.status_code == 202
    run_id = resp.json()["id"]
    run = client.get(f"/api/eval/runs/{run_id}").json()  # TestClient runs background tasks before returning
    assert run["status"] == "done", run.get("error")
    assert run["summary"]["hybrid"]["questions"] == 5
    assert len(run["results"]) == 5
    report = client.get(f"/api/eval/runs/{run_id}/report")
    assert report.status_code == 200 and report.json()["summary"]["hybrid"]
    golden = client.get("/api/eval/golden").json()
    assert len(golden["questions"]) >= 30 and "hybrid_rerank" in golden["variants"]

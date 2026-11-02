"""Test setup: offline models only (no network, no API keys), and a fresh data folder per test."""

from __future__ import annotations

import os

# Must be set before the app reads its settings.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "CHAT_PROVIDER": "fake",
        "EMBEDDING_PROVIDER": "fake",
        "JUDGE_PROVIDER": "fake",
        "RERANKER": "lexical",
        "QUERY_EXPANSION": "false",
        "LOG_LEVEL": "WARNING",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import BACKEND_DIR, get_settings  # noqa: E402

SAMPLES = BACKEND_DIR / "sample_docs"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


@pytest.fixture
def client(settings):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_files():
    return sorted(p for p in SAMPLES.iterdir() if p.is_file())

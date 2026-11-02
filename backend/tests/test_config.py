import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_work_without_env_file(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.sqlalchemy_url.startswith("sqlite:///")
    assert s.retrieval_mode == "hybrid"


def test_cors_origins_accepts_comma_separated(monkeypatch, tmp_path):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://clause.example.com")
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.cors_origins == ["http://localhost:3000", "https://clause.example.com"]


def test_invalid_chunk_overlap_is_rejected(tmp_path):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, data_dir=tmp_path, chunk_size=200, chunk_overlap=300)


def test_secrets_are_hidden(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAT_API_KEY", "sk-very-secret")
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert "sk-very-secret" not in repr(s)
    assert "sk-very-secret" not in str(s.public_dict())
    assert s.chat_api_key.get_secret_value() == "sk-very-secret"


def test_empty_judge_falls_back_to_chat_model(monkeypatch, tmp_path):
    monkeypatch.setenv("JUDGE_PROVIDER", "")
    s = Settings(_env_file=None, data_dir=tmp_path, chat_provider="ollama", chat_model="m1")
    assert s.public_dict()["judge"] == {"provider": "ollama", "model": "m1"}

"""Application settings, loaded from environment variables and the `.env` file.

Rules:
- Every setting has a safe default, so the app starts with no `.env` at all.
- Secrets are `SecretStr`: they never appear in logs, reprs or the public config endpoint.
- Real environment variables override `.env` values (useful in Docker / CI).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

Provider = str  # any LangChain provider name ("ollama", "openai", "anthropic", ...) or "fake"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- App ----------
    app_name: str = "Clause"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    data_dir: Path = BACKEND_DIR / "data"
    database_url: str | None = None  # default: SQLite file inside data_dir; set a postgresql+psycopg:// URL later
    max_upload_mb: int = 25

    # ---------- Models (LangChain init_chat_model / init_embeddings) ----------
    chat_provider: Provider = "ollama"
    chat_model: str = "gemma3:4b"
    chat_temperature: float = 0.1
    chat_api_key: SecretStr | None = None
    chat_base_url: str | None = None  # e.g. http://localhost:11434 for Ollama

    embedding_provider: Provider = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_api_key: SecretStr | None = None
    embedding_base_url: str | None = None
    embedding_batch_size: int = 64

    # Evaluation judge (defaults to the chat model when empty)
    judge_provider: Provider | None = None
    judge_model: str | None = None
    judge_api_key: SecretStr | None = None
    judge_base_url: str | None = None

    # ---------- Indexing ----------
    chunk_size: int = 900  # characters
    chunk_overlap: int = 150
    contextual_headers: bool = True  # embed "file > section" together with each chunk

    # ---------- Pre-retrieval ----------
    query_rewrite: bool = True  # turn follow-ups into standalone questions
    query_expansion: bool = False  # split complex questions into sub-questions
    max_sub_queries: int = 3

    # ---------- Retrieval ----------
    retrieval_mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rrf_k: int = 60
    vector_weight: float = 1.0
    keyword_weight: float = 1.0
    min_vector_score: float = 0.10  # drop vector hits below this cosine similarity
    vector_score_gap: float = 0.50  # drop vector hits this far below the best hit

    # ---------- Post-retrieval ----------
    reranker: Literal["none", "lexical", "flashrank", "llm"] = "flashrank"
    flashrank_model: str = "ms-marco-MiniLM-L-12-v2"
    rerank_candidates: int = 30
    rerank_top_n: int = 5
    min_rerank_score: float | None = None
    max_context_chars: int = 12000
    strict_sources: bool = True  # answer only from documents
    history_turns: int = 4

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "judge_provider",
        "judge_model",
        "chat_base_url",
        "embedding_base_url",
        "judge_base_url",
        "chat_api_key",
        "embedding_api_key",
        "judge_api_key",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.rerank_top_n > self.rerank_candidates:
            raise ValueError("RERANK_TOP_N must not exceed RERANK_CANDIDATES")
        if not self.data_dir.is_absolute():
            self.data_dir = (BACKEND_DIR / self.data_dir).resolve()
        return self

    # ---------- Derived paths ----------
    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'clause.db'}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "eval_reports"

    @property
    def samples_dir(self) -> Path:
        return BACKEND_DIR / "sample_docs"

    @property
    def golden_set_path(self) -> Path:
        return BACKEND_DIR / "eval" / "golden_set.json"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.uploads_dir, self.index_dir, self.models_dir, self.reports_dir):
            path.mkdir(parents=True, exist_ok=True)

    def public_dict(self) -> dict:
        """Non-secret settings, safe to show in the admin console."""
        return {
            "app_name": self.app_name,
            "environment": self.environment,
            "chat": {"provider": self.chat_provider, "model": self.chat_model, "temperature": self.chat_temperature},
            "embeddings": {"provider": self.embedding_provider, "model": self.embedding_model},
            "judge": {
                "provider": self.judge_provider or self.chat_provider,
                "model": self.judge_model or self.chat_model,
            },
            "database": "postgresql" if self.sqlalchemy_url.startswith("postgres") else "sqlite",
            "vector_store": "faiss",
            "indexing": {
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
                "contextual_headers": self.contextual_headers,
            },
            "pre_retrieval": {
                "query_rewrite": self.query_rewrite,
                "query_expansion": self.query_expansion,
                "max_sub_queries": self.max_sub_queries,
            },
            "retrieval": {
                "mode": self.retrieval_mode,
                "vector_top_k": self.vector_top_k,
                "keyword_top_k": self.keyword_top_k,
                "rrf_k": self.rrf_k,
                "vector_weight": self.vector_weight,
                "keyword_weight": self.keyword_weight,
                "min_vector_score": self.min_vector_score,
                "vector_score_gap": self.vector_score_gap,
            },
            "post_retrieval": {
                "reranker": self.reranker,
                "rerank_candidates": self.rerank_candidates,
                "rerank_top_n": self.rerank_top_n,
                "min_rerank_score": self.min_rerank_score,
                "max_context_chars": self.max_context_chars,
                "strict_sources": self.strict_sources,
            },
            "max_upload_mb": self.max_upload_mb,
        }


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings

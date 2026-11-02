from __future__ import annotations

from fastapi import Request

from app.core.config import Settings, get_settings
from app.rag.engine import RAGEngine


def get_engine(request: Request) -> RAGEngine:
    return request.app.state.engine


def settings_dep() -> Settings:
    return get_settings()

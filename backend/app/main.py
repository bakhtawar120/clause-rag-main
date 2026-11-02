"""Clause API.

Run (from the backend folder):
    uv run fastapi dev            # development, auto-reload, http://localhost:8000/docs
    uv run fastapi run            # production
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import update

from app import __version__
from app.api import admin, chat, documents
from app.core.config import get_settings
from app.db.database import init_db, session_scope
from app.db.models import Document
from app.rag.engine import EmbeddingError, RAGEngine
from app.rag.loaders import LoaderError
from app.services.documents import load_ready_records

log = logging.getLogger("clause")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db(settings.sqlalchemy_url)
    engine = RAGEngine(settings)
    with session_scope() as db:
        # A restart in the middle of an upload leaves documents stuck in "processing".
        db.execute(
            update(Document)
            .where(Document.status == "processing")
            .values(status="failed", error="Processing was interrupted. Re-index the document to try again.")
        )
        records = load_ready_records(db)
    try:
        info = engine.load(records)
        log.info("Clause ready: %s chunks indexed (rebuilt: %s)", info["chunks"], info["rebuilt"])
    except EmbeddingError as exc:
        log.error("Could not build the vector index at startup: %s", exc)
    app.state.engine = engine
    yield


app = FastAPI(
    title="Clause API",
    version=__version__,
    description="Grounded answers from your documents: hybrid retrieval, re-ranking, citations and evaluation.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.exception_handler(LoaderError)
async def loader_error_handler(_: Request, exc: LoaderError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(EmbeddingError)
async def embedding_error_handler(_: Request, exc: EmbeddingError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def root():
    return {"name": "Clause API", "version": __version__, "docs": "/docs"}

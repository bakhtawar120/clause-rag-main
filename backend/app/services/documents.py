"""Document lifecycle: upload -> load -> pre-process -> chunk -> embed -> index, plus delete and re-index."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Chunk, Document
from app.rag.chunking import chunk_pages
from app.rag.context import ChunkRecord
from app.rag.engine import EmbeddingError, RAGEngine
from app.rag.loaders import LoaderError, file_type_for, load_file
from app.rag.preprocess import preprocess

log = logging.getLogger(__name__)


def _record(chunk: Chunk, doc: Document) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk.id,
        document_id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        text=chunk.text,
        chunk_index=chunk.chunk_index,
        page=chunk.page,
        section=chunk.section,
    )


def load_ready_records(db: Session) -> list[ChunkRecord]:
    rows = db.execute(select(Chunk, Document).join(Document).where(Document.status == "ready")).all()
    return [_record(chunk, doc) for chunk, doc in rows]


def safe_filename(name: str) -> str:
    name = Path(name or "file").name.strip().replace("\x00", "")
    return name[:200] or "file"


def _index(db: Session, engine: RAGEngine, settings: Settings, doc: Document) -> None:
    """Read the stored file and (re)build its chunks. Sets doc.status / doc.error."""
    path = Path(doc.storage_path)
    try:
        pages = preprocess(load_file(path, doc.filename))
        drafts = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
        if not drafts:
            raise LoaderError("No readable text was found in this file.")
        chunks = [
            Chunk(document_id=doc.id, chunk_index=d.chunk_index, text=d.text, page=d.page, section=d.section, char_count=len(d.text))
            for d in drafts
        ]
        db.add_all(chunks)
        db.flush()  # assigns chunk ids
        engine.add_chunks([_record(c, doc) for c in chunks])
        page_numbers = {p.page for p in pages if p.page is not None}
        doc.pages = max(page_numbers) if page_numbers else None
        doc.chunk_count = len(chunks)
        doc.status, doc.error = "ready", None
    except (LoaderError, EmbeddingError) as exc:
        db.rollback()
        db.add(doc)
        doc.status, doc.error, doc.chunk_count = "failed", str(exc), 0
    except Exception:  # unexpected: keep the details in the log, show a plain message
        log.exception("Failed to index %s", doc.filename)
        db.rollback()
        db.add(doc)
        doc.status, doc.error, doc.chunk_count = "failed", "Something went wrong while reading this file.", 0


def ingest_file(
    db: Session,
    engine: RAGEngine,
    settings: Settings,
    *,
    filename: str,
    data: bytes,
    conversation_id: str | None = None,
) -> tuple[Document, bool]:
    """Store and index one file. Returns (document, is_duplicate)."""
    filename = safe_filename(filename)
    file_type = file_type_for(filename)  # raises LoaderError for unsupported types
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise LoaderError(f"This file is larger than {settings.max_upload_mb} MB.")
    if not data:
        raise LoaderError("The file is empty.")
    digest = hashlib.sha256(data).hexdigest()

    existing = db.scalars(
        select(Document).where(
            Document.sha256 == digest,
            Document.status == "ready",
            Document.conversation_id.is_(None) if conversation_id is None else Document.conversation_id == conversation_id,
        )
    ).first()
    if existing:
        return existing, True

    doc = Document(filename=filename, file_type=file_type, size_bytes=len(data), sha256=digest, storage_path="",
                   conversation_id=conversation_id, status="processing")
    db.add(doc)
    db.flush()
    path = settings.uploads_dir / f"{doc.id}{Path(filename).suffix.lower()}"
    path.write_bytes(data)
    doc.storage_path = str(path)
    db.commit()

    _index(db, engine, settings, doc)
    db.commit()
    db.refresh(doc)
    return doc, False


def delete_document(db: Session, engine: RAGEngine, doc: Document) -> None:
    chunk_ids = [cid for (cid,) in db.execute(select(Chunk.id).where(Chunk.document_id == doc.id)).all()]
    engine.remove_chunks(chunk_ids)
    try:
        Path(doc.storage_path).unlink(missing_ok=True)
    except OSError:
        log.warning("Could not delete stored file %s", doc.storage_path)
    db.delete(doc)
    db.commit()


def reindex_document(db: Session, engine: RAGEngine, settings: Settings, doc: Document) -> Document:
    chunk_ids = [cid for (cid,) in db.execute(select(Chunk.id).where(Chunk.document_id == doc.id)).all()]
    engine.remove_chunks(chunk_ids)
    for chunk in list(doc.chunks):
        db.delete(chunk)
    doc.status = "processing"
    db.commit()
    _index(db, engine, settings, doc)
    db.commit()
    db.refresh(doc)
    return doc

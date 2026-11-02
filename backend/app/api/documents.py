"""Documents: upload (many at once), list, inspect chunks, download, delete, re-index. Plus sample documents."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_engine, settings_dep
from app.core.config import Settings
from app.db.database import get_db
from app.db.models import Chunk, Conversation, Document
from app.rag.engine import RAGEngine
from app.rag.loaders import SUPPORTED_EXTENSIONS, LoaderError
from app.schemas import ChunkOut, DocumentOut, UploadResult
from app.services.documents import delete_document, ingest_file, reindex_document

router = APIRouter(tags=["documents"])

SAMPLE_DESCRIPTIONS = {
    "HR_Policy_v7.pdf": "HR policy: leave, notice periods, remote work (PDF, 3 pages)",
    "Supplier_Agreement_2026.pdf": "Supply agreement: payment, termination, liability (PDF, 2 pages)",
    "Employment_Contract_Template.docx": "Employment contract template: probation, notice, confidentiality (Word)",
    "Returns_and_Warranty_FAQ.md": "Returns, refunds and warranty FAQ (Markdown)",
    "Price_List_Q3_2026.csv": "Product price list with SKUs and warranty months (CSV)",
    "Travel_and_Expenses_Policy.html": "Travel allowances, flights, mileage, claims (HTML)",
    "Delivery_Policy.txt": "Delivery times, charges and days (plain text)",
}


def _doc_or_404(db: Session, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@router.post("/documents", response_model=list[UploadResult])
def upload_documents(  # sync on purpose: indexing is CPU/IO bound and runs in FastAPI's threadpool
    files: list[UploadFile] = File(...),
    conversation_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    engine: RAGEngine = Depends(get_engine),
    settings: Settings = Depends(settings_dep),
):
    if conversation_id and db.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    results: list[UploadResult] = []
    limit = settings.max_upload_mb * 1024 * 1024
    for upload in files:
        name = upload.filename or "file"
        data = upload.file.read(limit + 1)
        try:
            doc, duplicate = ingest_file(db, engine, settings, filename=name, data=data, conversation_id=conversation_id)
            results.append(UploadResult(filename=name, document=DocumentOut.model_validate(doc), duplicate=duplicate))
        except LoaderError as exc:
            results.append(UploadResult(filename=name, error=str(exc)))
    return results


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    scope: str = Query(default="library", pattern="^(library|all)$"),
    db: Session = Depends(get_db),
):
    stmt = select(Document).order_by(Document.created_at.desc())
    if scope == "library":
        stmt = stmt.where(Document.conversation_id.is_(None))
    return db.scalars(stmt).all()


@router.get("/documents/supported-types")
def supported_types():
    return {"extensions": sorted(SUPPORTED_EXTENSIONS)}


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)):
    return _doc_or_404(db, document_id)


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut])
def get_chunks(document_id: str, db: Session = Depends(get_db)):
    _doc_or_404(db, document_id)
    return db.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)).all()


@router.get("/documents/{document_id}/file")
def download_document(document_id: str, download: bool = False, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    path = Path(doc.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="The original file is no longer stored.")
    return FileResponse(path, filename=doc.filename, content_disposition_type="attachment" if download else "inline")


@router.delete("/documents/{document_id}", status_code=204)
def remove_document(document_id: str, db: Session = Depends(get_db), engine: RAGEngine = Depends(get_engine)):
    delete_document(db, engine, _doc_or_404(db, document_id))


@router.post("/documents/{document_id}/reindex", response_model=DocumentOut)
def reindex(
    document_id: str,
    db: Session = Depends(get_db),
    engine: RAGEngine = Depends(get_engine),
    settings: Settings = Depends(settings_dep),
):
    return reindex_document(db, engine, settings, _doc_or_404(db, document_id))


# ------------------------------------------------------------------ sample documents
def _sample_path(settings: Settings, filename: str) -> Path:
    if filename not in SAMPLE_DESCRIPTIONS:
        raise HTTPException(status_code=404, detail="Sample not found.")
    path = settings.samples_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Sample file is missing. Run scripts/make_sample_docs.py.")
    return path


@router.get("/samples")
def list_samples(settings: Settings = Depends(settings_dep)):
    items = []
    for name, description in SAMPLE_DESCRIPTIONS.items():
        path = settings.samples_dir / name
        if path.exists():
            items.append({"filename": name, "description": description, "size_bytes": path.stat().st_size,
                          "file_type": SUPPORTED_EXTENSIONS[path.suffix.lower()]})
    return items


@router.get("/samples/archive")
def download_samples_zip(settings: Settings = Depends(settings_dep)):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in SAMPLE_DESCRIPTIONS:
            path = settings.samples_dir / name
            if path.exists():
                zf.write(path, arcname=name)
        if settings.golden_set_path.exists():
            zf.write(settings.golden_set_path, arcname="golden_set.json")
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="clause-sample-documents.zip"'}
    )


@router.get("/samples/{filename}")
def download_sample(filename: str, settings: Settings = Depends(settings_dep)):
    return FileResponse(_sample_path(settings, filename), filename=filename, content_disposition_type="attachment")


@router.post("/samples/import", response_model=list[UploadResult])
def import_samples(
    db: Session = Depends(get_db),
    engine: RAGEngine = Depends(get_engine),
    settings: Settings = Depends(settings_dep),
):
    """Add every sample document to the shared library (skips ones already added)."""
    results = []
    for name in SAMPLE_DESCRIPTIONS:
        path = settings.samples_dir / name
        if not path.exists():
            continue
        try:
            doc, duplicate = ingest_file(db, engine, settings, filename=name, data=path.read_bytes())
            results.append(UploadResult(filename=name, document=DocumentOut.model_validate(doc), duplicate=duplicate))
        except LoaderError as exc:
            results.append(UploadResult(filename=name, error=str(exc)))
    return results

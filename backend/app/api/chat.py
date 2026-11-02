"""Chat: ask (JSON or streamed NDJSON), conversations, feedback."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_engine, settings_dep
from app.core.config import Settings
from app.db.database import get_db, session_scope
from app.db.models import Conversation, Document, Message
from app.rag.engine import AnswerOutcome, EmbeddingError, RAGEngine
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    FeedbackIn,
    MessageOut,
)

router = APIRouter(tags=["chat"])
log = logging.getLogger(__name__)

MODEL_UNAVAILABLE = (
    "Clause could not reach its language model right now. Please try again in a moment. "
    "If this keeps happening, ask your admin to check the model settings."
)


def _title(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= 60 else text[:57].rstrip() + "…"


def _prepare(db: Session, req: ChatRequest, settings: Settings) -> tuple[Conversation, list[tuple[str, str]], set[str]]:
    if req.conversation_id:
        conv = db.get(Conversation, req.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
    else:
        conv = Conversation(title=_title(req.question))
        db.add(conv)
        db.flush()
    if conv.title == "New chat" and not conv.messages:
        conv.title = _title(req.question)
    history = [(m.role, m.content) for m in conv.messages][-2 * settings.history_turns :]
    chat_docs = {d.id for d in conv.documents if d.status == "ready"}
    if req.scope == "chat":
        allowed = chat_docs
    else:
        library = set(db.scalars(select(Document.id).where(Document.conversation_id.is_(None), Document.status == "ready")).all())
        allowed = library | chat_docs
    db.add(Message(conversation_id=conv.id, role="user", content=req.question))
    db.commit()
    return conv, history, allowed


def _save_answer(db: Session, conversation_id: str, outcome: AnswerOutcome) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=outcome.answer,
        sources=[s.public() for s in outcome.sources],
        meta=outcome.meta(),
    )
    db.add(msg)
    conv = db.get(Conversation, conversation_id)
    if conv is not None:
        conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(msg)
    return msg


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    engine: RAGEngine = Depends(get_engine),
    settings: Settings = Depends(settings_dep),
):
    conv, history, allowed = _prepare(db, req, settings)
    try:
        outcome = engine.answer(req.question, document_ids=allowed, history=history, strict=req.strict)
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=MODEL_UNAVAILABLE) from exc
    except Exception as exc:
        log.exception("Answer generation failed")
        raise HTTPException(status_code=503, detail=MODEL_UNAVAILABLE) from exc
    msg = _save_answer(db, conv.id, outcome)
    return ChatResponse(conversation_id=conv.id, title=conv.title, message=MessageOut.model_validate(msg), refused=outcome.refused)


@router.post("/chat/stream")
def chat_stream(
    req: ChatRequest,
    db: Session = Depends(get_db),
    engine: RAGEngine = Depends(get_engine),
    settings: Settings = Depends(settings_dep),
):
    """Newline-delimited JSON events: conversation, status, sources, token, done | error."""
    conv, history, allowed = _prepare(db, req, settings)
    conv_id, title = conv.id, conv.title

    def events() -> Iterator[bytes]:
        def line(obj: dict) -> bytes:
            return (json.dumps(obj, default=str) + "\n").encode("utf-8")

        yield line({"type": "conversation", "conversation_id": conv_id, "title": title})
        try:
            for event in engine.stream(req.question, document_ids=allowed, history=history, strict=req.strict):
                if event["type"] == "done":
                    outcome: AnswerOutcome = event["outcome"]
                    with session_scope() as session:  # own session: the request session may already be closed
                        msg = _save_answer(session, conv_id, outcome)
                        payload = MessageOut.model_validate(msg).model_dump(mode="json")
                    yield line({"type": "done", "message": payload, "refused": outcome.refused})
                else:
                    yield line(event)
        except Exception:
            log.exception("Streaming answer failed")
            yield line({"type": "error", "message": MODEL_UNAVAILABLE})

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    return db.scalars(select(Conversation).order_by(Conversation.updated_at.desc()).limit(100)).all()


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    conv = Conversation(title=body.title or "New chat")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conv


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db), engine: RAGEngine = Depends(get_engine)):
    from app.services.documents import delete_document

    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    for doc in list(conv.documents):  # files uploaded into a chat are private to it
        delete_document(db, engine, doc)
    db.delete(conv)
    db.commit()


@router.post("/messages/{message_id}/feedback", response_model=MessageOut)
def feedback(message_id: int, body: FeedbackIn, db: Session = Depends(get_db)):
    msg = db.get(Message, message_id)
    if msg is None or msg.role != "assistant":
        raise HTTPException(status_code=404, detail="Message not found.")
    msg.feedback = body.value or None
    db.commit()
    db.refresh(msg)
    return msg

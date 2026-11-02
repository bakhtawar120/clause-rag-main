"""Request and response models (the contract with the Next.js frontend)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    size_bytes: int
    status: str
    error: str | None = None
    pages: int | None = None
    chunk_count: int
    conversation_id: str | None = None
    created_at: datetime


class UploadResult(BaseModel):
    filename: str
    document: DocumentOut | None = None
    duplicate: bool = False
    error: str | None = None


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    text: str
    page: int | None = None
    section: str | None = None
    char_count: int


class SourceOut(BaseModel):
    n: int
    document_id: str
    filename: str
    file_type: str
    page: int | None = None
    section: str | None = None
    text: str
    highlight: str = ""
    cited: bool = False


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    scope: Literal["all", "chat"] = "all"
    strict: bool | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    sources: list[SourceOut] | None = None
    feedback: int | None = None
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: str
    title: str
    message: MessageOut
    refused: bool


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
    documents: list[DocumentOut]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class FeedbackIn(BaseModel):
    value: Literal[-1, 0, 1]


class RetrievalTestIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["hybrid", "vector", "keyword"] | None = None
    reranker: Literal["none", "lexical", "flashrank", "llm"] | None = None
    top_n: int | None = Field(default=None, ge=1, le=20)


class EvalRunIn(BaseModel):
    variants: list[Literal["vector", "keyword", "hybrid", "hybrid_rerank"]] = Field(
        default_factory=lambda: ["vector", "keyword", "hybrid", "hybrid_rerank"], min_length=1
    )
    generate: bool = True
    judge: bool = True
    limit: int | None = Field(default=None, ge=1)


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    variants: list[str]
    progress: int
    total: int
    summary: dict | None = None
    config: dict | None = None
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None

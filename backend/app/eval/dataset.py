"""Golden set loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class ExpectedSource(BaseModel):
    file: str
    contains: str


class GoldenQuestion(BaseModel):
    id: str
    category: str
    question: str
    reference: str
    answerable: bool = True
    expected_sources: list[ExpectedSource] = Field(default_factory=list)
    must_include: list[list[str]] = Field(default_factory=list)
    history: list[tuple[str, str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "GoldenQuestion":
        if self.answerable and not self.expected_sources:
            raise ValueError(f"{self.id}: answerable questions need at least one expected source")
        return self


class GoldenSet(BaseModel):
    version: int
    description: str = ""
    documents: list[str]
    questions: list[GoldenQuestion]

    @model_validator(mode="after")
    def _check(self) -> "GoldenSet":
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate question ids in the golden set")
        known = set(self.documents)
        for q in self.questions:
            for src in q.expected_sources:
                if src.file not in known:
                    raise ValueError(f"{q.id}: unknown document {src.file}")
        return self


def load_golden_set(path: Path) -> GoldenSet:
    return GoldenSet.model_validate(json.loads(path.read_text(encoding="utf-8")))

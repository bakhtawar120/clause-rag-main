"""Post-retrieval · context post-processing and citations.

- Removes near-duplicate passages (same text uploaded twice, overlapping chunks)
- Keeps the best passages within a character budget
- Numbers the passages [1], [2], ... for the prompt and the citations
- After generation: validates citation numbers and finds the sentence to highlight in each source
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.prompts import NOT_FOUND
from app.rag.text import content_tokens, jaccard, split_sentences

_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_REFUSAL_RE = re.compile(
    r"(couldn'?t|could not|can'?t|cannot|unable to) find|not (mentioned|covered|found|available) in (your|the) documents|"
    r"no information (about|on)",
    re.IGNORECASE,
)


@dataclass
class ChunkRecord:
    chunk_id: int
    document_id: str
    filename: str
    file_type: str
    text: str
    chunk_index: int = 0
    page: int | None = None
    section: str | None = None


@dataclass
class Source:
    n: int
    chunk: ChunkRecord
    score: float
    cited: bool = False
    highlight: str = ""
    debug: dict = field(default_factory=dict)

    def location(self) -> str:
        parts = []
        if self.chunk.page:
            parts.append(f"page {self.chunk.page}")
        if self.chunk.section:
            parts.append(self.chunk.section.split(" > ")[-1])
        return ", ".join(parts)

    def public(self) -> dict:
        """What the chat UI receives: no scores or internal ids beyond what it needs to link."""
        return {
            "n": self.n,
            "document_id": self.chunk.document_id,
            "filename": self.chunk.filename,
            "file_type": self.chunk.file_type,
            "page": self.chunk.page,
            "section": self.chunk.section.split(" > ")[-1] if self.chunk.section else None,
            "text": self.chunk.text,
            "highlight": self.highlight,
            "cited": self.cited,
        }


def select_context(candidates, chunks: dict[int, ChunkRecord], *, top_n: int, max_chars: int, min_score=None) -> list[Source]:
    selected: list[Source] = []
    used_chars = 0
    kept_tokens: list[set[str]] = []
    for cand in candidates:
        chunk = chunks.get(cand.chunk_id)
        if chunk is None:
            continue
        score = cand.rerank_score if cand.rerank_score is not None else cand.fused_score
        if min_score is not None and cand.rerank_score is not None and cand.rerank_score < min_score:
            continue
        tokens = content_tokens(chunk.text)
        if any(jaccard(tokens, prev) >= 0.9 for prev in kept_tokens):
            continue  # near-duplicate
        if selected and used_chars + len(chunk.text) > max_chars:
            continue
        kept_tokens.append(tokens)
        used_chars += len(chunk.text)
        selected.append(Source(n=len(selected) + 1, chunk=chunk, score=float(score), debug=cand.as_debug()))
        if len(selected) >= top_n:
            break
    return selected


def format_sources(sources: list[Source]) -> str:
    blocks = []
    for s in sources:
        where = f", {s.location()}" if s.location() else ""
        blocks.append(f"[{s.n}] ({s.chunk.filename}{where})\n{s.chunk.text}")
    return "\n\n".join(blocks)


def extract_citations(text: str) -> list[int]:
    seen: list[int] = []
    for group in _CITE_RE.findall(text):
        for part in group.split(","):
            n = int(part.strip())
            if n not in seen:
                seen.append(n)
    return seen


def sanitize_citations(text: str, valid: set[int]) -> str:
    """Drop citation numbers that point to no source, so the UI never shows a broken chip."""

    def fix(match: re.Match) -> str:
        nums = [p.strip() for p in match.group(1).split(",") if int(p.strip()) in valid]
        return "".join(f"[{n}]" for n in nums)

    cleaned = _CITE_RE.sub(fix, text)
    return re.sub(r"[ \t]+([.,;:])", r"\1", cleaned).strip()


def is_refusal(text: str) -> bool:
    return bool(_REFUSAL_RE.search(text)) or text.strip().startswith(NOT_FOUND[:20])


def best_highlight(source_text: str, claims: list[str]) -> str:
    """The sentence in the source that best supports the answer sentences citing it."""
    sentences = [s for line in source_text.splitlines() for s in split_sentences(line)]
    if not sentences:
        return ""
    claim_tokens = set().union(*(content_tokens(c) for c in claims)) if claims else set()
    if not claim_tokens:
        return sentences[0]
    return max(sentences, key=lambda s: len(content_tokens(s) & claim_tokens) / (1 + 0.02 * len(s)))


def attach_citations(answer: str, sources: list[Source]) -> tuple[str, list[Source]]:
    valid = {s.n for s in sources}
    answer = sanitize_citations(answer, valid)
    cited = set(extract_citations(answer))
    sentences = split_sentences(answer)
    for s in sources:
        s.cited = s.n in cited
        claims = [sent for sent in sentences if f"[{s.n}]" in sent]
        s.highlight = best_highlight(s.chunk.text, claims or [answer])
    return answer, sources

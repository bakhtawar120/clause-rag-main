"""Indexing · step 3: structure-aware chunking.

1. Detect headings (Markdown "#", numbered headings like "6.1 Notice periods", short ALL-CAPS lines)
   and track the current section across pages.
2. Split each section with LangChain's RecursiveCharacterTextSplitter (paragraph -> line -> sentence -> word),
   with overlap, so every chunk stays inside one section and one page.
3. Keep metadata (page, section) for citations, and build a "contextual header"
   ("HR_Policy_v7.pdf > 6. Notice > 6.1 Notice periods") that is embedded with the chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.loaders import PageText

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_NUM_HEADING = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s+([A-Z][^\n]{1,80})$")
_CAPS_HEADING = re.compile(r"^[A-Z][A-Z0-9 &/,'()-]{3,60}$")


@dataclass
class ChunkDraft:
    text: str
    chunk_index: int
    page: int | None
    section: str | None


def _heading(line: str) -> tuple[int, str] | None:
    """Return (level, title) when the line looks like a heading."""
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return None
    match = _MD_HEADING.match(stripped)
    if match:
        return len(match.group(1)), match.group(2).strip()
    match = _NUM_HEADING.match(stripped)
    if match and not stripped.endswith((".", ",", ";", ":")):
        number = match.group(1)
        # Real numbered headings are short; a numbered list item with a long sentence is not a heading.
        if len(stripped.split()) <= 9:
            return number.count(".") + 1, stripped
    if _CAPS_HEADING.match(stripped) and len(stripped.split()) <= 6 and not stripped.isdigit():
        return 1, stripped.title()
    return None


def _is_label(lines: list[str]) -> bool:
    """A lone short line with no sentence punctuation (a title or label), not real content."""
    return len(lines) == 1 and len(lines[0]) < 100 and not lines[0].rstrip().endswith((".", "!", "?", ":"))


def _sections(pages: list[PageText]):
    """Yield (page, section_path, text) blocks, carrying the section across page breaks.

    Heading-only blocks and lone title lines are not emitted on their own: they are carried
    forward and prepended to the next block, so no chunk is just a heading.
    """
    path: list[tuple[int, str]] = []
    carry: list[str] = []  # headings / labels waiting for content
    for page in pages:
        heading_lines: list[str] = []
        content_lines: list[str] = []

        def flush():
            nonlocal carry
            content = [ln for ln in content_lines if ln.strip()]
            if not content or _is_label(content):
                carry = carry + heading_lines + content
            else:
                body = "\n".join(carry + heading_lines + content_lines).strip()
                carry = []
                yield page.page, " > ".join(title for _, title in path) or None, body
            heading_lines.clear()
            content_lines.clear()

        for line in page.text.splitlines():
            heading = _heading(line)
            if heading:
                if content_lines:
                    yield from flush()
                level, title = heading
                path = [(lvl, t) for lvl, t in path if lvl < level] + [(level, title)]
                heading_lines.append(title)  # keep the heading text inside the chunk too
            else:
                content_lines.append(line)
        yield from flush()
    if carry:  # trailing labels with nothing after them
        yield pages[-1].page if pages else None, " > ".join(t for _, t in path) or None, "\n".join(carry)


def chunk_pages(pages: list[PageText], chunk_size: int = 900, chunk_overlap: int = 150) -> list[ChunkDraft]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
        keep_separator="end",
        strip_whitespace=True,
    )
    drafts: list[ChunkDraft] = []
    for page, section, body in _sections(pages):
        for piece in splitter.split_text(body):
            piece = piece.strip()
            if len(piece) < 20 and drafts and drafts[-1].section == section and drafts[-1].page == page:
                drafts[-1].text = f"{drafts[-1].text}\n{piece}"  # glue tiny tails to the previous chunk
                continue
            if not piece:
                continue
            drafts.append(ChunkDraft(text=piece, chunk_index=len(drafts), page=page, section=section))
    return drafts


def contextual_text(filename: str, section: str | None, text: str) -> str:
    """What we embed: the chunk plus where it lives, so short chunks keep their meaning."""
    header = f"{filename} > {section}" if section else filename
    return f"{header}\n{text}"

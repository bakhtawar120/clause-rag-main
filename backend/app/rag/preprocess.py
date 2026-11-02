"""Indexing · step 2: data pre-processing.

Cleans extracted text before chunking:
- Unicode normalisation (NFKC), non-breaking spaces, ligatures
- Re-joins words hyphenated across line breaks ("employ-\\nment" -> "employment")
- Removes running headers/footers repeated on most PDF pages, and "Page 3 of 10" lines
- Collapses runs of spaces and blank lines
"""

from __future__ import annotations

import re
from collections import Counter

from app.rag.loaders import PageText
from app.rag.text import normalize

_PAGE_NUMBER_RE = re.compile(r"^\s*(page\s*)?\d+(\s*(of|/)\s*\d+)?\s*$", re.IGNORECASE)
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")


def _reflow(lines: list[str]) -> list[str]:
    """Join lines that were wrapped mid-sentence (PDFs break lines at the page width)."""
    out: list[str] = []
    for line in lines:
        if (
            out
            and line
            and out[-1]
            and not out[-1].endswith((".", "!", "?", ":", ";"))
            and (line[0].islower() or line[0] in "(,")
        ):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def clean_text(text: str) -> str:
    text = normalize(text).replace(" ", " ").replace("­", "")
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = _reflow([line.strip() for line in text.splitlines()])
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _repeated_lines(pages: list[PageText], min_share: float = 0.6) -> set[str]:
    """Lines that appear on most pages are headers/footers, not content."""
    if len(pages) < 2:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        seen = {line.strip() for line in page.text.splitlines() if line.strip()}
        counts.update(seen)
    # Short documents: a line must repeat on every page. Longer ones: on most pages.
    threshold = len(pages) if len(pages) < 4 else max(2, int(len(pages) * min_share))
    return {line for line, count in counts.items() if count >= threshold and len(line) < 120}


def preprocess(pages: list[PageText]) -> list[PageText]:
    repeated = _repeated_lines(pages)
    cleaned: list[PageText] = []
    for page in pages:
        kept = [
            line
            for line in page.text.splitlines()
            if line.strip() not in repeated and not _PAGE_NUMBER_RE.match(line)
        ]
        text = clean_text("\n".join(kept))
        if text:
            cleaned.append(PageText(text=text, page=page.page, metadata=dict(page.metadata)))
    return cleaned

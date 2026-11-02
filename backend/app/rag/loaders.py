"""Indexing · step 1: read files into page-level text with metadata.

Supported: PDF, Word (.docx), Markdown, plain text, CSV, HTML.
Headings are converted to Markdown-style "#" lines so the chunker can follow document structure.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".csv": "csv",
    ".html": "html",
    ".htm": "html",
}

CSV_ROWS_PER_PAGE = 25


class LoaderError(Exception):
    """A file could not be read. The message is shown to users, so keep it plain."""


@dataclass
class PageText:
    text: str
    page: int | None = None  # 1-based page number when the format has pages
    metadata: dict = field(default_factory=dict)


def file_type_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted({e.lstrip(".") for e in SUPPORTED_EXTENSIONS}))
        raise LoaderError(f"This file type is not supported. Supported types: {allowed}.")
    return SUPPORTED_EXTENSIONS[ext]


def load_file(path: Path, filename: str | None = None) -> list[PageText]:
    filename = filename or path.name
    kind = file_type_for(filename)
    data = path.read_bytes()
    if not data:
        raise LoaderError("The file is empty.")
    loader = {
        "pdf": _load_pdf,
        "docx": _load_docx,
        "markdown": _load_text,
        "text": _load_text,
        "csv": _load_csv,
        "html": _load_html,
    }[kind]
    pages = loader(data)
    pages = [p for p in pages if p.text and p.text.strip()]
    if not pages:
        raise LoaderError(
            "No readable text was found. If this is a scanned document, it needs OCR, which is not enabled yet."
        )
    return pages


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise LoaderError("The text encoding of this file could not be read.")


def _load_pdf(data: bytes) -> list[PageText]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise LoaderError("This PDF could not be opened. It may be damaged.") from exc
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise LoaderError("This PDF is password-protected. Upload an unlocked copy.")
        except Exception as exc:  # wrong/no password or unsupported encryption
            raise LoaderError("This PDF is password-protected. Upload an unlocked copy.") from exc
    pages: list[PageText] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # a single broken page should not fail the whole document
            text = ""
        pages.append(PageText(text=text, page=number))
    return pages


def _load_docx(data: bytes) -> list[PageText]:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(io.BytesIO(data))
    except (PackageNotFoundError, KeyError, ValueError) as exc:
        raise LoaderError("This Word file could not be opened. It may be damaged.") from exc

    lines: list[str] = []
    for block in document.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = docx.text.paragraph.Paragraph(block, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            if style.lower().startswith("heading"):
                level = "".join(ch for ch in style if ch.isdigit()) or "1"
                lines.append(f"{'#' * min(int(level), 6)} {text}")
            elif style.lower() == "title":
                lines.append(f"# {text}")
            else:
                lines.append(text)
        elif tag == "tbl":
            table = docx.table.Table(block, document)
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
    return [PageText(text="\n\n".join(lines), page=None)]


def _load_text(data: bytes) -> list[PageText]:
    return [PageText(text=_decode(data), page=None)]


def _load_csv(data: bytes) -> list[PageText]:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise LoaderError("This CSV file has no data rows.")
    header = [h.strip() or f"Column {i + 1}" for i, h in enumerate(rows[0])]
    pages: list[PageText] = []
    body = rows[1:]
    for start in range(0, len(body), CSV_ROWS_PER_PAGE):
        group = body[start : start + CSV_ROWS_PER_PAGE]
        lines = []
        for offset, row in enumerate(group):
            pairs = [f"{header[i]}: {row[i].strip()}" for i in range(min(len(header), len(row))) if row[i].strip()]
            lines.append(f"Row {start + offset + 1}. " + "; ".join(pairs) + ".")
        first, last = start + 1, start + len(group)
        pages.append(
            PageText(text=f"# Rows {first}-{last}\n\n" + "\n\n".join(lines), page=None, metadata={"rows": [first, last]})
        )
    return pages


def _load_html(data: bytes) -> list[PageText]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_decode(data), "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    lines: list[str] = []
    for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "pre"]):
        text = " ".join(element.get_text(" ", strip=True).split())
        if not text:
            continue
        if element.name in ("h1", "h2", "h3", "h4"):
            lines.append(f"{'#' * int(element.name[1])} {text}")
        elif element.name == "li":
            lines.append(f"- {text}")
        elif element.name in ("td", "th"):
            continue  # handled per row below
        else:
            lines.append(text)
    for row in soup.find_all("tr"):
        cells = [" ".join(c.get_text(" ", strip=True).split()) for c in row.find_all(["td", "th"])]
        if any(cells):
            lines.append(" | ".join(cells))
    return [PageText(text="\n\n".join(lines), page=None)]

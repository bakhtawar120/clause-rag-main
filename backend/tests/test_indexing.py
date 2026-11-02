"""Indexing stage: loaders, pre-processing, chunking."""

import io

import pytest
from pypdf import PdfWriter

from app.rag.chunking import chunk_pages, contextual_text
from app.rag.loaders import LoaderError, PageText, file_type_for, load_file
from app.rag.preprocess import clean_text, preprocess
from app.rag.text import stem, tokenize


# ---------------------------------------------------------------- text utilities
def test_tokenize_keeps_codes_and_parts():
    tokens = tokenize("Price of SKU-4471 and the 65W USB-C charger: 24,999 PKR")
    assert "sku-4471" in tokens and "4471" in tokens
    assert "usb-c" in tokens
    assert "24,999" in tokens


@pytest.mark.parametrize("a,b", [("invoices", "invoice"), ("approved", "approve"), ("policies", "policy"), ("refunds", "refund")])
def test_stemming_matches_word_forms(a, b):
    assert stem(a) == stem(b)


# ---------------------------------------------------------------- loaders
def test_every_sample_document_loads(sample_files):
    assert len(sample_files) == 7
    for path in sample_files:
        pages = load_file(path)
        assert pages and all(p.text.strip() for p in pages), path.name


def test_pdf_pages_are_numbered(sample_files):
    pdf = next(p for p in sample_files if p.name == "HR_Policy_v7.pdf")
    pages = load_file(pdf)
    assert [p.page for p in pages] == [1, 2, 3]


def test_docx_headings_become_markdown(sample_files):
    docx = next(p for p in sample_files if p.suffix == ".docx")
    text = load_file(docx)[0].text
    assert "# 9. Notice" in text


def test_csv_rows_keep_their_headers(sample_files):
    csv_file = next(p for p in sample_files if p.suffix == ".csv")
    text = load_file(csv_file)[0].text
    assert "SKU: SKU-4471; Product: X200 Wireless Headphones; Price (PKR): 24,999" in text


def test_html_drops_navigation_and_keeps_headings(sample_files):
    html = next(p for p in sample_files if p.suffix == ".html")
    text = load_file(html)[0].text
    assert "## Personal car" in text
    assert "intranet" not in text  # <header> removed


def test_unsupported_type_is_rejected():
    with pytest.raises(LoaderError, match="not supported"):
        file_type_for("malware.exe")


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    with pytest.raises(LoaderError, match="empty"):
        load_file(path)


def test_password_protected_pdf_is_reported(tmp_path, sample_files):
    source = next(p for p in sample_files if p.name == "Supplier_Agreement_2026.pdf")
    writer = PdfWriter(clone_from=str(source))
    writer.encrypt(user_password="secret", owner_password="owner")
    locked = tmp_path / "locked.pdf"
    buffer = io.BytesIO()
    writer.write(buffer)
    locked.write_bytes(buffer.getvalue())
    with pytest.raises(LoaderError, match="password-protected"):
        load_file(locked)


# ---------------------------------------------------------------- pre-processing
def test_clean_text_fixes_hyphenation_and_wrapped_lines():
    assert clean_text("employ-\nment rules") == "employment rules"
    assert clean_text("paid annual leave per year, in addition\nto public holidays.") == (
        "paid annual leave per year, in addition to public holidays."
    )


def test_repeated_headers_and_page_numbers_are_removed():
    pages = [PageText(text=f"Acme Inc. Confidential\nBody text {i}.\nPage {i} of 3", page=i) for i in (1, 2, 3)]
    cleaned = preprocess(pages)
    assert all("Confidential" not in p.text and "Page" not in p.text for p in cleaned)
    assert cleaned[0].text == "Body text 1."


# ---------------------------------------------------------------- chunking
def test_chunks_follow_sections_and_pages(sample_files):
    pdf = next(p for p in sample_files if p.name == "HR_Policy_v7.pdf")
    chunks = chunk_pages(preprocess(load_file(pdf)), 900, 150)
    notice = next(c for c in chunks if "thirty (30) days" in c.text)
    assert notice.page == 2
    assert notice.section == "6. Notice > 6.1 Notice periods"
    lieu = next(c for c in chunks if "HR Director" in c.text)
    assert lieu.page == 3 and lieu.section.endswith("6.4 Payment in lieu of notice")


def test_no_chunk_is_only_a_heading(sample_files):
    for path in sample_files:
        for c in chunk_pages(preprocess(load_file(path)), 900, 150):
            lines = [ln for ln in c.text.splitlines() if ln.strip()]
            assert len(lines) >= 2 or len(c.text) > 80, (path.name, c.text)


def test_long_sections_are_split_with_overlap():
    sentences = " ".join(f"Sentence number {i} explains rule {i} in detail." for i in range(120))
    pages = [PageText(text=f"# Rules\n{sentences}", page=1)]
    chunks = chunk_pages(pages, chunk_size=400, chunk_overlap=80)
    assert len(chunks) > 3
    assert all(len(c.text) <= 400 + 20 for c in chunks)
    assert all(c.section == "Rules" for c in chunks)
    # overlap: the end of one chunk reappears at the start of the next
    assert any(chunks[i].text[-30:].split()[-1] in chunks[i + 1].text[:120] for i in range(len(chunks) - 1))


def test_contextual_header():
    assert contextual_text("HR.pdf", "6. Notice", "Body").startswith("HR.pdf > 6. Notice\n")

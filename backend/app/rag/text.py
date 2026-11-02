"""Small, dependency-free text utilities shared by keyword search, reranking and evaluation."""

from __future__ import annotations

import re
import unicodedata

# Keeps product codes and numbers intact: "sku-4471", "usb-c", "1.5", "24,999"
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-.,][a-z0-9]+)*")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])")

STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does doing for from had has have having he her
    here hers him his how i if in into is it its itself just me more most my no nor not of off on once only or
    other our ours out over own same she should so some such than that the their theirs them then there these
    they this those through to too under until up very was we were what when where which while who whom why
    will with would you your yours about above after again against all am any because before below between
    both during each few further also may must shall per via within without upon whether please tell explain
    much many get got give gives given know let lets make makes need needs say says use used using like
    """.split()
)

# Words that appear in almost every business document: they should not count as evidence on their own.
GENERIC_WORDS = frozenset(
    "policy policies company acme inc document documents staff employee employees customer customers".split()
)

_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def stem(token: str) -> str:
    """A tiny, predictable suffix stripper (good enough for keyword matching).

    Plural and past forms map to the same stem as the base word:
    invoices/invoice -> invoice, boxes -> box, policies -> policy, approved/approve -> approv.
    """
    if token.isdigit() or len(token) <= 3 or any(ch.isdigit() for ch in token):
        return token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)] + ("y" if suffix in ("ies", "ied") else "")
    if token.endswith(("ches", "shes", "sses", "xes", "zes")):
        token = token[:-2]
    elif token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    elif token.endswith("ed") and len(token) > 5:
        token = token[:-2] if not token.endswith("eed") else token
    if token.endswith("e") and len(token) > 4:
        token = token[:-1]  # approve / approved / approves -> approv
    return token


def tokenize(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Lowercase, keep codes whole and also index their parts ("sku-4471" -> sku-4471, sku, 4471)."""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(normalize(text).lower()):
        raw = raw.strip(".,")
        if not raw:
            continue
        parts = [raw]
        if "-" in raw:
            parts.extend(p for p in raw.split("-") if p)
        for part in parts:
            if drop_stopwords and part in STOPWORDS:
                continue
            out.append(stem(part))
    return out


def content_tokens(text: str) -> set[str]:
    """Distinct meaningful tokens (no stopwords, no generic business words)."""
    generic = {stem(w) for w in GENERIC_WORDS}
    return {t for t in tokenize(text) if t not in generic}


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def squash(text: str) -> str:
    """Lowercase + collapse whitespace, for robust substring matching."""
    return re.sub(r"\s+", " ", normalize(text)).strip().lower()

"""Vector store: FAISS today, pgvector later.

`VectorStore` is the small interface the engine depends on. `FaissVectorStore` implements it with an
exact inner-product index over L2-normalised vectors, so scores are cosine similarities in [-1, 1].
A `PgVectorStore` only needs these six methods (add/delete/search/count/reset/save).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

import faiss
import numpy as np


class VectorStore(Protocol):
    def add(self, ids: list[int], vectors: np.ndarray) -> None: ...
    def delete(self, ids: Iterable[int]) -> None: ...
    def search(self, vector: np.ndarray, k: int, allowed_ids: set[int] | None = None) -> list[tuple[int, float]]: ...
    def count(self) -> int: ...
    def reset(self, signature: str | None = None) -> None: ...
    def save(self) -> None: ...


class FaissVectorStore:
    INDEX_FILE = "faiss.index"
    META_FILE = "faiss_meta.json"

    def __init__(self, path: Path | None = None, signature: str | None = None):
        """path=None keeps everything in memory (used by evaluation runs and tests)."""
        self.path = path
        self.signature = signature
        self.dim: int | None = None
        self._index: faiss.IndexIDMap2 | None = None
        self._lock = threading.RLock()
        if path is not None:
            path.mkdir(parents=True, exist_ok=True)
            self._load()

    # ---------- persistence
    def _load(self) -> None:
        assert self.path is not None
        index_file, meta_file = self.path / self.INDEX_FILE, self.path / self.META_FILE
        if index_file.exists() and meta_file.exists():
            meta = json.loads(meta_file.read_text())
            self._index = faiss.read_index(str(index_file))
            self.dim = meta.get("dim")
            self.stored_signature = meta.get("signature")
        else:
            self.stored_signature = None

    def save(self) -> None:
        if self.path is None:
            return
        with self._lock:
            meta = {"signature": self.signature, "dim": self.dim, "count": self.count()}
            if self._index is not None:
                faiss.write_index(self._index, str(self.path / self.INDEX_FILE))
            (self.path / self.META_FILE).write_text(json.dumps(meta, indent=2))
            self.stored_signature = self.signature

    def signature_matches(self) -> bool:
        """False when the saved index was built with a different embedding model."""
        return self.path is None or self.stored_signature in (None, self.signature)

    # ---------- operations
    def _ensure(self, dim: int) -> faiss.IndexIDMap2:
        if self._index is None:
            self.dim = dim
            self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        elif dim != self.dim:
            raise ValueError(f"Embedding size changed from {self.dim} to {dim}; rebuild the index.")
        return self._index

    @staticmethod
    def _prep(vectors: np.ndarray) -> np.ndarray:
        arr = np.ascontiguousarray(np.asarray(vectors, dtype=np.float32))
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        faiss.normalize_L2(arr)
        return arr

    def add(self, ids: list[int], vectors: np.ndarray) -> None:
        if not ids:
            return
        arr = self._prep(vectors)
        with self._lock:
            index = self._ensure(arr.shape[1])
            index.add_with_ids(arr, np.asarray(ids, dtype=np.int64))

    def delete(self, ids: Iterable[int]) -> None:
        id_list = list(ids)
        with self._lock:
            if self._index is not None and id_list:
                self._index.remove_ids(np.asarray(id_list, dtype=np.int64))

    def search(self, vector: np.ndarray, k: int, allowed_ids: set[int] | None = None) -> list[tuple[int, float]]:
        with self._lock:
            if self._index is None or self._index.ntotal == 0 or k <= 0:
                return []
            if allowed_ids is not None and not allowed_ids:
                return []
            query = self._prep(vector)
            # Metadata filter: exact search over everything, then keep allowed ids (flat index, so cost is the same).
            fetch = self._index.ntotal if allowed_ids is not None else min(k, self._index.ntotal)
            scores, ids = self._index.search(query, fetch)
        hits: list[tuple[int, float]] = []
        for score, idx in zip(scores[0], ids[0]):
            if idx == -1:
                continue
            if allowed_ids is not None and int(idx) not in allowed_ids:
                continue
            hits.append((int(idx), float(score)))
            if len(hits) >= k:
                break
        return hits

    def count(self) -> int:
        return 0 if self._index is None else int(self._index.ntotal)

    def reset(self, signature: str | None = None) -> None:
        with self._lock:
            self._index = None
            self.dim = None
            if signature is not None:
                self.signature = signature

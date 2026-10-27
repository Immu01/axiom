"""Swap-friendly vector storage interface backed by owner-scoped SQLite."""
from typing import Protocol

import store


class VectorStore(Protocol):
    def add_chunks(self, owner: str, doc_id: str, chunks: list[dict]) -> int: ...
    def search(
        self,
        owner: str,
        query: str,
        query_vector: list[float] | None,
        n: int = 6,
        doc_ids: list[str] | None = None,
    ) -> list[dict]: ...


class SQLiteVectorStore:
    def add_chunks(self, owner: str, doc_id: str, chunks: list[dict]) -> int:
        return store.add_pdf_chunks(owner, doc_id, chunks)

    def search(
        self,
        owner: str,
        query: str,
        query_vector: list[float] | None,
        n: int = 6,
        doc_ids: list[str] | None = None,
    ) -> list[dict]:
        return store.pdf_hybrid_search(owner, query, query_vector, n, doc_ids)


vector_store: VectorStore = SQLiteVectorStore()

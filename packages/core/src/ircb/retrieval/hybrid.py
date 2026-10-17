"""Hybrid retrieval primitives: Context, deps, chunk search and fact lookup (spec §5.10)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from ircb.domain.models import Chunk, Fact
from ircb.retrieval.glossary_expand import expand_query
from ircb.retrieval.sparse_bm25 import SparseVec, encode_query
from ircb.retrieval.tokenize_vi import tokenize
from ircb.storage.vector_store import Hit, Kind

FACT_OVERFETCH = 4


class StoreLike(Protocol):
    def hybrid(
        self, kind: Kind, dense: list[float], sparse: SparseVec, flt: dict[str, Any] | None, limit: int
    ) -> list[Hit]: ...


class SqlLike(Protocol):
    def get_many(self, ids: list[str]) -> dict[str, Fact]: ...


class EmbedderLike(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class RetrievalDeps:
    store: StoreLike
    sql: SqlLike
    embedder: EmbedderLike
    glossary: dict[str, list[str]] = field(default_factory=dict)
    doc_id: str = "tcb-ar-2025"
    top_k: int = 8


@dataclass
class Context:
    chunks: list[Chunk] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    chunk_hits: list[Hit] = field(default_factory=list)
    fact_hits: list[Hit] = field(default_factory=list)
    # top-1 hit of every branch (general, table, glossary, each fact lookup), independent of display order
    gate_hits: list[Hit] = field(default_factory=list)
    # SQL facts extracted from the chunks the answer cites; the verifier reads a cited chunk's own
    # facts (value, period, direction) as part of that chunk. Never shown to the generator.
    chunk_facts: list[Fact] = field(default_factory=list)


def sparse_for(text: str, glossary: dict[str, list[str]]) -> SparseVec:
    return encode_query(tokenize(expand_query(text, glossary)))


def search_chunks(
    deps: RetrievalDeps, dense: list[float], text: str, extra_filter: dict[str, Any] | None = None
) -> list[Hit]:
    flt: dict[str, Any] = {"doc_id": deps.doc_id, **(extra_filter or {})}
    return deps.store.hybrid("chunks", dense, sparse_for(text, deps.glossary), flt, deps.top_k)


class StalePayloadError(ValueError):
    """A chunk point whose payload cannot be rebuilt into a Chunk (loaded by an older loader)."""


def chunk_from_hit(hit: Hit) -> Chunk:
    try:
        return Chunk.model_validate(hit.payload)
    except ValidationError as exc:
        raise StalePayloadError(
            f"chunk {hit.id!r} has an incomplete Qdrant payload; run `ircb index load --force`"
        ) from exc


def period_matches(fact_period: str | None, period: str) -> bool:
    """A year such as "2025" matches fact periods "FY2025" and "2025-12-31"; others match exactly."""
    if not fact_period:
        return False
    if re.fullmatch(r"\d{4}", period):
        return fact_period.startswith((f"FY{period}", f"{period}-")) or fact_period == period
    return fact_period == period


class FactLookup:
    """Hybrid search over the ``facts`` collection; numeric values always come from SQL.

    A single Qdrant MatchValue cannot OR "FY2025" with "2025-12-31", so no period filter is sent:
    over-fetch, then keep only hits whose payload period matches the requested one.
    """

    def __init__(
        self,
        store: StoreLike,
        sql: SqlLike,
        embedder: EmbedderLike,
        glossary: dict[str, list[str]] | None = None,
        doc_id: str = "tcb-ar-2025",
    ) -> None:
        self.store, self.sql, self.embedder = store, sql, embedder
        self.glossary = glossary or {}
        self.doc_id = doc_id

    def lookup_hits(
        self,
        metric: str,
        period: str | None,
        statement: str | None = None,
        k: int = 3,
        dense: list[float] | None = None,
    ) -> tuple[list[Hit], list[Fact]]:
        if dense is None:
            dense = self.embedder.embed([metric])[0]
        flt: dict[str, Any] = {"doc_id": self.doc_id}
        if statement:
            flt["statement"] = statement
        sparse = sparse_for(f"{metric} {period}" if period else metric, self.glossary)
        hits = self.store.hybrid("facts", dense, sparse, flt, k * FACT_OVERFETCH if period else k)
        if period:
            hits = [h for h in hits if period_matches(h.payload.get("period"), period)]
        hits = hits[:k]
        by_id = self.sql.get_many([h.id for h in hits])
        kept = [h for h in hits if h.id in by_id]
        return kept, [by_id[h.id] for h in kept]

    def lookup(
        self,
        metric: str,
        period: str | None,
        statement: str | None = None,
        k: int = 3,
        dense: list[float] | None = None,
    ) -> list[Fact]:
        return self.lookup_hits(metric, period, statement, k, dense)[1]

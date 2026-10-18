"""Qdrant hybrid store (spec §4.3, §5.10): named dense + BM25 sparse vectors fused with RRF."""

from __future__ import annotations

import uuid
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from qdrant_client import QdrantClient, models

from ircb.retrieval.sparse_bm25 import SparseVec
from ircb.settings import Settings

Kind = Literal["chunks", "facts"]
PREFETCH_LIMIT = 30

_KEYWORD_INDEXES = ("doc_id", "content_type", "statement", "chapter")


_LOCAL_NOOP = (
    r"Payload indexes have no effect in the local Qdrant.*",
    r"Local mode performs exact \(brute-force\) search.*",
)


@dataclass
class Hit:
    id: str
    score: float
    dense_score: float | None
    branches: int
    payload: dict[str, Any] = field(default_factory=dict)


# RRF scores of symmetric ranks tie exactly; embedded Qdrant returns them as float64 and the
# server as float32 (0.333333333 vs 0.33333334), and each breaks ties in its own order.
SCORE_DECIMALS = 6


def rank_fused(hits: list[Hit], limit: int) -> list[Hit]:
    """Mode-independent order: score (rounded past float32 noise) descending, then id."""
    return sorted(hits, key=lambda h: (-round(h.score, SCORE_DECIMALS), h.id))[:limit]


# Qdrant's RRF constant: a point ranked r (from 1) in a branch adds 1 / (RRF_K + r)
RRF_K = 1
# extra points fetched per branch so a tie at the PREFETCH_LIMIT cut is resolved by id, not engine
TIE_MARGIN = 10
# branch scores (cosine, BM25) closer than 1e-4 count as tied: float32 (server) and float64
# (embedded) scores of near-identical chunks differ around 1e-7 and flipped their order
BRANCH_SCORE_DECIMALS = 4


def _point_key(p: Any, id_key: str) -> str:
    return str((p.payload or {}).get(id_key, p.id))


def top_of_branch(points: list[Any], id_key: str, limit: int) -> list[Any]:
    """One branch's top ``limit`` in a mode-independent order (rounded score desc, then id)."""

    def order(p: Any) -> tuple[float, str]:
        return -round(float(p.score), BRANCH_SCORE_DECIMALS), _point_key(p, id_key)

    return sorted(points, key=order)[:limit]


def fuse_rrf(branches: list[list[str]]) -> dict[str, float]:
    """Reciprocal rank fusion over ranked id lists."""
    scores: dict[str, float] = {}
    for ids in branches:
        for rank, key in enumerate(ids, start=1):
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_K + rank)
    return scores


def point_id(original_id: str) -> str:
    """Deterministic Qdrant point id (UUIDv5) derived from a chunk_id / fact_id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, original_id))


class QdrantStore:
    def __init__(self, settings: Settings) -> None:
        self._prefix = settings.qdrant_collection_prefix
        self._embedded = settings.qdrant_mode != "server"
        self._settings = settings
        self._client = self._open()

    def _open(self) -> QdrantClient:
        s = self._settings
        if s.qdrant_mode == "server":
            return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)
        Path(s.qdrant_path).mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=s.qdrant_path)

    @contextmanager
    def _quiet(self) -> Iterator[None]:
        """Embedded mode warns that payload indexes / search_params are no-ops; silence just those."""
        with warnings.catch_warnings():
            if self._embedded:
                for msg in _LOCAL_NOOP:
                    warnings.filterwarnings("ignore", message=msg, category=UserWarning)
            yield

    def reset_collections(self, dim: int) -> None:
        """Empty both collections (used when a new index version replaces the old one).

        Points are deleted rather than dropping the collection: embedded Qdrant keeps the old
        points when a deleted collection is recreated at the same path.
        """
        if self.dense_dim() not in (None, dim):
            self.recreate_collections(dim)  # a different dimension cannot be reused by emptying
        self.ensure_collections(dim)
        for kind in ("chunks", "facts"):
            self._client.delete(
                self._name(kind),
                points_selector=models.FilterSelector(filter=models.Filter()),
                wait=True,
            )

    def dense_dim(self) -> int | None:
        """Dense vector size of the existing collections (None when absent)."""
        kinds: tuple[Kind, Kind] = ("chunks", "facts")
        for kind in kinds:
            name = self._name(kind)
            if not self._client.collection_exists(name):
                continue
            vectors = self._client.get_collection(name).config.params.vectors
            if isinstance(vectors, dict) and "dense" in vectors:
                return int(vectors["dense"].size)
        return None

    def recreate_collections(self, dim: int) -> None:
        """Drop both collections and create them again with dense size ``dim``.

        Embedded Qdrant can keep the old collection after a delete (points and vector config), so
        points are emptied first and the client is closed and reopened before recreating. The
        result is verified; a stale dimension or leftover points raise ``RuntimeError``.
        """
        kinds: tuple[Kind, Kind] = ("chunks", "facts")
        for kind in kinds:
            name = self._name(kind)
            if self._client.collection_exists(name):
                self._client.delete(
                    name, points_selector=models.FilterSelector(filter=models.Filter()), wait=True
                )
                self._client.delete_collection(name)
        if self._embedded:
            self._client.close()
            self._client = self._open()
            for kind in kinds:  # a reopened client may still see the old collection
                if self._client.collection_exists(self._name(kind)):
                    self._client.delete_collection(self._name(kind))
        self.ensure_collections(dim)
        if self.dense_dim() != dim or self.count("chunks") or self.count("facts"):
            raise RuntimeError(f"could not recreate collections with dense dimension {dim}")

    def close(self) -> None:
        self._client.close()

    def _name(self, kind: Kind) -> str:
        return f"{self._prefix}{kind}"

    def ensure_collections(self, dim: int) -> None:
        kinds: tuple[Kind, Kind] = ("chunks", "facts")
        for kind in kinds:
            name = self._name(kind)
            if self._client.collection_exists(name):
                continue
            self._client.create_collection(
                collection_name=name,
                vectors_config={"dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)},
                sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )
            with self._quiet():
                for key in _KEYWORD_INDEXES:
                    self._client.create_payload_index(name, key, models.PayloadSchemaType.KEYWORD)
                if kind == "chunks":
                    self._client.create_payload_index(name, "printed_pages", models.PayloadSchemaType.INTEGER)

    def upsert(
        self,
        kind: Kind,
        ids: list[str],
        dense: list[list[float]],
        sparse: list[SparseVec],
        payloads: list[dict[str, Any]],
    ) -> None:
        id_key = "chunk_id" if kind == "chunks" else "fact_id"
        points = [
            models.PointStruct(
                id=point_id(i),
                vector={
                    "dense": [float(x) for x in d],
                    "bm25": models.SparseVector(indices=list(s.indices), values=list(s.values)),
                },
                payload={**p, id_key: i},
            )
            for i, d, s, p in zip(ids, dense, sparse, payloads, strict=True)
        ]
        for start in range(0, len(points), 256):
            self._client.upsert(self._name(kind), points[start : start + 256], wait=True)

    @staticmethod
    def _filter(flt: dict[str, Any] | None) -> models.Filter | None:
        if not flt:
            return None
        return models.Filter(
            must=[models.FieldCondition(key=k, match=models.MatchValue(value=v)) for k, v in flt.items()]
        )

    def hybrid(
        self,
        kind: Kind,
        dense: list[float],
        sparse: SparseVec,
        flt: dict[str, Any] | None,
        limit: int,
    ) -> list[Hit]:
        """RRF fusion of an exact dense and an exact BM25 branch (top 30 each), fused client-side.

        Each branch is cut in a fixed order (``top_of_branch``) and fused with Qdrant's RRF formula
        (``fuse_rrf``), so embedded and server Qdrant return the same hits in the same order: a
        server-side fusion broke score ties (float32 vs float64) differently per engine. The dense
        branch also supplies ``dense_score``; ``branches`` is 2 when a point is in both top-30s.
        """
        qfilter = self._filter(flt)
        dvec = [float(x) for x in dense]
        svec = models.SparseVector(indices=list(sparse.indices), values=list(sparse.values))
        with self._quiet():
            return self._hybrid(kind, dvec, svec, qfilter, limit)

    def _hybrid(
        self,
        kind: Kind,
        dvec: list[float],
        svec: models.SparseVector,
        qfilter: models.Filter | None,
        limit: int,
    ) -> list[Hit]:
        name = self._name(kind)
        id_key = "chunk_id" if kind == "chunks" else "fact_id"
        exact = models.SearchParams(exact=True)
        branches = [
            top_of_branch(
                self._client.query_points(
                    name,
                    query=query,
                    using=using,
                    query_filter=qfilter,
                    limit=PREFETCH_LIMIT + TIE_MARGIN,
                    search_params=exact,
                    with_payload=True,
                ).points,
                id_key,
                PREFETCH_LIMIT,
            )
            for query, using in ((dvec, "dense"), (svec, "bm25"))
        ]
        dense_pts, sparse_pts = branches
        scores = fuse_rrf([[_point_key(p, id_key) for p in pts] for pts in branches])
        points = {_point_key(p, id_key): p for pts in branches for p in pts}
        dense_scores = {_point_key(p, id_key): float(p.score) for p in dense_pts}
        sparse_ids = {_point_key(p, id_key) for p in sparse_pts}
        hits = [
            Hit(
                id=key,
                score=score,
                dense_score=dense_scores.get(key),
                branches=(key in dense_scores) + (key in sparse_ids),
                payload=dict(points[key].payload or {}),
            )
            for key, score in scores.items()
        ]
        return rank_fused(hits, limit)

    def count(self, kind: Kind) -> int:
        return int(self._client.count(self._name(kind), exact=True).count)

    def has_collections(self) -> bool:
        return all(self._client.collection_exists(self._name(k)) for k in ("chunks", "facts"))

    def sample_payload(self, kind: Kind) -> dict[str, Any] | None:
        """Payload of one point (None when the collection is empty)."""
        points, _ = self._client.scroll(self._name(kind), limit=1, with_payload=True, with_vectors=False)
        return dict(points[0].payload or {}) if points else None

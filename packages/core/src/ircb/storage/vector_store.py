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
        """RRF fusion of a dense and a BM25 prefetch (30 each, exact) in ONE fusion ``query_points``.

        Qdrant does not expose per-branch scores of a fused query, so two extra exact,
        dense-only / sparse-only ``query_points`` calls (limit 30) supply ``dense_score`` and
        ``branches`` (2 if the id is in both branch top-30s, else 1). Cheap on a few thousand points.
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
        exact = models.SearchParams(exact=True)
        fused = self._client.query_points(
            name,
            prefetch=[
                models.Prefetch(
                    query=dvec, using="dense", limit=PREFETCH_LIMIT, filter=qfilter, params=exact
                ),
                models.Prefetch(query=svec, using="bm25", limit=PREFETCH_LIMIT, filter=qfilter, params=exact),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=qfilter,
            limit=limit,
            with_payload=True,
        ).points
        if not fused:
            return []
        dense_pts = self._client.query_points(
            name,
            query=dvec,
            using="dense",
            query_filter=qfilter,
            limit=PREFETCH_LIMIT,
            search_params=exact,
            with_payload=False,
        ).points
        sparse_pts = self._client.query_points(
            name,
            query=svec,
            using="bm25",
            query_filter=qfilter,
            limit=PREFETCH_LIMIT,
            search_params=exact,
            with_payload=False,
        ).points
        dense_scores = {str(p.id): p.score for p in dense_pts}
        sparse_ids = {str(p.id) for p in sparse_pts}
        id_key = "chunk_id" if kind == "chunks" else "fact_id"
        hits: list[Hit] = []
        for p in fused:
            pid = str(p.id)
            payload = dict(p.payload or {})
            branches = (pid in dense_scores) + (pid in sparse_ids)
            hits.append(
                Hit(
                    id=str(payload.get(id_key, pid)),
                    score=float(p.score),
                    dense_score=dense_scores.get(pid),
                    branches=branches or 1,
                    payload=payload,
                )
            )
        return hits

    def count(self, kind: Kind) -> int:
        return int(self._client.count(self._name(kind), exact=True).count)

    def has_collections(self) -> bool:
        return all(self._client.collection_exists(self._name(k)) for k in ("chunks", "facts"))

    def sample_payload(self, kind: Kind) -> dict[str, Any] | None:
        """Payload of one point (None when the collection is empty)."""
        points, _ = self._client.scroll(self._name(kind), limit=1, with_payload=True, with_vectors=False)
        return dict(points[0].payload or {}) if points else None

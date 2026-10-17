"""Load shipped index artefacts (facts -> SQL, vectors -> Qdrant) idempotently."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine

from ircb.domain.models import Chunk, Fact
from ircb.ingestion.facts import fact_embed_text
from ircb.retrieval.sparse_bm25 import SparseVec
from ircb.settings import Settings
from ircb.storage import artefacts
from ircb.storage.db import make_engine, session_scope, upgrade_db
from ircb.storage.fact_repo import SqlFactStore
from ircb.storage.orm import FactRow, IndexVersion
from ircb.storage.vector_store import QdrantStore

# The chunk payload is the complete Chunk: retrieval rebuilds Chunk objects from it.
_CHUNK_KEYS = tuple(Chunk.model_fields)
_FACT_KEYS = ("doc_id", "label", "period", "statement", "unit")


class ManifestMismatchError(Exception):
    pass


@dataclass
class LoadResult:
    loaded: bool
    n_chunks: int
    n_facts: int


def _is_loaded(engine: Engine, store: QdrantStore, manifest: artefacts.Manifest) -> bool:
    """Loaded = SQL has the version AND Qdrant holds exactly the manifest's points in the current
    payload shape. A deleted / switched / half-loaded Qdrant, or chunks loaded by an older loader
    (incomplete payload), therefore trigger a reload instead of refusing every query."""
    with session_scope(engine) as s:
        if s.get(IndexVersion, manifest.index_version) is None:
            return False
    if not store.has_collections():
        return False
    if (store.count("chunks"), store.count("facts")) != (manifest.n_chunks, manifest.n_facts):
        return False
    sample = store.sample_payload("chunks")
    return sample is None or set(_CHUNK_KEYS) <= set(sample)


def load_index(index_dir: Path, store: QdrantStore, engine: Engine, force: bool = False) -> LoadResult:
    manifest = artefacts.read_manifest(index_dir)
    if not force and _is_loaded(engine, store, manifest):
        return LoadResult(False, manifest.n_chunks, manifest.n_facts)

    chunks = artefacts.read_chunks(index_dir)
    facts = [Fact.model_validate(d) for d in artefacts.read_facts(index_dir)]
    vectors = {(v.kind, v.id): v for v in artefacts.read_vectors(index_dir)}

    # A new index version (or force) fully replaces the old data: no superseded ids may survive.
    with session_scope(engine) as s:
        s.execute(sa.delete(FactRow).where(FactRow.doc_id == manifest.doc_id))
    SqlFactStore(engine).upsert(facts)
    store.reset_collections(manifest.embed_dimensions)

    c_ids: list[str] = []
    c_dense: list[list[float]] = []
    c_sparse: list[SparseVec] = []
    c_pay: list[dict[str, Any]] = []
    for c in chunks:
        v = vectors[("chunk", c["chunk_id"])]
        c_ids.append(c["chunk_id"])
        c_dense.append(v.dense)
        c_sparse.append(SparseVec(v.sparse_indices, v.sparse_values))
        c_pay.append(Chunk.model_validate(c).model_dump(mode="json"))
    store.upsert("chunks", c_ids, c_dense, c_sparse, c_pay)

    f_ids: list[str] = []
    f_dense: list[list[float]] = []
    f_sparse: list[SparseVec] = []
    f_pay: list[dict[str, Any]] = []
    for f in facts:
        v = vectors[("fact", f.fact_id)]
        f_ids.append(f.fact_id)
        f_dense.append(v.dense)
        f_sparse.append(SparseVec(v.sparse_indices, v.sparse_values))
        payload: dict[str, Any] = {k: getattr(f, k) for k in _FACT_KEYS}
        payload["text"] = fact_embed_text(f)
        f_pay.append(payload)
    store.upsert("facts", f_ids, f_dense, f_sparse, f_pay)

    with session_scope(engine) as s:
        if s.get(IndexVersion, manifest.index_version) is None:
            s.add(IndexVersion(index_version=manifest.index_version))
    return LoadResult(True, len(chunks), len(facts))


def ensure_loaded(settings: Settings, force: bool = False) -> LoadResult:
    manifest = artefacts.read_manifest(settings.index_dir)
    if (manifest.embed_model, manifest.embed_dimensions) != (
        settings.embed_model,
        settings.embed_dimensions,
    ):
        raise ManifestMismatchError(
            f"index built with {manifest.embed_model}/{manifest.embed_dimensions} but settings use "
            f"{settings.embed_model}/{settings.embed_dimensions}; run `ircb index reembed`"
        )
    settings.ensure_dirs()
    engine = make_engine(settings.database_url)
    upgrade_db(engine)
    store = QdrantStore(settings)
    try:
        return load_index(settings.index_dir, store, engine, force=force)
    finally:
        store.close()


def reload_index(settings: Settings) -> LoadResult:
    """Full reload after a re-embed: drop and recreate both collections, then force-load."""
    manifest = artefacts.read_manifest(settings.index_dir)
    settings.ensure_dirs()
    engine = make_engine(settings.database_url)
    upgrade_db(engine)
    store = QdrantStore(settings)
    try:
        store.recreate_collections(manifest.embed_dimensions)
        return load_index(settings.index_dir, store, engine, force=True)
    finally:
        store.close()

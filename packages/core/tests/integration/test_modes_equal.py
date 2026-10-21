"""Embedded (Qdrant local + SQLite) and server (Qdrant server + PostgreSQL) modes retrieve identically.

Server mode runs against a throwaway PostgreSQL database and uniquely-prefixed Qdrant collections,
both removed afterwards: these tests never write to the ``ircb`` database.
"""

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from ircb.domain.models import RewriteResult
from ircb.retrieval.hybrid import RetrievalDeps
from ircb.retrieval.prefetch import prefetch
from ircb.settings import Settings
from ircb.storage import artefacts
from ircb.storage.db import make_engine
from ircb.storage.fact_repo import SqlFactStore
from ircb.storage.loader import ensure_loaded
from ircb.storage.vector_store import QdrantStore
from qdrant_client import QdrantClient
from sqlalchemy import Engine

from modes_support import QUERIES, HashEmbedder, build_mini_index, rw_for

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[4]
INDEX_DIR = REPO / "index"
DEV_SET = REPO / "eval" / "datasets" / "own_questions.jsonl"


def _deps(settings: Settings, doc_id: str, opened: list[Any]) -> RetrievalDeps:
    ensure_loaded(settings)
    store = QdrantStore(settings)
    engine: Engine = make_engine(settings.database_url)
    opened.extend([store, engine])  # both have close()/dispose() called in teardown
    return RetrievalDeps(
        store=store,
        sql=SqlFactStore(engine),
        embedder=HashEmbedder(settings.embed_dimensions),
        doc_id=doc_id,
    )


def _open_modes(
    tmp_path: Path, qdrant_url: str, pg_db: str, index_dir: Path
) -> Iterator[tuple[RetrievalDeps, RetrievalDeps]]:
    manifest = artefacts.read_manifest(index_dir)
    common: dict[str, Any] = {
        "llm_model": "x",
        "embed_dimensions": manifest.embed_dimensions,
        "index_dir": index_dir,
        "qdrant_collection_prefix": f"ircb_it_{uuid.uuid4().hex[:8]}_",
    }
    embedded = Settings(
        **common,
        qdrant_url=None,
        qdrant_path=str(tmp_path / "qdrant"),
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
    )
    server = Settings(**common, qdrant_url=qdrant_url, database_url=pg_db)
    opened: list[Any] = []
    try:
        a = _deps(embedded, manifest.doc_id, opened)
        b = _deps(server, manifest.doc_id, opened)
        yield a, b
    finally:
        for r in opened:
            r.dispose() if isinstance(r, Engine) else r.close()
        client = QdrantClient(url=qdrant_url)
        for kind in ("chunks", "facts"):
            client.delete_collection(f"{server.qdrant_collection_prefix}{kind}")
        client.close()


@pytest.fixture
def synthetic_modes(
    tmp_path: Path, qdrant_url: str, pg_db: str
) -> Iterator[tuple[RetrievalDeps, RetrievalDeps]]:
    run = uuid.uuid4().hex[:8]
    index_dir = build_mini_index(tmp_path / "index", f"it-{run}", run)
    yield from _open_modes(tmp_path, qdrant_url, pg_db, index_dir)


@pytest.fixture
def real_modes(tmp_path: Path, qdrant_url: str, pg_db: str) -> Iterator[tuple[RetrievalDeps, RetrievalDeps]]:
    if not (INDEX_DIR / "manifest.json").exists():
        pytest.skip("index/manifest.json not built")
    yield from _open_modes(tmp_path, qdrant_url, pg_db, INDEX_DIR)


def _ids(deps: RetrievalDeps, rw: RewriteResult) -> tuple[list[str], list[str], list[str]]:
    ctx = prefetch(rw, deps)
    return (
        [h.id for h in ctx.chunk_hits],
        [h.id for h in ctx.fact_hits],
        [f.fact_id for f in ctx.facts],
    )


def test_synthetic_topk_equal_across_modes(synthetic_modes: tuple[RetrievalDeps, RetrievalDeps]) -> None:
    embedded, server = synthetic_modes
    for rw in QUERIES:
        a, b = _ids(embedded, rw), _ids(server, rw)
        assert a[0], rw.standalone_query  # the comparison must not be vacuous
        assert a == b, rw.standalone_query


def _dev_questions() -> list[str]:
    rows = [json.loads(line) for line in DEV_SET.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r["question"] for r in rows if r.get("split") == "dev"]


def test_dev_questions_topk_equal_across_modes(real_modes: tuple[RetrievalDeps, RetrievalDeps]) -> None:
    embedded, server = real_modes
    questions = _dev_questions()
    assert questions
    for q in questions:
        assert _ids(embedded, rw_for(q)) == _ids(server, rw_for(q)), q

from collections.abc import Iterator
from pathlib import Path

import pytest
from ircb.domain.models import Chunk
from ircb.retrieval.sparse_bm25 import SparseVec
from ircb.settings import Settings
from ircb.storage import artefacts
from ircb.storage.artefacts import Manifest, VectorRecord
from ircb.storage.db import make_engine, upgrade_db
from ircb.storage.fact_repo import SqlFactStore
from ircb.storage.loader import ManifestMismatchError, ensure_loaded, load_index
from ircb.storage.vector_store import QdrantStore
from sqlalchemy.engine import Engine

from factories import fact

DIM = 8


def vec(i: int = 0) -> list[float]:
    v = [0.1] * DIM
    v[i % DIM] = 1.0
    return v


def sparse(i: int = 0) -> SparseVec:
    return SparseVec([i, i + 10], [1.0, 0.5])


def build_index_dir(d: Path, n: int, version: str) -> Path:
    chunks = [
        Chunk(
            chunk_id=f"c{i}",
            doc_id="tcb-ar-2025",
            pdf_page=1,
            half="L",
            printed_pages=[i + 1],
            chapter="Ch1",
            statement=None,
            note_no=None,
            content_type="prose",
            unit=None,
            text=f"đoạn {i}",
            fact_ids=[],
            bbox=[0.0, 0.0, 1.0, 1.0],
        )
        for i in range(n)
    ]
    facts = [fact(fact_id=f"f{i}", label=f"chỉ tiêu {i}", period="2025") for i in range(n)]
    artefacts.write_chunks(d, chunks)
    artefacts.write_facts(d, facts)
    recs = [
        VectorRecord(c.chunk_id, "chunk", vec(i), sparse(i).indices, sparse(i).values)
        for i, c in enumerate(chunks)
    ]
    recs += [
        VectorRecord(f.fact_id, "fact", vec(i), sparse(i).indices, sparse(i).values)
        for i, f in enumerate(facts)
    ]
    artefacts.write_vectors(d, recs)
    artefacts.write_manifest(
        d,
        Manifest(
            index_version=version,
            doc_id="tcb-ar-2025",
            pdf_sha256="0",
            embed_provider="openai",
            embed_model="ollama/qwen3-embedding:4b",
            embed_dimensions=DIM,
            tokenizer_version="t1",
            periods_seen=["2025"],
            n_chunks=n,
            n_facts=n,
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    return d


@pytest.fixture
def mini_index(tmp_path: Path) -> Path:
    return build_index_dir(tmp_path / "index", 5, "v1")


@pytest.fixture
def settings(tmp_path: Path, mini_index: Path) -> Settings:
    return Settings(
        llm_model="x",
        embed_dimensions=DIM,
        index_dir=mini_index,
        qdrant_path=str(tmp_path / "qdrant"),
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
    )


@pytest.fixture
def store(settings: Settings) -> Iterator[QdrantStore]:
    s = QdrantStore(settings)
    yield s
    s.close()


@pytest.fixture
def engine(settings: Settings) -> Engine:
    eng = make_engine(settings.database_url)
    upgrade_db(eng)
    return eng


def test_load_idempotent(mini_index: Path, store: QdrantStore, engine: Engine) -> None:
    load_index(mini_index, store, engine)
    load_index(mini_index, store, engine, force=True)
    assert store.count("chunks") == 5 and store.count("facts") == 5


def test_skip_when_version_loaded(mini_index: Path, store: QdrantStore, engine: Engine) -> None:
    assert load_index(mini_index, store, engine).loaded is True
    assert load_index(mini_index, store, engine).loaded is False


def test_fact_payload_has_no_value(mini_index: Path, store: QdrantStore, engine: Engine) -> None:
    load_index(mini_index, store, engine)
    h = store.hybrid("facts", vec(), sparse(), None, 5)[0]
    assert "value" not in h.payload and "fact_id" in h.payload
    assert set(h.payload) == {"fact_id", "doc_id", "label", "period", "statement", "unit", "text"}
    assert h.id == h.payload["fact_id"] and h.branches in (1, 2) and h.dense_score is not None


def test_hybrid_ranks_matching_chunk_first(mini_index: Path, store: QdrantStore, engine: Engine) -> None:
    load_index(mini_index, store, engine)
    h = store.hybrid("chunks", vec(2), sparse(2), {"doc_id": "tcb-ar-2025"}, 3)
    assert h[0].id == "c2" and h[0].branches == 2


def test_manifest_mismatch(mini_index: Path, settings: Settings) -> None:
    with pytest.raises(ManifestMismatchError, match="ircb index reembed"):
        ensure_loaded(settings.model_copy(update={"embed_dimensions": 3072}))


def test_ensure_loaded_then_skips(settings: Settings) -> None:
    assert ensure_loaded(settings).loaded is True
    assert ensure_loaded(settings).loaded is False


def test_doc_filter(mini_index: Path, store: QdrantStore, engine: Engine) -> None:
    load_index(mini_index, store, engine)
    assert store.hybrid("chunks", vec(), sparse(), {"doc_id": "other"}, 5) == []
    assert store.hybrid("chunks", vec(), sparse(), {"doc_id": "tcb-ar-2025"}, 5) != []


def test_ensure_loaded_matching_settings_does_not_raise(settings: Settings) -> None:
    r = ensure_loaded(settings)
    assert r.loaded is True and r.n_chunks == 5 and r.n_facts == 5


def test_new_version_replaces_stale_data(
    tmp_path: Path, mini_index: Path, store: QdrantStore, engine: Engine
) -> None:
    load_index(mini_index, store, engine)
    v2 = build_index_dir(tmp_path / "index2", 4, "v2")
    assert load_index(v2, store, engine).loaded is True
    assert store.count("chunks") == 4 and store.count("facts") == 4
    ids = {h.id for h in store.hybrid("chunks", vec(), sparse(), None, 10)}
    assert "c4" not in ids and len(ids) == 4
    fids = {h.id for h in store.hybrid("facts", vec(), sparse(), None, 10)}
    assert "f4" not in fids
    assert set(SqlFactStore(engine).get_many([f"f{i}" for i in range(5)])) == {"f0", "f1", "f2", "f3"}


def test_recreate_collections_changes_dimension(tmp_path: Path, settings: Settings, mini_index: Path) -> None:
    s = QdrantStore(settings)
    try:
        eng = make_engine(settings.database_url)
        upgrade_db(eng)
        load_index(mini_index, s, eng)
        assert s.dense_dim() == DIM and s.count("chunks") == 5
        s.recreate_collections(16)
        assert s.dense_dim() == 16 and s.count("chunks") == 0 and s.count("facts") == 0
        s.upsert("chunks", ["x"], [[0.5] * 16], [sparse(1)], [{"doc_id": "tcb-ar-2025"}])
        assert s.count("chunks") == 1
    finally:
        s.close()


def test_recreate_collections_survives_reopen(tmp_path: Path, settings: Settings, mini_index: Path) -> None:
    s = QdrantStore(settings)
    eng = make_engine(settings.database_url)
    upgrade_db(eng)
    load_index(mini_index, s, eng)
    s.recreate_collections(16)
    s.close()
    again = QdrantStore(settings)
    try:
        assert again.dense_dim() == 16 and again.count("chunks") == 0
    finally:
        again.close()


def test_reset_collections_handles_dimension_change(settings: Settings, mini_index: Path) -> None:
    s = QdrantStore(settings)
    try:
        eng = make_engine(settings.database_url)
        upgrade_db(eng)
        load_index(mini_index, s, eng)
        s.reset_collections(16)
        assert s.dense_dim() == 16 and s.count("chunks") == 0
    finally:
        s.close()


class _VecEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vec(2) for _ in texts]


def test_loaded_chunk_payload_rebuilds_chunk_through_prefetch(
    mini_index: Path, store: QdrantStore, engine: Engine
) -> None:
    """Regression C1: the real loader payload must parse back into a full Chunk in prefetch."""
    from ircb.domain.models import RewriteResult
    from ircb.retrieval.hybrid import RetrievalDeps
    from ircb.retrieval.prefetch import prefetch

    load_index(mini_index, store, engine)
    deps = RetrievalDeps(store=store, sql=SqlFactStore(engine), embedder=_VecEmbedder())
    rw = RewriteResult(
        standalone_query="đoạn 2",
        metrics=[],
        periods=[],
        entity=None,
        topic=None,
        needs_comparison=False,
        needs_calc=False,
        is_forecast=False,
    )
    ctx = prefetch(rw, deps)
    assert ctx.chunks and all(isinstance(c, Chunk) for c in ctx.chunks)
    by_id = {c.chunk_id: c for c in ctx.chunks}
    assert by_id["c2"].pdf_page == 1 and by_id["c2"].half == "L"
    assert by_id["c2"].fact_ids == [] and by_id["c2"].bbox == [0.0, 0.0, 1.0, 1.0]


def test_chunk_from_hit_incomplete_payload_names_the_fix() -> None:
    from ircb.retrieval.hybrid import StalePayloadError, chunk_from_hit
    from ircb.storage.vector_store import Hit

    hit = Hit(id="c0", score=1.0, dense_score=1.0, branches=2, payload={"chunk_id": "c0", "text": "x"})
    with pytest.raises(StalePayloadError, match="ircb index load --force"):
        chunk_from_hit(hit)


_PATH_ENV = (
    "DATABASE_URL",
    "QDRANT_URL",
    "QDRANT_PATH",
    "TRACE_DIR",
    "EMBED_CACHE_DIR",
    "PAGE_CACHE_DIR",
    "INDEX_DIR",
)


def test_fresh_checkout_creates_runtime_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression I5: with default relative paths and no var/, the first load and service start work."""
    from ircb.service import AnswerService

    for k in _PATH_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    build_index_dir(tmp_path / "index", 3, "v1")
    (tmp_path / "index" / "glossary.json").write_text('{"entries": [], "extra": {}}', encoding="utf-8")
    s = Settings(_env_file=None, llm_model="x", embed_dimensions=DIM)  # type: ignore[call-arg]
    assert not (tmp_path / "var").exists()
    assert ensure_loaded(s).loaded is True
    svc = AnswerService.from_settings(s)
    for d in ("var", "var/qdrant", "var/embed_cache", "var/page_cache", "traces"):
        assert (tmp_path / d).is_dir(), d
    assert (tmp_path / "var" / "app.db").is_file()
    svc.deps.store.close()  # type: ignore[attr-defined]


def test_make_engine_creates_sqlite_parent(tmp_path: Path) -> None:
    eng = make_engine(f"sqlite:///{(tmp_path / 'a' / 'b' / 'app.db').as_posix()}")
    upgrade_db(eng)
    assert (tmp_path / "a" / "b" / "app.db").is_file()
    make_engine("sqlite://")  # in-memory: nothing to create


def test_ensure_loaded_reloads_when_qdrant_dir_deleted(settings: Settings) -> None:
    """Regression I6: the SQL version row alone does not mean Qdrant still holds the index."""
    import shutil

    assert ensure_loaded(settings).loaded is True
    shutil.rmtree(settings.qdrant_path)
    r = ensure_loaded(settings)
    assert r.loaded is True
    s = QdrantStore(settings)
    try:
        assert s.count("chunks") == 5 and s.count("facts") == 5
    finally:
        s.close()
    assert ensure_loaded(settings).loaded is False


def test_ensure_loaded_reloads_on_count_mismatch(settings: Settings) -> None:
    assert ensure_loaded(settings).loaded is True
    s = QdrantStore(settings)
    s.reset_collections(DIM)  # empty collections, SQL row kept
    s.close()
    assert ensure_loaded(settings).loaded is True


def test_ensure_loaded_reloads_stale_chunk_payload(settings: Settings) -> None:
    """An index loaded by the old loader (incomplete chunk payload) is reloaded automatically."""
    assert ensure_loaded(settings).loaded is True
    s = QdrantStore(settings)
    try:
        ids = [f"c{i}" for i in range(5)]
        s.upsert("chunks", ids, [vec(i) for i in range(5)], [sparse(i) for i in range(5)],
                 [{"doc_id": "tcb-ar-2025", "text": "x"} for _ in ids])  # fmt: skip
    finally:
        s.close()
    assert ensure_loaded(settings).loaded is True


def test_fused_ties_order_by_id_whatever_the_engine_returns() -> None:
    """RRF gives equal scores to symmetric ranks; embedded (float64) and server (float32) Qdrant
    broke those ties differently, so the two modes fed the generator different context orders."""
    from ircb.storage.vector_store import Hit, rank_fused

    def hit(i: str, s: float) -> Hit:
        return Hit(id=i, score=s, dense_score=None, branches=2, payload={})

    embedded = [
        hit("p140R_t02", 0.5),
        hit("p40L_x01", 0.5),
        hit("g_ees", 0.333333333),
        hit("p3R_k", 0.333333333),
    ]
    server = [hit("p40L_x01", 0.5), hit("p140R_t02", 0.5), hit("p3R_k", 0.33333334), hit("g_ees", 0.33333334)]
    expected = ["p140R_t02", "p40L_x01", "g_ees", "p3R_k"]
    assert [h.id for h in rank_fused(embedded, 4)] == expected
    assert [h.id for h in rank_fused(server, 4)] == expected
    # a tie straddling the cut-off keeps the same member in both modes
    assert [h.id for h in rank_fused(server, 3)] == expected[:3]
    # a strictly higher score still wins over id order
    assert [h.id for h in rank_fused([hit("a", 0.2), hit("z", 0.5)], 2)] == ["z", "a"]


def test_branch_ties_at_the_prefetch_cut_pick_the_same_points() -> None:
    """A dense or BM25 tie at the 30-point cut made the two modes fuse different candidates
    (p168R_t02 vs p168R_t03 on a dev question); branches are now cut in a fixed order."""
    from types import SimpleNamespace

    from ircb.storage.vector_store import fuse_rrf, top_of_branch

    def pt(cid: str, s: float) -> SimpleNamespace:
        return SimpleNamespace(id=f"uuid-{cid}", score=s, payload={"chunk_id": cid})

    a = [pt("x", 0.9), pt("t03", 0.4), pt("t02", 0.4)]
    b = [pt("x", 0.9), pt("t02", 0.40000001), pt("t03", 0.4)]
    assert [p.payload["chunk_id"] for p in top_of_branch(a, "chunk_id", 2)] == ["x", "t02"]
    assert [p.payload["chunk_id"] for p in top_of_branch(b, "chunk_id", 2)] == ["x", "t02"]
    # Qdrant's RRF: 1 / (1 + rank), rank from 1; summed over the branches a point appears in
    scores = fuse_rrf([["x", "t02"], ["t02", "y"]])
    assert scores == {"x": 0.5, "t02": 1 / 3 + 1 / 2, "y": 1 / 3}

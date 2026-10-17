from pathlib import Path

from ircb.ingestion.pipeline import reembed_index
from ircb.retrieval.embed import Embedder
from ircb.settings import Settings
from ircb.storage import artefacts
from ircb.storage.db import make_engine, upgrade_db
from ircb.storage.loader import ensure_loaded, reload_index
from ircb.storage.vector_store import QdrantStore
from test_vector_store_loader import DIM, build_index_dir


class Backend:
    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.25] * self.dim for _ in texts]


def test_reembed_updates_manifest_and_vectors(tmp_path: Path) -> None:
    idx = build_index_dir(tmp_path / "index", 3, "v1")
    old = artefacts.read_manifest(idx)
    m = reembed_index(idx, Embedder(Backend(16), tmp_path / "cache", "openai/other-model", 16))
    assert (m.embed_model, m.embed_dimensions, m.embed_provider) == ("openai/other-model", 16, "openai")
    assert m.index_version != old.index_version and m.n_chunks == old.n_chunks
    assert artefacts.read_manifest(idx) == m
    vecs = artefacts.read_vectors(idx)
    assert len(vecs) == 6 and all(len(v.dense) == 16 for v in vecs)


def test_reembed_then_reload_dims_8_to_16(tmp_path: Path) -> None:
    idx = build_index_dir(tmp_path / "index", 3, "v1")
    base = {
        "llm_model": "x",
        "index_dir": idx,
        "qdrant_path": str(tmp_path / "qdrant"),
        "database_url": f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
    }
    assert ensure_loaded(Settings(embed_dimensions=DIM, **base)).loaded is True  # type: ignore[arg-type]
    s16 = Settings(embed_dimensions=16, **base)  # type: ignore[arg-type]
    reembed_index(idx, Embedder(Backend(16), tmp_path / "cache", s16.embed_model, 16))
    assert reload_index(s16).loaded is True
    store = QdrantStore(s16)
    try:
        assert store.dense_dim() == 16 and store.count("chunks") == 3 and store.count("facts") == 3
    finally:
        store.close()
    upgrade_db(make_engine(s16.database_url))
    assert ensure_loaded(s16).loaded is False  # new manifest version is now the loaded one

import hashlib
from pathlib import Path

import pymupdf as fitz
import pytest
from ircb.ingestion.pipeline import kpi_golden_check, main
from ircb.retrieval.embed import Embedder
from ircb.storage.artefacts import (
    read_chunks,
    read_facts,
    read_manifest,
    read_page_map,
    read_report,
    read_vectors,
)

pytestmark = pytest.mark.requires_pdf

DIMS = 1024


class HashBackend:
    """Deterministic fake vectors; never calls a real provider."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            out.append([h[i % 32] / 255.0 for i in range(DIMS)])
        return out


class FakeEmbedder(Embedder):
    """Bypasses the on-disk cache so the test writes no per-text files."""

    def __init__(self) -> None:
        super().__init__(HashBackend(), Path("unused"), "openai/text-embedding-3-large", DIMS)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.backend.embed(texts)


def test_kpi_golden_check_passes(doc: fitz.Document) -> None:
    assert kpi_golden_check(doc) == []


def test_build_index_end_to_end(
    tmp_path: Path,
    pdf_path: Path,
    doc: fitz.Document,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # module entry point (python -m ircb.ingestion.pipeline <pdf> --out <dir>) -> build_index
    monkeypatch.setenv("LLM_MODEL", "fake")
    monkeypatch.setenv("EMBED_CACHE_DIR", str(tmp_path / "cache"))
    assert main([str(pdf_path), "--out", str(tmp_path)], embedder=FakeEmbedder()) == 0
    m = read_manifest(tmp_path)
    assert f"index {m.index_version}: {m.n_chunks} chunks, {m.n_facts} facts" in capsys.readouterr().out
    assert "2027" not in m.periods_seen and "2026" in m.periods_seen
    assert m.n_facts >= 2000 and (tmp_path / "vectors.parquet").exists()
    assert {c["chunk_id"] for c in read_chunks(tmp_path) if c["content_type"] == "glossary"}

    assert m.embed_dimensions == DIMS and len(m.index_version) == 12
    chunks, facts = read_chunks(tmp_path), read_facts(tmp_path)
    assert (m.n_chunks, m.n_facts) == (len(chunks), len(facts))
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)
    assert len({f["fact_id"] for f in facts}) == len(facts)
    fact_ids = {f["fact_id"] for f in facts}
    dangling = [(c["chunk_id"], fid) for c in chunks for fid in c["fact_ids"] if fid not in fact_ids]
    assert dangling == []  # every chunk.fact_ids entry is a real fact (ledger T12)
    assert all(f["unit"] and f["printed_pages"] for f in facts)
    vecs = read_vectors(tmp_path)
    assert len(vecs) == len(chunks) + len(facts)
    assert all(len(v.dense) == DIMS for v in vecs[:5])
    assert {v.kind for v in vecs} == {"chunk", "fact"}
    assert len(read_page_map(tmp_path)) == 2 * doc.page_count - 1  # cover + two halves per spread

    rep = read_report(tmp_path)
    assert rep["kpi_golden_failed"] == [] and rep["facts_missing_unit"] == 0
    assert rep["n_chunks"] == len(chunks) and rep["n_facts"] == len(facts)
    assert set(rep["content_types"]) >= {"prose", "table", "kpi", "glossary"}
    assert any(i["xref"] == 238 for i in rep["informative_images_pending_vlm"])
    assert len(rep["table_qa"]) >= 380
    assert (tmp_path / "glossary.json").exists() and not (tmp_path / ".tmp").exists()
    assert all(h != [10, "L", 0.0] for h in rep["low_halves"])  # narrative halves filtered
    # KPI facts exist for printed p.5 and p.59
    kpi = [f for f in facts if f["source"] == "kpi"]
    assert any(f["printed_pages"] == [5] and f["raw"] == "1.192" for f in kpi)
    assert any(f["printed_pages"] == [59] and f["raw"] == "328,1" for f in kpi)

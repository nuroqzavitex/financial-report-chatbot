import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from ircb.domain.models import Chunk
from ircb.ingestion import pipeline
from ircb.ingestion.facts import fact_embed_text
from ircb.ingestion.pipeline import (
    GateError,
    assert_unique_ids,
    check_gates,
    compute_index_version,
    run_embed,
    years_in_text,
)
from ircb.retrieval.embed import Embedder
from ircb.retrieval.sparse_bm25 import encode_doc
from ircb.retrieval.tokenize_vi import TOKENIZER_VERSION, tokenize
from ircb.storage.artefacts import (
    Manifest,
    VectorRecord,
    read_chunks,
    read_facts,
    read_manifest,
    read_report,
    read_vectors,
    write_chunks,
    write_facts,
    write_glossary,
    write_manifest,
    write_page_map,
    write_report,
    write_vectors,
)

from factories import fact


def report(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "page_map_mismatches": 0,
        "facts_missing_unit": 0,
        "facts_missing_pages": 0,
        "kpi_golden_failed": [],
        "low_halves": [],
    }
    base.update(kw)
    return base


def chunk(**kw: Any) -> Chunk:
    base: dict[str, Any] = {
        "chunk_id": "p2L_x01",
        "doc_id": "tcb-ar-2025",
        "pdf_page": 2,
        "half": "L",
        "printed_pages": [2],
        "chapter": None,
        "statement": None,
        "note_no": None,
        "content_type": "prose",
        "unit": None,
        "text": "Tổng tài sản tăng mạnh",
        "fact_ids": [],
        "bbox": [0.0, 0.0, 1.0, 1.0],
    }
    base.update(kw)
    return Chunk(**base)


class LenBackend:
    def __init__(self, dims: int) -> None:
        self.dims = dims
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(t))] + [0.5] * (self.dims - 1) for t in texts]


# ---------------------------------------------------------------- gates


def test_gate_fails_on_missing_unit() -> None:
    with pytest.raises(GateError, match="unit"):
        check_gates(report(facts_missing_unit=3))


def test_gate_fails_on_kpi_golden() -> None:
    with pytest.raises(GateError, match="kpi"):
        check_gates(report(kpi_golden_failed=["p5"]))


def test_gate_warns_on_low_coverage() -> None:
    assert check_gates(report(low_halves=[("152", "R", 0.91)])) == ["coverage<0.95: 152R=0.91"]


def test_gate_fails_on_page_map_and_missing_pages() -> None:
    with pytest.raises(GateError, match="page map"):
        check_gates(report(page_map_mismatches=2))
    with pytest.raises(GateError, match="printed_pages"):
        check_gates(report(facts_missing_pages=1))


def test_gate_clean_report_has_no_warnings() -> None:
    assert check_gates(report()) == []


def test_gate_lists_every_failure() -> None:
    with pytest.raises(GateError) as ei:
        check_gates(report(facts_missing_unit=1, kpi_golden_failed=["p59: 3 tiles"]))
    assert "unit" in str(ei.value) and "kpi" in str(ei.value)


# ---------------------------------------------------------------- helpers


def test_years_in_text() -> None:
    text = "Năm 2025 so với 2024; giai đoạn 2018–2025, 31/12/2026. Số 12.2019 và 120245 không tính."
    assert years_in_text(text) == {"2018", "2024", "2025", "2026"}


def test_index_version_is_12_hex_and_depends_on_inputs() -> None:
    v = compute_index_version("abc", "openai/text-embedding-3-large", 1024, "deadbee")
    assert len(v) == 12 and int(v, 16) >= 0
    assert v != compute_index_version("abc", "openai/text-embedding-3-large", 512, "deadbee")
    assert v != compute_index_version("abc", "openai/text-embedding-3-large", 1024, "nogit")
    import hashlib

    raw = "abc" + TOKENIZER_VERSION + "openai/text-embedding-3-large" + "1024" + "deadbee"
    assert v == hashlib.sha256(raw.encode()).hexdigest()[:12]


def test_unique_ids_raise_on_collision() -> None:
    assert_unique_ids([chunk(chunk_id="a"), chunk(chunk_id="b")], [fact(fact_id="f1")])
    with pytest.raises(GateError, match="chunk_id"):
        assert_unique_ids([chunk(chunk_id="a"), chunk(chunk_id="a")], [])
    with pytest.raises(GateError, match="fact_id"):
        assert_unique_ids([], [fact(fact_id="f1"), fact(fact_id="f1")])


# ---------------------------------------------------------------- artefacts


def test_chunks_and_facts_roundtrip(tmp_path: Path) -> None:
    write_chunks(tmp_path, [chunk(), chunk(chunk_id="g_casa", content_type="glossary")])
    write_facts(tmp_path, [fact(value=Decimal("1.192"))])
    cs = read_chunks(tmp_path)
    assert [c["chunk_id"] for c in cs] == ["p2L_x01", "g_casa"]
    assert Chunk.model_validate(cs[0]) == chunk()
    fs = read_facts(tmp_path)
    assert fs[0]["value"] == "1.192"  # Decimal kept exact as a string
    assert "Tổng tài sản" in (tmp_path / "chunks.jsonl").read_text(encoding="utf-8")


def test_vectors_parquet_roundtrip(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    recs = [
        VectorRecord("c1", "chunk", [0.25] * 4, [3, 4_000_000_000], [1.5, 0.75]),
        VectorRecord("f1", "fact", [0.5, -1.0, 0.0, 2.0], [], []),
    ]
    write_vectors(tmp_path, recs)
    assert read_vectors(tmp_path) == recs
    cols = pq.read_schema(tmp_path / "vectors.parquet").names
    assert cols == ["id", "kind", "dense", "sparse_indices", "sparse_values"]


def test_manifest_and_report_roundtrip(tmp_path: Path) -> None:
    m = Manifest(
        index_version="0123456789ab",
        doc_id="tcb-ar-2025",
        pdf_sha256="ff",
        embed_provider="openai",
        embed_model="openai/text-embedding-3-large",
        embed_dimensions=1024,
        tokenizer_version=TOKENIZER_VERSION,
        periods_seen=["2025"],
        n_chunks=1,
        n_facts=2,
        created_at="2026-10-17T00:00:00+00:00",
    )
    write_manifest(tmp_path, m)
    assert read_manifest(tmp_path) == m
    write_report(tmp_path, {"n_chunks": 1, "tên": "Tổng"})
    assert read_report(tmp_path) == {"n_chunks": 1, "tên": "Tổng"}


# ---------------------------------------------------------------- embed stage


def test_run_embed_dense_and_bm25(tmp_path: Path) -> None:
    cs = [chunk(chunk_id="a", text="Tổng tài sản"), chunk(chunk_id="b", text="Dư nợ vay khách hàng tăng")]
    fs = [fact(fact_id="f1", label="Tổng tài sản", table_title="Bảng cân đối")]
    write_chunks(tmp_path, cs)
    write_facts(tmp_path, fs)
    be = LenBackend(4)
    run_embed(tmp_path, Embedder(be, tmp_path / "cache", "m", 4))
    recs = {r.id: r for r in read_vectors(tmp_path)}
    assert [r.kind for r in recs.values()] == ["chunk", "chunk", "fact"]
    assert recs["a"].dense[0] == len("Tổng tài sản")
    assert recs["f1"].dense[0] == len(fact_embed_text(fs[0]))  # fact text = fact_embed_text
    toks = [tokenize(c.text) for c in cs]
    avg = sum(map(len, toks)) / len(toks)  # avg_len over all chunks, same tokenize() output
    want = encode_doc(toks[1], avg)
    assert recs["b"].sparse_indices == want.indices
    assert recs["b"].sparse_values == pytest.approx(want.values, rel=1e-6)
    ftoks = tokenize(fact_embed_text(fs[0]))
    fwant = encode_doc(ftoks, float(len(ftoks)))  # facts have their own avg_len
    assert recs["f1"].sparse_values == pytest.approx(fwant.values, rel=1e-6)


def test_run_embed_rejects_wrong_dimension(tmp_path: Path) -> None:
    write_chunks(tmp_path, [chunk()])
    write_facts(tmp_path, [])
    with pytest.raises(ValueError, match="dimension"):
        run_embed(tmp_path, Embedder(LenBackend(3), tmp_path / "cache", "m", 4))


# ---------------------------------------------------------------- entry point


def test_main_entry_point(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_build(pdf: Path, out: Path, settings: Any, embedder: Any = None) -> Manifest:
        seen.update(pdf=pdf, out=out, embedder=embedder)
        return Manifest(
            index_version="x",
            doc_id="tcb-ar-2025",
            pdf_sha256="",
            embed_provider="openai",
            embed_model="m",
            embed_dimensions=4,
            tokenizer_version=TOKENIZER_VERSION,
            periods_seen=[],
            n_chunks=3,
            n_facts=4,
            created_at="",
        )

    monkeypatch.setattr(pipeline, "build_index", fake_build)
    monkeypatch.setenv("LLM_MODEL", "x")
    assert pipeline.main([str(tmp_path / "a.pdf"), "--out", str(tmp_path / "idx")]) == 0
    assert seen["pdf"] == tmp_path / "a.pdf" and seen["out"] == tmp_path / "idx"


def test_report_is_json(tmp_path: Path) -> None:
    write_report(tmp_path, {"low_halves": [[152, "R", 0.91]]})
    assert json.loads((tmp_path / "ingest_report.json").read_text(encoding="utf-8"))["low_halves"]


# ---------------------------------------------------------------- fix round 1


def test_low_halves_filters_narrative_halves() -> None:
    qa = [
        {"pdf_page": 10, "half": "L", "ratio": 0.0},  # narrative (printed 18), no tables -> dropped
        {"pdf_page": 41, "half": "L", "ratio": 0.8125},  # narrative but holds a table -> kept
        {"pdf_page": 152, "half": "R", "ratio": 0.91},  # FS chapter (printed 303) -> kept
        {"pdf_page": 160, "half": "L", "ratio": 0.99},  # FS chapter, above threshold -> dropped
    ]
    assert pipeline.low_halves(qa, {(41, "L")}) == [[41, "L", 0.8125], [152, "R", 0.91]]


def test_low_halves_gutter_table_counts_for_both_halves() -> None:
    qa = [{"pdf_page": 20, "half": "L", "ratio": 0.5}, {"pdf_page": 20, "half": "R", "ratio": 0.5}]
    assert pipeline.table_halves([{"pdf_page": 20, "half": "G"}]) == {(20, "L"), (20, "R")}
    assert len(pipeline.low_halves(qa, pipeline.table_halves([{"pdf_page": 20, "half": "G"}]))) == 2


def _fake_stages(monkeypatch: pytest.MonkeyPatch, rep: dict[str, Any]) -> None:
    def extract(pdf: Path, out: Path) -> None:
        (out / "build").mkdir(parents=True, exist_ok=True)
        (out / "build" / "extract.json").write_text("{}", encoding="utf-8")

    def normalize(out: Path) -> None:
        write_chunks(out, [chunk(chunk_id="new")])
        write_facts(out, [])
        write_glossary(out, {"entries": [], "extra": {}})
        write_page_map(out, [])
        write_report(out, rep)

    monkeypatch.setattr(pipeline, "run_extract", extract)
    monkeypatch.setattr(pipeline, "run_normalize", normalize)


def _ok_report(**kw: Any) -> dict[str, Any]:
    return report(pdf_sha256="ab", periods_seen=["2025"], n_chunks=1, n_facts=0, **kw)


def _settings() -> Any:
    from ircb.settings import Settings

    return Settings(llm_model="x", _env_file=None)  # type: ignore[call-arg]


def test_gate_failure_leaves_no_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_stages(monkeypatch, _ok_report(facts_missing_unit=1))
    emb = Embedder(LenBackend(4), tmp_path / "cache", "m", 4)
    with pytest.raises(GateError):
        pipeline.build_index(tmp_path / "a.pdf", tmp_path / "idx", _settings(), emb)
    assert not (tmp_path / "idx" / "manifest.json").exists()
    assert not (tmp_path / "idx" / "chunks.jsonl").exists()
    # the failed report is kept for inspection in the staging dir
    assert "gate_error" in read_report(tmp_path / "idx" / ".tmp")


def test_failed_rebuild_keeps_previous_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "idx"
    emb = Embedder(LenBackend(4), tmp_path / "cache", "m", 4)
    _fake_stages(monkeypatch, _ok_report())
    m = pipeline.build_index(tmp_path / "a.pdf", out, _settings(), emb)
    assert read_manifest(out) == m and not (out / ".tmp").exists()
    assert (out / "build" / "extract.json").exists()
    before = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}

    _fake_stages(monkeypatch, _ok_report(kpi_golden_failed=["p5"]))
    with pytest.raises(GateError):
        pipeline.build_index(tmp_path / "a.pdf", out, _settings(), emb)
    assert {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()} == before

    def boom(out_dir: Path, embedder: Any) -> None:
        raise RuntimeError("embed down")

    _fake_stages(monkeypatch, _ok_report())
    monkeypatch.setattr(pipeline, "run_embed", boom)
    with pytest.raises(RuntimeError):
        pipeline.build_index(tmp_path / "a.pdf", out, _settings(), emb)
    assert {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()} == before


def test_gitignore_excludes_index_build_only() -> None:
    root = Path(__file__).resolve().parents[4]
    lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "index/build/" in lines and "index/.tmp/" in lines
    assert "index/" not in lines

import json
from pathlib import Path
from typing import Any

import pytest
from ircb.ingestion.pipeline import GateError
from ircb.retrieval.embed import Embedder
from ircb.settings import Settings
from ircb.storage import artefacts
from ircb.storage.vector_store import QdrantStore
from ircb_cli import main
from typer.testing import CliRunner

from cli_helpers import Backend, FakeService, build_mini_index, read_jsonl, write_input

runner = CliRunner()


@pytest.fixture
def fake_service() -> FakeService:
    return FakeService()


def _settings_for(tmp_path: Path, **kw: Any) -> Settings:
    return Settings(
        llm_model="x",
        index_dir=tmp_path / "index",
        qdrant_path=str(tmp_path / "qdrant"),
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        **kw,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(main, "_settings", lambda require_llm=True: settings)


def test_ingest_gate_error_prints_report_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(pdf: Path, out: Path, settings: Settings, embedder: Any = None) -> None:
        raise GateError("facts missing unit: 3")

    monkeypatch.setattr(main, "build_index", boom)
    _patch_settings(monkeypatch, Settings(llm_model="x"))
    out = tmp_path / "idx"
    r = runner.invoke(main.app, ["ingest", str(tmp_path / "x.pdf"), "--out", str(out)])
    assert r.exit_code == 1
    assert "facts missing unit: 3" in r.output
    assert str(out / ".tmp" / "ingest_report.json") in r.output.replace("\n", "")


def test_batch_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_service: FakeService) -> None:
    monkeypatch.setattr(main, "_service_factory", lambda settings: fake_service)
    _patch_settings(monkeypatch, Settings(llm_model="x"))
    src = write_input(tmp_path, [{"id": "a", "question": "q"}])
    out = tmp_path / "o.jsonl"
    r = runner.invoke(main.app, ["batch", str(src), "--out", str(out), "--concurrency", "2"])
    assert r.exit_code == 0, r.output
    assert [x["status"] for x in read_jsonl(out)] == ["answered"]


def test_chat_command_wires_service_and_repl(
    monkeypatch: pytest.MonkeyPatch, fake_service: FakeService
) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(main, "_service_factory", lambda settings: fake_service)
    monkeypatch.setattr(main, "run_repl", lambda service: seen.append(service))
    _patch_settings(monkeypatch, Settings(llm_model="x"))
    r = runner.invoke(main.app, ["chat"])
    assert r.exit_code == 0, r.output
    assert seen == [fake_service]


def test_index_load_and_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build_mini_index(tmp_path / "index", 8)
    _patch_settings(monkeypatch, _settings_for(tmp_path, embed_dimensions=8))
    first = runner.invoke(main.app, ["index", "load"])
    again = runner.invoke(main.app, ["index", "load"])
    forced = runner.invoke(main.app, ["index", "load", "--force"])
    assert first.exit_code == 0 and "loaded" in first.output
    assert "already loaded" in again.output
    assert forced.exit_code == 0 and "loaded" in forced.output and "already" not in forced.output


def test_index_load_manifest_mismatch_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build_mini_index(tmp_path / "index", 8)
    _patch_settings(monkeypatch, _settings_for(tmp_path, embed_dimensions=16))
    r = runner.invoke(main.app, ["index", "load"])
    assert r.exit_code == 1 and "ircb index reembed" in r.output.replace("\n", " ")


def test_index_reembed_drops_and_recreates_collections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    idx = build_mini_index(tmp_path / "index", 8)
    _patch_settings(monkeypatch, _settings_for(tmp_path, embed_dimensions=8))
    assert runner.invoke(main.app, ["index", "load"]).exit_code == 0

    s16 = _settings_for(tmp_path, embed_dimensions=16)
    _patch_settings(monkeypatch, s16)
    monkeypatch.setattr(
        main,
        "_embedder_factory",
        lambda s: Embedder(Backend(16), tmp_path / "cache", s.embed_model, s.embed_dimensions),
    )
    r = runner.invoke(main.app, ["index", "reembed"])
    assert r.exit_code == 0, r.output
    m = artefacts.read_manifest(idx)
    assert m.embed_dimensions == 16 and all(len(v.dense) == 16 for v in artefacts.read_vectors(idx))
    store = QdrantStore(s16)
    try:
        assert store.dense_dim() == 16 and store.count("chunks") == 2
    finally:
        store.close()
    # the settings now match the manifest, so a plain load works and is a no-op
    assert "already loaded" in runner.invoke(main.app, ["index", "load"]).output


def _eval_dataset(tmp_path: Path) -> Path:
    rows = [
        {
            "id": "own-01",
            "category": "key_figures",
            "question": "Tổng tài sản 2025?",
            "gold_answer": "1.192 nghìn tỷ đồng",
            "gold_printed_pages": [5],
            "answerable": True,
            "split": "dev",
            "gold_values": [{"value": "1.192", "unit": "nghìn tỷ đồng"}],
        },
        {
            "id": "own-02",
            "category": "unanswerable",
            "question": "Giá vàng?",
            "gold_answer": "Không có",
            "gold_printed_pages": [],
            "answerable": False,
            "split": "test",
        },
    ]
    p = tmp_path / "ds.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def test_eval_command_with_run_answers_only_the_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_service: FakeService
) -> None:
    monkeypatch.setattr(main, "_service_factory", lambda settings: fake_service)
    _patch_settings(monkeypatch, Settings(llm_model="x", trace_dir=tmp_path / "traces"))
    batch_out = tmp_path / "batch.jsonl"
    r = runner.invoke(
        main.app,
        [
            "eval",
            "--split",
            "dev",
            "--run",
            "--dataset",
            str(_eval_dataset(tmp_path)),
            "--batch-out",
            str(batch_out),
            "--out-dir",
            str(tmp_path / "eval"),
        ],
    )
    assert r.exit_code == 0, r.output
    assert fake_service.questions == ["Tổng tài sản 2025?"]
    assert [x["id"] for x in read_jsonl(batch_out)] == ["own-01"]
    reports = list((tmp_path / "eval" / "reports").glob("*.json"))
    assert len(reports) == 1 and str(reports[0].name) in r.output.replace("\n", "")
    assert (tmp_path / "eval" / "scoring" / "score_sheet.csv").exists()


def test_eval_command_without_run_reads_existing_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_service(settings: Settings) -> None:
        raise AssertionError("eval without --run must not build the service")

    monkeypatch.setattr(main, "_service_factory", no_service)
    _patch_settings(monkeypatch, Settings(llm_model="x", trace_dir=tmp_path / "traces"))
    batch_out = tmp_path / "batch.jsonl"
    batch_out.write_text(
        json.dumps(
            {"id": "own-02", "status": "refused", "answer": "Không có", "citations": [], "trace_id": "t"}
        )
        + "\n",
        encoding="utf-8",
    )
    r = runner.invoke(
        main.app,
        [
            "eval",
            "--split",
            "all",
            "--dataset",
            str(_eval_dataset(tmp_path)),
            "--batch-out",
            str(batch_out),
            "--out-dir",
            str(tmp_path / "eval"),
        ],
    )
    assert r.exit_code == 0, r.output


def test_eval_command_without_run_and_missing_batch_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_settings(monkeypatch, Settings(llm_model="x"))
    r = runner.invoke(
        main.app,
        ["eval", "--dataset", str(_eval_dataset(tmp_path)), "--batch-out", str(tmp_path / "nope.jsonl")],
    )
    assert r.exit_code == 2 and "--run" in r.output


# --- I7: grader-facing errors are one clear line, never a traceback -----------


def _one_clear_line(r: Any, code: int, *needles: str) -> None:
    assert r.exit_code == code, r.output
    assert isinstance(r.exception, SystemExit), repr(r.exception)  # no uncaught exception
    assert "Traceback" not in r.output
    flat = r.output.replace("\n", " ")
    for n in needles:
        assert n in flat, (n, r.output)


@pytest.mark.parametrize("cmd", ["chat", "batch"])
def test_missing_index_is_a_clear_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cmd: str) -> None:
    _patch_settings(monkeypatch, _settings_for(tmp_path))  # tmp_path/index does not exist
    src = write_input(tmp_path, [{"id": "a", "question": "q"}])
    args = ["chat"] if cmd == "chat" else ["batch", str(src), "--out", str(tmp_path / "o.jsonl")]
    r = runner.invoke(main.app, args)
    _one_clear_line(r, 1, "ircb ingest", str(tmp_path / "index"))
    assert len(r.output.strip().splitlines()) == 1


@pytest.mark.parametrize("cmd", ["chat", "batch"])
def test_manifest_mismatch_is_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cmd: str
) -> None:
    build_mini_index(tmp_path / "index", 8)
    _patch_settings(monkeypatch, _settings_for(tmp_path, embed_dimensions=16))
    src = write_input(tmp_path, [{"id": "a", "question": "q"}])
    args = ["chat"] if cmd == "chat" else ["batch", str(src), "--out", str(tmp_path / "o.jsonl")]
    r = runner.invoke(main.app, args)
    _one_clear_line(r, 1, "ircb index reembed")
    assert len(r.output.strip().splitlines()) == 1


def test_index_load_missing_index_is_a_clear_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, _settings_for(tmp_path))
    _one_clear_line(runner.invoke(main.app, ["index", "load"]), 1, "ircb ingest")


def test_invalid_settings_is_one_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("LLM_MODEL", raising=False)
    r = runner.invoke(main.app, ["chat"])
    _one_clear_line(r, 2, "LLM_MODEL")
    assert len(r.output.strip().splitlines()) == 1


def test_batch_malformed_json_array_is_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_service: FakeService
) -> None:
    monkeypatch.setattr(main, "_service_factory", lambda settings: fake_service)
    _patch_settings(monkeypatch, Settings(llm_model="x"))
    src = tmp_path / "in.json"
    src.write_text('[{"id": "a", "question": "q"},', encoding="utf-8")
    r = runner.invoke(main.app, ["batch", str(src), "--out", str(tmp_path / "o.jsonl")])
    _one_clear_line(r, 2, "invalid JSON", str(src))
    assert not (tmp_path / "o.jsonl").exists()

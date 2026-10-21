import json
from pathlib import Path

import pytest
from ircb_cli.batch import run_batch

from cli_helpers import FakeService, read_jsonl, write_input


@pytest.fixture
def fake_service() -> FakeService:
    return FakeService()


@pytest.fixture
def fake_service_llm_down() -> FakeService:
    return FakeService(status="error")


def test_batch_bad_row_does_not_abort(tmp_path: Path, fake_service: FakeService) -> None:
    rows_in = [{"id": "a", "question": ""}, {"id": "b", "question": "Tổng tài sản?"}, {"oops": 1}]
    rows = read_jsonl(run_batch(write_input(tmp_path, rows_in), tmp_path / "o.jsonl", fake_service))
    assert [r["status"] for r in rows] == ["error", "answered", "error"]
    assert rows[0]["id"] == "a" and rows[0]["error"] and "answer" not in rows[0]
    assert rows[2]["id"] is None


def test_batch_llm_error_row(tmp_path: Path, fake_service_llm_down: FakeService) -> None:
    src = write_input(tmp_path, [{"id": "a", "question": "x"}])
    rows = read_jsonl(run_batch(src, tmp_path / "o.jsonl", fake_service_llm_down))
    assert rows[0]["status"] == "error"


def test_batch_multi_turn(tmp_path: Path, fake_service: FakeService) -> None:
    src = write_input(tmp_path, [{"id": "m1", "turns": ["Tổng tài sản 2025?", "còn năm trước thì sao?"]}])
    rows = read_jsonl(run_batch(src, tmp_path / "o.jsonl", fake_service))
    assert [r["turn_index"] for r in rows] == [0, 1] and fake_service.prev_states[1] is not None
    assert fake_service.prev_states[0] is None
    assert fake_service.histories[1] == [("Tổng tài sản 2025?", rows[0]["answer"])]
    assert [r["id"] for r in rows] == ["m1", "m1"]


def test_batch_output_fields(tmp_path: Path, fake_service: FakeService) -> None:
    src = write_input(tmp_path, [{"id": "a", "question": "q"}])
    (row,) = read_jsonl(run_batch(src, tmp_path / "o.jsonl", fake_service))
    keys = {"id", "status", "answer", "citations", "claims", "calcs", "latency_ms", "cost_usd", "trace_id"}
    assert set(row) == keys
    assert row["cost_usd"] == "0.0012" and row["latency_ms"] == {"total": 12} and row["trace_id"] == "t1"
    assert row["citations"] == [{"printed_pages": [5], "label": "[tr. 5]"}]


def test_batch_unexpected_exception_is_recorded(tmp_path: Path) -> None:
    svc = FakeService(boom=KeyError("bug"))
    src = write_input(tmp_path, [{"id": "a", "question": "boom"}, {"id": "b", "question": "ok"}])
    rows = read_jsonl(run_batch(src, tmp_path / "o.jsonl", svc))
    assert rows[0] == {"id": "a", "status": "error", "error": "KeyError: 'bug'"}
    assert rows[1]["status"] == "answered"


def test_batch_jsonl_input_with_broken_lines(tmp_path: Path, fake_service: FakeService) -> None:
    lines = [json.dumps({"id": "a", "question": "q"}), "{not json", "", "[1]"]
    rows = read_jsonl(run_batch(write_input(tmp_path, lines, jsonl=True), tmp_path / "o.jsonl", fake_service))
    assert [r["status"] for r in rows] == ["answered", "error", "error"]


def test_batch_concurrency_keeps_input_order(tmp_path: Path, fake_service: FakeService) -> None:
    src = write_input(tmp_path, [{"id": f"q{i}", "question": f"q{i}"} for i in range(8)])
    rows = read_jsonl(run_batch(src, tmp_path / "sub" / "o.jsonl", fake_service, concurrency=4))
    assert [r["id"] for r in rows] == [f"q{i}" for i in range(8)]


def test_batch_bad_turns(tmp_path: Path, fake_service: FakeService) -> None:
    src = write_input(tmp_path, [{"id": "m", "turns": []}, {"id": "n", "turns": ["ok", 3]}])
    rows = read_jsonl(run_batch(src, tmp_path / "o.jsonl", fake_service))
    assert [r["status"] for r in rows] == ["error", "error"]


class _ClaimService(FakeService):
    def __init__(self, status: str = "partial", calc_owner: str = "bad") -> None:
        super().__init__(status)
        self.calc_owner = calc_owner  # which claim's text used {c1}

    def ask(self, message, prev_state=None, history=None):  # type: ignore[no-untyped-def]
        from decimal import Decimal

        from ircb.domain.models import CalcResult, VerifiedClaim

        a = super().ask(message, prev_state, history)
        ok = VerifiedClaim(
            text="Tổng tài sản đạt 1.192 nghìn tỷ đồng.",
            sources=["chunk:k"],
            printed_pages=[5],
            ok=True,
            failed_rule=None,
            calc_ids=["c1"] if self.calc_owner == "ok" else [],
        )
        bad = VerifiedClaim(
            text="Lợi nhuận trước thuế đạt 45.000 tỷ đồng.",
            sources=["chunk:k"],
            printed_pages=[5],
            ok=False,
            failed_rule="number_mismatch",
            calc_ids=["c1"] if self.calc_owner == "bad" else [],
        )
        calc = CalcResult(
            id="c1",
            ok=True,
            value=Decimal("21.8"),
            unit="%",
            rendered="tăng 21,8%",
            formula="x",
            operand_fact_ids=["f"],
            error=None,
        )
        return a.model_copy(update={"claims": [ok, bad], "calcs": [calc]})


def test_batch_row_never_carries_failed_claim_text(tmp_path: Path) -> None:
    src = write_input(tmp_path, [{"id": "a", "question": "q"}])
    out = run_batch(src, tmp_path / "o.jsonl", _ClaimService())
    assert "45.000" not in out.read_text(encoding="utf-8")
    (row,) = read_jsonl(out)
    assert row["claims"][0]["text"] == "Tổng tài sản đạt 1.192 nghìn tỷ đồng."
    assert row["claims"][1] == {
        "sources": ["chunk:k"],
        "printed_pages": [5],
        "ok": False,
        "failed_rule": "number_mismatch",
        "calc_ids": ["c1"],
    }


def test_batch_refused_row_has_no_claims_or_calcs(tmp_path: Path) -> None:
    src = write_input(tmp_path, [{"id": "a", "question": "q"}])
    (row,) = read_jsonl(run_batch(src, tmp_path / "o.jsonl", _ClaimService(status="refused")))
    assert row["status"] == "refused" and row["claims"] == [] and row["calcs"] == []


def test_batch_drops_calc_of_failed_claim(tmp_path: Path) -> None:
    src = write_input(tmp_path, [{"id": "a", "question": "q"}])
    out = run_batch(src, tmp_path / "o.jsonl", _ClaimService(calc_owner="bad"))
    (row,) = read_jsonl(out)
    assert row["calcs"] == []
    assert "tăng 21,8%" not in out.read_text(encoding="utf-8")


def test_batch_keeps_calc_of_passed_claim(tmp_path: Path) -> None:
    src = write_input(tmp_path, [{"id": "a", "question": "q"}])
    (row,) = read_jsonl(run_batch(src, tmp_path / "o.jsonl", _ClaimService(calc_owner="ok")))
    assert [c["id"] for c in row["calcs"]] == ["c1"]

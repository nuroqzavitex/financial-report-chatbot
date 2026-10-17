import csv
import json
from pathlib import Path
from typing import Any

import pytest

from eval.runners.judge_agreement import judge_agreement
from eval.runners.run_eval import (
    SCORE_SHEET_COLUMNS,
    calibrate_threshold,
    calibration_rows,
    run_eval,
    score_row,
)

# ----------------------------------------------------------------- helpers


def gold(
    pages: list[int] | None = None,
    answerable: bool = True,
    values: list[tuple[str, str]] | None = None,
    direction: str | None = None,
    **kw: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": kw.pop("id", "own-01"),
        "category": kw.pop("category", "key_figures"),
        "question": kw.pop("question", "Tổng tài sản 2025?"),
        "gold_answer": kw.pop("gold_answer", "1.192 nghìn tỷ đồng"),
        "gold_printed_pages": pages if pages is not None else ([5] if answerable else []),
        "answerable": answerable,
        "split": kw.pop("split", "dev"),
    }
    if values:
        row["gold_values"] = [{"value": v, "unit": u} for v, u in values]
    if direction:
        row["direction"] = direction
    row.update(kw)
    return row


def out(
    status: str = "answered",
    answer: str = "",
    citations: list[list[int]] | None = None,
    **kw: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": kw.pop("id", "own-01"),
        "status": status,
        "answer": answer,
        "citations": [
            {"printed_pages": p, "label": "[tr. " + ", ".join(map(str, p)) + "]"} for p in citations or []
        ],
        "claims": [],
        "calcs": [],
        "latency_ms": {"total": 10},
        "cost_usd": "0.001",
        "trace_id": kw.pop("trace_id", "t-1"),
    }
    row.update(kw)
    return row


def csv_rows(labels: list[str]) -> list[dict[str, str]]:
    return [{"id": f"own-{i:02d}", "manual_label": lab} for i, lab in enumerate(labels, start=1)]


def ragas(labels: list[str]) -> dict[str, Any]:
    return {"rows": [{"id": f"own-{i:02d}", "label": lab} for i, lab in enumerate(labels, start=1)]}


def hit(score: float | None, branches: int = 1) -> dict[str, Any]:
    return {"dense_score": score, "branches": branches}


def dev_rows_fixture() -> list[dict[str, Any]]:
    """Answerable rows score 0.55-0.80, unanswerable 0.10-0.30: a separable dev set."""
    rows: list[dict[str, Any]] = []
    for i, s in enumerate([0.55, 0.6, 0.62, 0.7, 0.75, 0.8, 0.58, 0.66]):
        rows.append(
            {
                "id": f"a{i}",
                "answerable": True,
                "status": "answered",
                "gate_passed": True,
                "gate_hits": [hit(s)],
            }
        )
    for i, s in enumerate([0.1, 0.2, 0.25, 0.3, 0.15]):
        rows.append(
            {
                "id": f"u{i}",
                "answerable": False,
                "status": "answered",
                "gate_passed": True,
                "gate_hits": [hit(s)],
            }
        )
    return rows


# ----------------------------------------------------------------- brief tests


def test_citation_hit() -> None:
    assert score_row(gold(pages=[5]), out(citations=[[5], [297]])).citation_hit


def test_refusal_ok() -> None:
    assert score_row(gold(answerable=False), out(status="refused")).refusal_ok


def test_partial_not_refusal() -> None:
    assert score_row(gold(answerable=True), out(status="partial")).refusal_ok


def test_unit_ok_with_scale() -> None:
    assert score_row(
        gold(values=[("1.192", "nghìn tỷ đồng")]), out(answer="1.192.344.137 triệu đồng")
    ).unit_ok


def test_kappa_perfect() -> None:
    assert judge_agreement(csv_rows(["yes", "no"]), ragas(["yes", "no"]))["kappa"] == 1.0


def test_calibrate_respects_targets() -> None:
    t = calibrate_threshold(dev_rows_fixture())
    assert 0 < t < 1


# ----------------------------------------------------------------- score_row details


def test_citation_miss_when_a_gold_page_is_absent() -> None:
    assert not score_row(gold(pages=[374, 375]), out(citations=[[374]])).citation_hit
    assert score_row(gold(pages=[374, 375]), out(citations=[[374, 375]])).citation_hit


def test_refusing_answerable_is_not_ok_and_answering_unanswerable_is_not_ok() -> None:
    assert not score_row(gold(answerable=True), out(status="refused")).refusal_ok
    assert not score_row(gold(answerable=False), out(status="answered", answer="32,5")).refusal_ok


def test_unit_wrong_scale_fails() -> None:
    g = gold(values=[("1.192", "nghìn tỷ đồng")])
    assert score_row(g, out(answer="Tổng tài sản 1.192 tỷ đồng")).unit_ok is False
    assert score_row(g, out(answer="Tổng tài sản 1.192 nghìn tỷ đồng")).unit_ok is True


def test_unit_ok_precise_gold_vs_rounded_answer() -> None:
    g = gold(values=[("978.799", "tỷ đồng")])
    assert score_row(g, out(answer="978.798.549 triệu đồng")).unit_ok is True


def test_unit_ok_percent_and_non_money_units() -> None:
    assert score_row(gold(values=[("18,2", "%")]), out(answer="tăng 18,2% N/N")).unit_ok is True
    assert score_row(gold(values=[("18,0", "triệu khách hàng")]), out(answer="18,0 triệu khách hàng")).unit_ok
    assert (
        score_row(gold(values=[("18,0", "triệu khách hàng")]), out(answer="18,0 khách hàng")).unit_ok is False
    )
    assert score_row(gold(values=[("0,31", "điểm %")]), out(answer="chênh 0,31 điểm %")).unit_ok is True


def test_unit_ok_none_without_gold_values() -> None:
    assert score_row(gold(), out(answer="Khối Ngân hàng Bán lẻ")).unit_ok is None


def test_suggested_correct() -> None:
    g = gold(values=[("32,5", "nghìn tỷ đồng"), ("18,2", "%")], direction="tăng")
    assert score_row(g, out(answer="LNTT đạt 32,5 nghìn tỷ đồng, tăng 18,2%")).suggested_correct == "yes"
    assert score_row(g, out(answer="LNTT đạt 32,5 nghìn tỷ đồng")).suggested_correct == "partial"
    assert score_row(g, out(answer="LNTT đạt 32,5 nghìn tỷ đồng, 18,2%")).suggested_correct == "partial"
    assert score_row(g, out(answer="LNTT đạt 30 nghìn tỷ đồng")).suggested_correct == "no"
    assert score_row(g, out(status="refused", answer="Không có")).suggested_correct == "no"
    assert score_row(gold(answerable=False), out(status="refused")).suggested_correct == "yes"
    assert score_row(gold(), out(answer="Khối Ngân hàng Bán lẻ")).suggested_correct == "?"


def test_direction_word_must_match() -> None:
    g = gold(values=[("13,7", "%")], direction="giảm")
    assert score_row(g, out(answer="CIR 13,7%, tăng so với 2024")).suggested_correct == "partial"
    assert score_row(g, out(answer="CIR 13,7%, giảm 0,5%")).suggested_correct == "yes"


# ----------------------------------------------------------------- judge agreement


def test_kappa_and_agreement_values(tmp_path: Path) -> None:
    manual = tmp_path / "sheet.csv"
    with manual.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "manual_label"])
        w.writeheader()
        for i, lab in enumerate(["yes", "yes", "no", "partial", ""], start=1):
            w.writerow({"id": f"own-{i:02d}", "manual_label": lab})
    rj = tmp_path / "ragas.json"
    rj.write_text(json.dumps(ragas(["yes", "no", "no", "no", "yes"])), encoding="utf-8")
    r = judge_agreement(manual, rj)
    # unlabeled own-05 skipped; partial counts as "no": manual y,y,n,n vs judge y,n,n,n -> 3/4
    assert r["agreement"] == 0.75
    assert r["kappa"] == pytest.approx(0.5)
    assert r["n"] == 4


# ----------------------------------------------------------------- calibration


def test_calibration_meets_targets_on_separable_rows() -> None:
    rows = dev_rows_fixture()
    t = calibrate_threshold(rows)
    assert 0.3 < t <= 0.55


def test_calibration_keeps_guard_refusals_and_branch_agreement() -> None:
    rows = dev_rows_fixture() + [
        {"id": "g", "answerable": False, "status": "refused", "gate_passed": None, "gate_hits": []},
        {
            "id": "b",
            "answerable": True,
            "status": "answered",
            "gate_passed": True,
            "gate_hits": [hit(0.05, 2)],
        },
    ]
    t = calibrate_threshold(rows)
    assert 0.3 < t <= 0.55


def test_calibration_rows_from_batch_and_traces() -> None:
    golds = [gold(id="own-01", split="dev"), gold(id="own-02", answerable=False, split="dev")]
    batch = [out(id="own-01", trace_id="t1"), out(id="own-02", status="refused", trace_id="t2")]
    traces = {
        "t1": {"records": {"gate": {"passed": True, "threshold": 0.35, "hits": [hit(0.7)]}}},
        "t2": {"records": {"guard": "period"}},
    }
    rows = calibration_rows(golds, batch, traces)
    assert rows == [
        {
            "id": "own-01",
            "answerable": True,
            "status": "answered",
            "gate_passed": True,
            "gate_hits": [hit(0.7)],
        },
        {"id": "own-02", "answerable": False, "status": "refused", "gate_passed": None, "gate_hits": []},
    ]


# ----------------------------------------------------------------- run_eval end-to-end (fixtures, no API)


def _write_jsonl(p: Path, rows: list[dict[str, Any]]) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _trace(tid: str, status: str, chunk_pages: list[list[int]], **records: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "status": status,
        "prompt_version": "pv123",
        "models": {"rewriter": "small", "generator": "big"},
        "retrieval": {"chunks": [], "facts": [], "chunk_pages": chunk_pages, "fact_pages": []},
        "gate": {"passed": True, "threshold": 0.35, "hits": [hit(0.6)]},
        "retrieval_recovered": False,
        "verifier": [{"ok": True, "failed_rule": None}],
        "calcs": {},
    }
    rec.update(records)
    return {
        "trace_id": tid,
        "latency_ms": {"rewrite": 100.0, "generate": 900.0, "total": 1200.0},
        "records": rec,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost_usd": "0.002"},
    }


@pytest.fixture
def eval_fixture(tmp_path: Path) -> dict[str, Path]:
    dataset = _write_jsonl(
        tmp_path / "ds.jsonl",
        [
            gold(id="own-01", category="key_figures", values=[("1.192", "nghìn tỷ đồng")], pages=[5]),
            gold(id="own-02", category="unanswerable", answerable=False, split="dev"),
            gold(
                id="own-03",
                category="multi_turn",
                pages=[14],
                values=[("978.799", "tỷ đồng")],
                turns=["Tổng tài sản 2025?", "Còn năm trước?"],
                question="Còn năm trước?",
            ),
            gold(id="own-04", category="key_figures", split="test", pages=[48]),
        ],
    )
    batch = _write_jsonl(
        tmp_path / "batch.jsonl",
        [
            out(
                id="own-01",
                answer="Tổng tài sản 1.192.344.137 triệu đồng [tr. 297]",
                citations=[[297]],
                trace_id="t1",
            ),
            out(id="own-02", status="refused", answer="Không có trong báo cáo", trace_id="t2"),
            out(
                id="own-03",
                answer="1.192 nghìn tỷ đồng [tr. 5]",
                citations=[[5]],
                trace_id="t3a",
                turn_index=0,
            ),
            out(
                id="own-03", answer="978.799 tỷ đồng [tr. 14]", citations=[[14]], trace_id="t3b", turn_index=1
            ),
            out(id="own-04", answer="x", trace_id="t4"),
        ],
    )
    traces = tmp_path / "traces"
    _write_jsonl(
        traces / "2026-10-17.jsonl",
        [
            _trace(
                "t1",
                "answered",
                [[297], [5], [14]],
                retrieval_recovered=True,
                verifier=[{"ok": True, "failed_rule": None}, {"ok": False, "failed_rule": "number_mismatch"}],
            ),
            _trace("t2", "refused", [], gate={"passed": False, "threshold": 0.35, "hits": [hit(0.1)]}),
            _trace("t3a", "answered", [[5]]),
            _trace("t3b", "answered", [[297], [14]], calcs={"c1": {"ok": False, "error": "unit_mismatch"}}),
            _trace("t4", "answered", [[48]]),
        ],
    )
    return {"dataset": dataset, "batch": batch, "traces": traces, "out": tmp_path / "eval"}


def test_run_eval_writes_report_and_score_sheet(eval_fixture: dict[str, Path]) -> None:
    f = eval_fixture
    rep = run_eval(
        f["dataset"], "dev", f["out"], batch_out=f["batch"], trace_dir=f["traces"], commit="abc1234"
    )
    assert rep.report_path.parent == f["out"] / "reports"
    assert rep.report_path.name.endswith("_abc1234.json")
    data = json.loads(rep.report_path.read_text(encoding="utf-8"))
    assert data["meta"]["commit"] == "abc1234"
    assert data["meta"]["prompt_version"] == "pv123"
    assert data["meta"]["model"] == {"rewriter": "small", "generator": "big"}
    assert "index_version" in data["meta"]
    assert data["meta"]["n_rows"] == 3  # test row own-04 excluded

    cat = data["by_category"]
    assert cat["key_figures"]["n"] == 1
    assert cat["key_figures"]["citation_hit"] == 0.0  # cited 297, gold 5
    assert cat["key_figures"]["unit_ok"] == 1.0
    assert cat["unanswerable"]["refusal_ok"] == 1.0
    assert cat["multi_turn"]["citation_hit"] == 1.0  # scored on the last turn

    # Recall@8 / MRR over rows with gold pages: own-01 page 5 at rank 2, own-03 page 14 at rank 2
    assert data["retrieval"]["recall_at_8"] == 1.0
    assert data["retrieval"]["mrr"] == pytest.approx(0.5)

    ops = data["ops"]
    assert ops["n_traces"] == 4  # both turns of own-03 count
    assert ops["retrieval_recovered_rate"] == 0.25
    assert ops["blocked_claims_by_rule"] == {"number_mismatch": 1}
    assert ops["calc_fail_by_error"] == {"unit_mismatch": 1}
    assert ops["latency_ms"]["generate"]["p50"] == 900.0
    assert ops["usd_per_query"] == "0.002"

    with rep.score_sheet_path.open(encoding="utf-8") as fh:
        sheet = list(csv.DictReader(fh))
    assert rep.score_sheet_path == f["out"] / "scoring" / "score_sheet.csv"
    assert list(sheet[0].keys()) == SCORE_SHEET_COLUMNS
    assert [r["id"] for r in sheet] == ["own-01", "own-02", "own-03"]
    assert all(r["manual_label"] == "" for r in sheet)
    assert sheet[2]["system_answer"] == "978.799 tỷ đồng [tr. 14]"


def test_run_eval_missing_output_is_scored_not_crashed(eval_fixture: dict[str, Path], tmp_path: Path) -> None:
    f = eval_fixture
    empty = _write_jsonl(tmp_path / "empty.jsonl", [out(id="zzz")])
    rep = run_eval(f["dataset"], "all", f["out"], batch_out=empty, trace_dir=f["traces"], commit="c")
    data = json.loads(rep.report_path.read_text(encoding="utf-8"))
    assert data["meta"]["n_rows"] == 4
    assert data["overall"]["missing"] == 4


def test_run_eval_meta_comes_from_the_scored_traces_not_a_stale_one(
    eval_fixture: dict[str, Path],
) -> None:
    """Daily trace files accumulate chat sessions and older runs; meta must describe this batch only."""
    f = eval_fixture
    stale = _trace(
        "t-old", "answered", [[1]], prompt_version="stale-pv", models={"rewriter": "old", "generator": "old"}
    )
    _write_jsonl(f["traces"] / "2026-01-01.jsonl", [stale])  # sorts (and loads) before the run's file
    rep = run_eval(f["dataset"], "dev", f["out"], batch_out=f["batch"], trace_dir=f["traces"], commit="c")
    assert rep.meta["prompt_version"] == "pv123"
    assert rep.meta["model"] == {"rewriter": "small", "generator": "big"}


def test_run_eval_meta_records_every_prompt_version_and_model_seen(
    eval_fixture: dict[str, Path],
) -> None:
    f = eval_fixture
    lines = [
        json.loads(x) for x in (f["traces"] / "2026-10-17.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    lines[0]["records"]["prompt_version"] = "pv999"
    lines[0]["records"]["models"] = {"rewriter": "small", "generator": "bigger"}
    _write_jsonl(f["traces"] / "2026-10-17.jsonl", lines)
    rep = run_eval(f["dataset"], "dev", f["out"], batch_out=f["batch"], trace_dir=f["traces"], commit="c")
    assert rep.meta["prompt_version"] == ["pv123", "pv999"]
    assert rep.meta["model"] == [
        {"rewriter": "small", "generator": "big"},
        {"rewriter": "small", "generator": "bigger"},
    ]

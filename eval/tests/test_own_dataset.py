"""Schema and composition checks of eval/datasets/own_questions.jsonl (spec §10.0.1, §10.4)."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from ircb.domain.numbers_vn import parse_vn

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "eval" / "datasets" / "own_questions.jsonl"
SAMPLES = ROOT / "data" / "sample_questions.json"

EXPECTED = {
    "key_figures": 4,
    "segment_performance": 4,
    "direction": 2,
    "financial_statements": 8,
    "parent_child_rows": 3,
    "gutter_table": 2,
    "definition_or_rounding": 4,
    "multi_turn": 5,
    "calculation": 4,
    "partial": 2,
    "terminology": 3,
    "narrative": 3,
    "unanswerable": 6,
}
REQUIRED = {
    "id",
    "category",
    "question",
    "gold_answer",
    "gold_printed_pages",
    "answerable",
    "split",
    "gold_source",
    "gold_checked_by",
}


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_category_counts(rows: list[dict[str, Any]]) -> None:
    assert Counter(r["category"] for r in rows) == EXPECTED


def test_required_fields_and_unique_ids(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        assert REQUIRED <= r.keys(), r["id"]
        assert r["split"] in {"dev", "test"}
        assert r["gold_checked_by"] == "claude-first-pass"
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)) and all(i.startswith("own-") for i in ids)


def test_split_is_half_half_within_each_category(rows: list[dict[str, Any]]) -> None:
    for cat in EXPECTED:
        splits = Counter(r["split"] for r in rows if r["category"] == cat)
        assert abs(splits["dev"] - splits["test"]) <= 1, cat


def test_answerable_rows_have_pages_and_unanswerable_have_none(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        if r["answerable"]:
            assert r["gold_printed_pages"] and all(
                isinstance(p, int) and 1 <= p <= 393 for p in r["gold_printed_pages"]
            )
        else:
            assert r["gold_printed_pages"] == [] and r["category"] == "unanswerable"


def test_gold_values_parse(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        for gv in r.get("gold_values", []):
            parse_vn(gv["value"])
            assert gv["unit"].strip(), r["id"]


def test_multi_turn_rows_have_turns_and_question_is_last_turn(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        if r["category"] == "multi_turn":
            assert len(r["turns"]) >= 2 and r["question"] == r["turns"][-1]
        else:
            assert "turns" not in r


def test_calculation_has_formula_and_one_nested(rows: list[dict[str, Any]]) -> None:
    calc = [r for r in rows if r["category"] == "calculation"]
    assert all(r.get("formula") for r in calc)
    assert sum(1 for r in calc if r.get("nested")) == 1


def test_direction_values(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        if "direction" in r:
            assert r["direction"] in {"tăng", "giảm"}
    assert all("direction" in r for r in rows if r["category"] == "direction")


# function words and the bank name carry no topic; digits are masked so "2027" vs "2028" still collide
_STOP = {
    "của",
    "là",
    "bao",
    "nhiêu",
    "techcombank",
    "năm",
    "tại",
    "ngày",
    "cuối",
    "và",
    "có",
    "trong",
    "theo",
    "đạt",
    "được",
    "the",
    "0",
}


def _topic_tokens(q: str) -> set[str]:
    masked = re.sub(r"\d+", "0", q.lower())
    return {t for t in re.findall(r"\w+", masked) if t not in _STOP}


def near_duplicate(a: str, b: str, threshold: float = 0.8) -> bool:
    """Same text after masking digits, or Jaccard >= threshold over topic tokens."""
    if re.sub(r"\d+", "0", a.strip().lower()) == re.sub(r"\d+", "0", b.strip().lower()):
        return True
    ta, tb = _topic_tokens(a), _topic_tokens(b)
    return bool(ta | tb) and len(ta & tb) / len(ta | tb) >= threshold


def test_near_duplicate_detector_catches_paraphrases() -> None:
    sq10 = "Techcombank dự báo lợi nhuận trước thuế năm 2027 là bao nhiêu?"
    sq03 = "Tổng tài sản của Techcombank tại ngày 31/12/2025 là bao nhiêu?"
    assert near_duplicate("Techcombank dự báo lợi nhuận trước thuế năm 2028 là bao nhiêu?", sq10)
    assert near_duplicate("Tổng tài sản của Techcombank cuối năm 2025 là bao nhiêu?", sq03)
    assert not near_duplicate("Kế hoạch lợi nhuận trước thuế năm 2026 của Techcombank là bao nhiêu?", sq10)


def test_no_duplicate_of_sample_questions(rows: list[dict[str, Any]]) -> None:
    if not SAMPLES.exists():
        pytest.skip("data/sample_questions.json not present")
    samples = [q["question"] for q in json.loads(SAMPLES.read_text(encoding="utf-8"))]
    dups = [
        (r["id"], q, sq)
        for r in rows
        for q in r.get("turns", [r["question"]])
        for sq in samples
        if near_duplicate(q, sq)
    ]
    assert dups == []


def test_gold_answer_scores_itself(rows: list[dict[str, Any]]) -> None:
    """The gold answer must pass the automatic checks against its own gold values and direction."""
    from eval.runners.run_eval import score_row

    for r in rows:
        fake = {
            "status": "refused" if not r["answerable"] else "answered",
            "answer": r["gold_answer"],
            "citations": [{"printed_pages": r["gold_printed_pages"]}] if r["gold_printed_pages"] else [],
        }
        s = score_row(r, fake)
        assert s.citation_hit and s.refusal_ok, r["id"]
        assert s.unit_ok in (True, None), r["id"]
        assert s.suggested_correct in ("yes", "?"), r["id"]

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from factories import fact
from ircb.answering.calc import execute_calcs
from ircb.answering.verifier import DIRECTION_WORDS, verify_claims
from ircb.domain.models import CalcResult, CalcSpec, Chunk, ClaimOut
from ircb.retrieval.hybrid import Context

ROOT = Path(__file__).resolve().parents[4]
ADVERSARIAL = ROOT / "eval" / "datasets" / "adversarial.jsonl"
ALL_RULES = {
    "source_missing",
    "evidence_not_substring",
    "number_mismatch",
    "direction_near_placeholder",
    "direction_mismatch",
    "direction_unknown",
    "calc_failed",
}

KPI_TEXT = (
    "Tổng tài sản 1.192 Nghìn tỷ đồng, tăng 21,8% so với cùng kỳ\n"
    "Tổng thu nhập hoạt động 53,4 Nghìn tỷ đồng, CAGR 16,5% giai đoạn 2021-2025\n"
    "Lợi nhuận trước thuế 32,5 Nghìn tỷ đồng, tăng 17,3% so với cùng kỳ"
)
# synthetic prose for the round-4 direction-binding probes (each line is quoted as evidence)
PROSE_TEXT = (
    "Tổng tài sản so với năm trước tăng 21,8%. Cho vay khách hàng 757 nghìn tỷ đồng.\n"
    "Tổng tài sản đạt 1.192, dư nợ xấu giảm 3%\n"
    "Năm 2025 của ngân hàng: tổng tài sản tăng 21,8%\n"
    "Lợi nhuận trên tổng tài sản (ROA) tăng 0,2 điểm %\n"
    "Tổng tài sản có rủi ro tăng 5%\n"
    "Tổng tài sản không tăng\n"
    "Chi phí thuế tăng 10%\n"
    "ROA đạt 1,5%"
)
# real p.5 KPI chunk sentence (chunks_from_kpi over the PDF)
REAL_P5_LINE = "Tổng tài sản: 1.192 nghìn tỷ đồng, tăng 21,8% so với năm trước"
TABLE_TEXT = (
    "Báo cáo tình hình tài chính hợp nhất (1)\n"
    "Cho vay khách hàng tại ngày 31/12/2025: 757.118.751\n"
    "Cho vay khách hàng (TM 9) tại ngày 31/12/2025: 767.617.129"
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mk_chunk(**kw: Any) -> Chunk:
    base: dict[str, Any] = {
        "chunk_id": "p3R_k",
        "doc_id": "tcb-ar-2025",
        "pdf_page": 3,
        "half": "R",
        "printed_pages": [5],
        "chapter": None,
        "statement": None,
        "note_no": None,
        "content_type": "kpi",
        "unit": None,
        "text": KPI_TEXT,
        "fact_ids": [],
        "bbox": [0.0, 0.0, 1.0, 1.0],
    }
    base.update(kw)
    return Chunk(**base)


def money(fid: str, label: str, value: str, period: str, **kw: Any) -> Any:
    v = Decimal(value)
    return fact(
        fact_id=fid,
        label=label,
        label_norm=label.lower(),
        value=v,
        unit="triệu đồng",
        value_vnd=v * 10**6,
        period=period,
        printed_pages=[297],
        pdf_page=149,
        **kw,
    )


def kpi_change(fid: str, label: str, value: str, direction: str, printed: int, **kw: Any) -> Any:
    return fact(
        fact_id=fid,
        label=label,
        label_norm=label.lower(),
        value=Decimal(value),
        unit="%",
        source="kpi",
        printed_pages=[printed],
        direction=direction,
        change_basis="N/N",
        col_path="N/N",
        **kw,
    )


@pytest.fixture
def ctx() -> Context:
    facts = [
        money("tts25", "Tổng tài sản", "1192344137", "31/12/2025"),
        money("tts24", "Tổng tài sản", "978800000", "31/12/2024"),
        money("p149R_t02_r10_c0", "Cho vay khách hàng", "757118751", "31/12/2025"),
        money(
            "p149R_t02_r11_c0",
            "Cho vay khách hàng",
            "767617129",
            "31/12/2025",
            row_level=1,
            parent_label="Cho vay khách hàng",
        ),
        # TCBS in the context so "CIR của TCBS" binds (the real p.81 title is the TCBS
        # "Dấu ấn Wealthtech" section but does not spell out "TCBS")
        kpi_change("p41R_k03_chg", "CIR", "0.5", "down", 81, table_title="Thành tựu của Tech · TCBS"),
        kpi_change("p13L_k02_chg", "Dư nợ vay", "18.2", "unknown", 24),
        # final-review I2 probes: rounding coarser than the source must not pass
        fact(
            fact_id="p5_roa",
            label="ROA",
            label_norm="roa",
            value=Decimal("1.5"),
            unit="%",
            period="FY2025",
            col_path="2025",
            raw="1,5%",
            printed_pages=[5],
        ),
        fact(
            fact_id="p5_pbt",
            label="Lợi nhuận",
            label_norm="loi nhuan",
            value=Decimal("1492"),
            unit="tỷ đồng",
            period="FY2025",
            col_path="2025",
            raw="1.492",
            printed_pages=[5],
        ),
        kpi_change("p3R_k07_chg", "Tổng tài sản", "21.8", "up", 5, table_title="Điểm nhấn 2025"),
        kpi_change("syn_tts_down", "Tổng tài sản", "0.3", "down", 5),
        kpi_change(
            "p30R_k01_chg",
            "Dư nợ vay",
            "26.9",
            "up",
            59,
            table_title="Thành tựu của Tech · Khối Ngân hàng Bán lẻ (RBG) · Điểm nhấn 2025",
        ),
    ]
    chunks = [
        mk_chunk(),
        mk_chunk(
            chunk_id="p149R_t02",
            pdf_page=149,
            printed_pages=[297],
            content_type="table",
            unit="triệu đồng",
            text=TABLE_TEXT,
        ),
        mk_chunk(chunk_id="p10R_p01", pdf_page=10, printed_pages=[19], content_type="prose", text=PROSE_TEXT),
    ]
    return Context(chunks=chunks, facts=facts)


def calcs_for(case: dict[str, Any], ctx: Context) -> dict[str, CalcResult]:
    specs = [CalcSpec(**c) for c in case.get("calcs", [])]
    return execute_calcs(specs, {f.fact_id: f for f in ctx.facts})


def verify_one(ctx: Context, text: str, sources: list[str], evidence: str, calcs: Any = None) -> Any:
    claim = ClaimOut(text=text, sources=sources, evidence=evidence)
    return verify_claims([claim], ctx, calcs or {})[0]


def test_direction_words() -> None:
    assert DIRECTION_WORDS == ("tăng", "giảm", "mạnh", "nhẹ", "đi xuống", "đi lên")


def test_valid_claim_passes(ctx: Context) -> None:
    v = verify_claims(
        [
            ClaimOut(
                text="Tổng tài sản đạt 1.192 nghìn tỷ đồng",
                sources=["chunk:p3R_k"],
                evidence="Tổng tài sản 1.192 Nghìn tỷ đồng",
            )
        ],
        ctx,
        {},
    )[0]
    assert v.ok and v.printed_pages == [5] and v.failed_rule is None


def test_adversarial_file_shape() -> None:
    cases = load_jsonl(ADVERSARIAL)
    assert len(cases) >= 12
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["expected_rule"] for c in cases} == ALL_RULES


@pytest.mark.parametrize("case", load_jsonl(ADVERSARIAL), ids=lambda c: c["id"])
def test_adversarial_blocked(case: dict[str, Any], ctx: Context) -> None:
    v = verify_claims([ClaimOut(**case["claim"])], ctx, calcs_for(case, ctx))[0]
    assert not v.ok and v.failed_rule == case["expected_rule"]


# --- PASS controls: the rules must not over-block ---------------------------


def test_pass_rounded_overview_number_vs_audited_fact(ctx: Context) -> None:
    # 1.192 nghìn tỷ vs 1.192.344.137 triệu: |diff| = 0,344 nghìn tỷ <= 0,5 nghìn tỷ
    v = verify_one(ctx, "Tổng tài sản đạt 1.192 nghìn tỷ đồng", ["fact:tts25"], "Tổng tài sản")
    assert v.ok and v.printed_pages == [297]


def test_pass_correct_direction_for_cir(ctx: Context) -> None:
    v = verify_one(ctx, "CIR của TCBS giảm 0,5%", ["fact:p41R_k03_chg"], "CIR 0,5%")
    assert v.ok and v.printed_pages == [81]


def test_pass_number_with_date_in_evidence(ctx: Context) -> None:
    v = verify_one(
        ctx,
        "Tại ngày 31/12/2025, cho vay khách hàng đạt 757.118.751 triệu đồng",
        ["chunk:p149R_t02"],
        "Cho vay khách hàng tại ngày 31/12/2025: 757.118.751",
    )
    assert v.ok and v.printed_pages == [297]


# --- Rule details -------------------------------------------------------------


def test_placeholder_filled_and_operand_pages_cited(ctx: Context) -> None:
    calcs = execute_calcs(
        [CalcSpec(id="c1", op="growth", a="fact:tts25", b="fact:tts24", to_unit=None)],
        {f.fact_id: f for f in ctx.facts},
    )
    v = verify_one(
        ctx,
        "Tổng tài sản năm 2025 {c1} so với năm 2024",
        ["chunk:p3R_k"],
        "Tổng tài sản 1.192 Nghìn tỷ đồng",
        calcs,
    )
    assert v.ok, v.failed_rule
    assert v.text == "Tổng tài sản năm 2025 tăng 21,82% so với năm 2024"
    assert v.sources == ["chunk:p3R_k", "fact:tts25", "fact:tts24"]
    assert v.printed_pages == [5, 297]


@pytest.mark.parametrize(
    ("value", "ok"),
    [("53.44", True), ("53.35", True), ("53.46", False), ("53.34", False)],
)
def test_tolerance_is_half_last_displayed_digit(value: str, ok: bool) -> None:
    v = Decimal(value)
    f = fact(fact_id="toi", value=v * 1000, unit="tỷ đồng", value_vnd=v * 10**12, printed_pages=[5])
    c = Context(facts=[f])
    got = verify_one(c, "Tổng thu nhập hoạt động đạt 53,4 nghìn tỷ đồng", ["fact:toi"], "")
    assert got.ok is ok
    assert got.failed_rule == (None if ok else "number_mismatch")


def test_unitless_number_compares_by_plain_value(ctx: Context) -> None:
    ok = verify_one(ctx, "Tổng thu nhập hoạt động đạt 53,4", ["chunk:p3R_k"], "Tổng thu nhập hoạt động 53,4")
    bad = verify_one(ctx, "Tổng thu nhập hoạt động đạt 53,9", ["chunk:p3R_k"], "Tổng thu nhập hoạt động 53,4")
    assert ok.ok and bad.failed_rule == "number_mismatch"


def test_years_and_counts_are_checked(ctx: Context) -> None:
    base = "Tổng thu nhập hoạt động 53,4 Nghìn tỷ đồng, CAGR 16,5% giai đoạn 2021-2025"
    ok = verify_one(ctx, "CAGR 16,5% giai đoạn 2021-2025", ["chunk:p3R_k"], base)
    bad = verify_one(ctx, "CAGR 16,5% giai đoạn 2019-2025", ["chunk:p3R_k"], base)
    assert ok.ok and bad.failed_rule == "number_mismatch"
    c = Context(chunks=[mk_chunk(text="Đạt 29 trên 34 chỉ tiêu")])
    assert verify_one(c, "Ngân hàng đạt 29 trên 34 chỉ tiêu", ["chunk:p3R_k"], "Đạt 29 trên 34 chỉ tiêu").ok
    bad_count = verify_one(c, "Ngân hàng đạt 30 trên 34 chỉ tiêu", ["chunk:p3R_k"], "Đạt 29 trên 34 chỉ tiêu")
    assert bad_count.failed_rule == "number_mismatch"


def test_footnote_marker_is_exempt(ctx: Context) -> None:
    v = verify_one(
        ctx, "Tổng tài sản (1) đạt 1.192 nghìn tỷ đồng", ["chunk:p3R_k"], "Tổng tài sản 1.192 Nghìn tỷ đồng"
    )
    assert v.ok


def test_three_digit_parenthesised_number_is_not_a_footnote(ctx: Context) -> None:
    v = verify_one(
        ctx, "Tổng tài sản (123) đạt 1.192 nghìn tỷ đồng", ["chunk:p3R_k"], "Tổng tài sản 1.192 Nghìn tỷ đồng"
    )
    assert v.failed_rule == "number_mismatch"


def test_identifier_number_passes_only_when_in_source() -> None:
    c = Context(chunks=[mk_chunk(text="Sau đại dịch COVID-19, tổng tài sản 1.192 Nghìn tỷ đồng")])
    ev = "Sau đại dịch COVID-19, tổng tài sản 1.192 Nghìn tỷ đồng"
    assert verify_one(c, "Sau COVID-19, tổng tài sản đạt 1.192 nghìn tỷ đồng", ["chunk:p3R_k"], ev).ok
    c2 = Context(chunks=[mk_chunk(text="Tổng tài sản 1.192 Nghìn tỷ đồng")])
    bad = verify_one(
        c2,
        "Sau COVID-19, tổng tài sản đạt 1.192 nghìn tỷ đồng",
        ["chunk:p3R_k"],
        "Tổng tài sản 1.192 Nghìn tỷ đồng",
    )
    assert bad.failed_rule == "number_mismatch"


def test_date_in_fact_period_is_exempt(ctx: Context) -> None:
    v = verify_one(
        ctx,
        "Tại ngày 31/12/2025, cho vay khách hàng đạt 757.118.751 triệu đồng",
        ["fact:p149R_t02_r10_c0"],
        "",
    )
    assert v.ok and v.printed_pages == [297]


def test_date_parts_exempt_even_when_unit_words_follow(ctx: Context) -> None:
    # "2025 đồng thời" makes the year look like an amount in đồng; the date exemption covers it
    text = "Ngày 31/12/2025 đồng thời là ngày tổng tài sản đạt 1.192 nghìn tỷ đồng"
    assert verify_one(ctx, text, ["fact:tts25"], "").ok
    other = "Ngày 30/06/2025 đồng thời là ngày tổng tài sản đạt 1.192 nghìn tỷ đồng"
    assert verify_one(ctx, other, ["fact:tts25"], "").failed_rule == "number_mismatch"


def test_fact_only_claim_does_not_trust_unchecked_evidence(ctx: Context) -> None:
    # evidence of a fact-only claim is not substring-checked, so its numbers are no reference
    v = verify_one(
        ctx, "Cho vay khách hàng đạt 1.234 triệu đồng", ["fact:p149R_t02_r10_c0"], "1.234 triệu đồng"
    )
    assert v.failed_rule == "number_mismatch"


def test_table_chunk_unit_applies_to_bare_evidence_numbers(ctx: Context) -> None:
    ev = "Cho vay khách hàng tại ngày 31/12/2025: 757.118.751"
    ok = verify_one(ctx, "Cho vay khách hàng đạt 757 nghìn tỷ đồng", ["chunk:p149R_t02"], ev)
    bad = verify_one(ctx, "Cho vay khách hàng đạt 757.118.751 tỷ đồng", ["chunk:p149R_t02"], ev)
    assert ok.ok and bad.failed_rule == "number_mismatch"


def test_rule_order_source_before_numbers(ctx: Context) -> None:
    v = verify_one(ctx, "Tổng tài sản đạt 9.999 tỷ đồng", ["chunk:nope"], "x")
    assert v.failed_rule == "source_missing"


def test_unprefixed_or_empty_sources_fail(ctx: Context) -> None:
    assert verify_one(ctx, "Tổng tài sản", ["p3R_k"], "Tổng tài sản").failed_rule == "source_missing"
    assert verify_one(ctx, "Tổng tài sản", [], "Tổng tài sản").failed_rule == "source_missing"


def test_empty_evidence_for_chunk_source_fails(ctx: Context) -> None:
    assert verify_one(ctx, "Tổng tài sản", ["chunk:p3R_k"], "").failed_rule == "evidence_not_substring"


def test_evidence_whitespace_is_normalised(ctx: Context) -> None:
    v = verify_one(
        ctx, "Tổng tài sản đạt 1.192 nghìn tỷ đồng", ["chunk:p3R_k"], "Tổng tài sản  1.192\xa0Nghìn tỷ đồng"
    )
    assert v.ok


def test_direction_word_beyond_window_is_allowed(ctx: Context) -> None:
    calcs = execute_calcs(
        [CalcSpec(id="c1", op="growth", a="fact:tts25", b="fact:tts24", to_unit=None)],
        {f.fact_id: f for f in ctx.facts},
    )
    near = verify_one(ctx, "Tổng tài sản tăng mạnh {c1}", ["fact:tts25"], "", calcs)
    # "tăng" is > 3 words before {c1} and is supported by the evidence for the same metric
    ev = "Tổng tài sản 1.192 Nghìn tỷ đồng, tăng 21,8%"
    far = verify_one(
        ctx, "Tổng tài sản tăng 21,8%, cụ thể năm 2025 so với 2024 là {c1}", ["chunk:p3R_k"], ev, calcs
    )
    assert near.failed_rule == "direction_near_placeholder"
    assert far.ok, far.failed_rule


def test_degree_word_on_unknown_direction(ctx: Context) -> None:
    # ruling: "mạnh"/"nhẹ" only count next to a direction word
    alone = verify_one(ctx, "Dư nợ vay thay đổi mạnh 18,2%", ["fact:p13L_k02_chg"], "")
    paired = verify_one(ctx, "Dư nợ vay giảm nhẹ 18,2%", ["fact:p13L_k02_chg"], "")
    assert alone.ok and paired.failed_rule == "direction_unknown"


def test_unknown_direction_without_direction_word_passes(ctx: Context) -> None:
    v = verify_one(ctx, "Dư nợ vay thay đổi 18,2% so với năm trước", ["fact:p13L_k02_chg"], "")
    assert v.ok and v.printed_pages == [24]


def test_failed_claim_keeps_filled_text_and_pages(ctx: Context) -> None:
    v = verify_one(ctx, "Tổng tài sản đạt {c9}", ["fact:tts25"], "")
    assert v.failed_rule == "calc_failed" and v.text == "Tổng tài sản đạt {c9}"
    assert v.printed_pages == [297]


def test_one_result_per_claim_in_order(ctx: Context) -> None:
    claims = [
        ClaimOut(text="Tổng tài sản đạt 1.192 nghìn tỷ đồng", sources=["fact:tts25"], evidence=""),
        ClaimOut(text="Tổng tài sản đạt 1.192 tỷ đồng", sources=["fact:tts25"], evidence=""),
    ]
    out = verify_claims(claims, ctx, {})
    assert [v.ok for v in out] == [True, False]


# --- Fix round 1: bare scale words, spelled units, unitless references, direction pooling ---


def test_bare_scale_word_maps_to_money_unit(ctx: Context) -> None:
    ev = "Tổng tài sản 1.192 Nghìn tỷ đồng"
    assert verify_one(ctx, "Tổng tài sản đạt 1.192 nghìn tỷ", ["chunk:p3R_k"], ev).ok
    assert verify_one(ctx, "Tổng tài sản đạt 1.192 ngàn tỷ", ["chunk:p3R_k"], ev).ok
    assert verify_one(ctx, "Tổng tài sản đạt 1.192 tỷ", ["chunk:p3R_k"], ev).failed_rule == "number_mismatch"


def test_phan_tram_is_percent(ctx: Context) -> None:
    ev = "Tổng thu nhập hoạt động 53,4 Nghìn tỷ đồng, CAGR 16,5% giai đoạn 2021-2025"
    assert verify_one(ctx, "CAGR đạt 16,5 phần trăm", ["chunk:p3R_k"], ev).ok
    assert verify_one(ctx, "CAGR đạt 17,3 phần trăm", ["chunk:p3R_k"], ev).failed_rule == "number_mismatch"


def test_foreign_currency_never_matches() -> None:
    c = Context(chunks=[mk_chunk(text="Huy động 1,5 tỷ USD vốn quốc tế")])
    v = verify_one(c, "Ngân hàng huy động 1,5 tỷ USD", ["chunk:p3R_k"], "Huy động 1,5 tỷ USD")
    assert v.failed_rule == "number_mismatch"


def test_scale_word_before_noun_fails_closed() -> None:
    # round-3 ruling: after a scale word only đồng/VND, punctuation or a connective may follow
    c = Context(chunks=[mk_chunk(text="Phục vụ 15,5 triệu khách hàng")])
    ev = "Phục vụ 15,5 triệu khách hàng"
    v = verify_one(c, "Ngân hàng phục vụ 15,5 triệu khách hàng", ["chunk:p3R_k"], ev)
    assert v.failed_rule == "number_mismatch"


def test_year_may_come_from_cited_chunk_text(ctx: Context) -> None:
    # 2025 is in the chunk ("2021-2025") but not in the quoted evidence
    v = verify_one(
        ctx,
        "Năm 2025, tổng tài sản đạt 1.192 nghìn tỷ đồng",
        ["chunk:p3R_k"],
        "Tổng tài sản 1.192 Nghìn tỷ đồng",
    )
    assert v.ok, v.failed_rule


def test_unitless_number_not_vouched_by_other_chunk_numbers(ctx: Context) -> None:
    # 53,4 is in the chunk but not in the evidence: no vouching from full chunk text
    v = verify_one(
        ctx,
        "Tổng tài sản 1.192 nghìn tỷ đồng, chỉ số 53,4",
        ["chunk:p3R_k"],
        "Tổng tài sản 1.192 Nghìn tỷ đồng",
    )
    assert v.failed_rule == "number_mismatch"


def test_unitless_number_not_vouched_by_money_fact(ctx: Context) -> None:
    v = verify_one(ctx, "Cho vay khách hàng đạt 757.118.751", ["fact:p149R_t02_r10_c0"], "")
    assert v.failed_rule == "number_mismatch"


def test_any_unknown_fact_forbids_direction_words(ctx: Context) -> None:
    v = verify_one(ctx, "Dư nợ vay tăng 18,2%", ["fact:p13L_k02_chg", "fact:tts25"], "")
    assert v.failed_rule == "direction_unknown"


# --- Fix round 2: vocabulary, fail-closed unitless matching, unsupported direction words ---


def test_nghin_ti_dong_spelling_passes(ctx: Context) -> None:
    ev = "Tổng tài sản 1.192 Nghìn tỷ đồng"
    assert verify_one(ctx, "Tổng tài sản đạt 1.192 nghìn tỉ đồng", ["chunk:p3R_k"], ev).ok
    assert verify_one(ctx, "Tổng tài sản đạt 1.192 ngàn tỉ", ["chunk:p3R_k"], ev).ok


def test_tram_ty_is_a_scale(ctx: Context) -> None:
    # 11.923 trăm tỷ = 1.192,3 nghìn tỷ; fact 1.192.344.137 triệu; |diff| 0,44 trăm tỷ <= 0,5
    assert verify_one(ctx, "Tổng tài sản đạt 11.923 trăm tỷ đồng", ["fact:tts25"], "").ok


def test_short_vnd_abbreviations_are_money() -> None:
    c = Context(chunks=[mk_chunk(text="Giá trị 1.500 tr và phí 20.000 đ")])
    ev = "Giá trị 1.500 tr và phí 20.000 đ"
    assert verify_one(c, "Giá trị 1,5 tỷ đồng và phí 20 nghìn đồng", ["chunk:p3R_k"], ev).ok


def test_currency_before_number_never_matches() -> None:
    c = Context(chunks=[mk_chunk(text="Huy động USD 1,5 tỷ")])
    v = verify_one(c, "Huy động USD 1,5 tỷ", ["chunk:p3R_k"], "Huy động USD 1,5 tỷ")
    assert v.failed_rule == "number_mismatch"


def test_unitless_claim_number_not_vouched_by_unit_evidence(ctx: Context) -> None:
    v = verify_one(ctx, "Tổng tài sản đạt 1.192", ["chunk:p3R_k"], "Tổng tài sản 1.192 Nghìn tỷ đồng")
    assert v.failed_rule == "number_mismatch"


def test_direction_word_supported_by_evidence_passes(ctx: Context) -> None:
    ev = "Tổng tài sản 1.192 Nghìn tỷ đồng, tăng 21,8%"
    assert verify_one(ctx, "Tổng tài sản tăng 21,8%", ["chunk:p3R_k"], ev).ok


def test_calc_never_supplies_direction_signal(ctx: Context) -> None:
    calcs = execute_calcs(
        [CalcSpec(id="c1", op="growth", a="fact:tts25", b="fact:tts24", to_unit=None)],
        {f.fact_id: f for f in ctx.facts},
    )
    up = verify_one(ctx, "Tổng tài sản năm 2025 mở rộng: {c1}, đà tăng giữ vững", ["fact:tts25"], "", calcs)
    down = verify_one(ctx, "Tổng tài sản năm 2025 thu hẹp: {c1}, đà giảm kéo dài", ["fact:tts25"], "", calcs)
    assert up.failed_rule == "direction_mismatch"
    assert down.failed_rule == "direction_mismatch"


def test_degree_word_without_signal_fails(ctx: Context) -> None:
    v = verify_one(ctx, "Tổng tài sản đạt 1.192 nghìn tỷ đồng, tăng trưởng mạnh", ["fact:tts25"], "")
    assert v.failed_rule == "direction_mismatch"


# --- Fix round 3: fail closed after scale words, metric-bound direction signals, vocabulary ---


@pytest.mark.parametrize(
    "text",
    [
        "Tổng tài sản đạt 1.192 nghìn tỷ đồng.",
        "Tổng tài sản đạt 1.192 nghìn tỷ VND",
        "Tổng tài sản đạt 1.192 nghìn tỷ VNĐ",
        "Tổng tài sản đạt 1.192 nghìn tỷ",
        "Tổng tài sản 2025 đạt 1.192 nghìn tỷ trong năm",
    ],
)
def test_scale_word_followed_by_vnd_end_or_connective_passes(ctx: Context, text: str) -> None:
    v = verify_one(ctx, text, ["chunk:p3R_k"], "Tổng tài sản 1.192 Nghìn tỷ đồng")
    assert v.ok, v.failed_rule


def test_scale_word_followed_by_punctuation_and_direction_passes(ctx: Context) -> None:
    ev = "Tổng tài sản 1.192 Nghìn tỷ đồng, tăng 21,8%"
    v = verify_one(ctx, "Tổng tài sản đạt 1.192 nghìn tỷ, tăng 21,8%", ["chunk:p3R_k"], ev)
    assert v.ok, v.failed_rule


def test_bang_alone_is_not_a_currency() -> None:
    text = "Theo Bảng 12, tổng tài sản 1.192 Nghìn tỷ đồng."
    c = Context(chunks=[mk_chunk(text=text)])
    ev = "Theo Bảng 12, tổng tài sản 1.192 Nghìn tỷ đồng"
    v = verify_one(c, "Theo Bảng 12, tổng tài sản 1.192 nghìn tỷ đồng", ["chunk:p3R_k"], ev)
    assert v.ok, v.failed_rule
    bad = verify_one(c, "Tổng tài sản đạt 1.192 nghìn tỷ bảng Anh", ["chunk:p3R_k"], ev)
    assert bad.failed_rule == "number_mismatch"


def test_tang_cuong_and_bare_degree_word_are_not_directions(ctx: Context) -> None:
    v = verify_one(ctx, "Ngân hàng tăng cường vốn mạnh", ["fact:tts25"], "")
    assert v.ok, v.failed_rule


def test_suy_giam_is_a_direction(ctx: Context) -> None:
    assert verify_one(ctx, "Tổng tài sản suy giảm", ["fact:tts25"], "").failed_rule == "direction_mismatch"


def test_fact_direction_needs_label_in_claim(ctx: Context) -> None:
    ok = verify_one(ctx, "CIR của TCBS giảm 0,5%", ["fact:p41R_k03_chg"], "")
    other = verify_one(ctx, "Chi phí giảm 0,5%", ["fact:p41R_k03_chg"], "")
    assert ok.ok and other.failed_rule == "direction_mismatch"


def test_evidence_direction_needs_same_subject_clause() -> None:
    # round-4 ruling replaces the 8-word window: the evidence clause before the direction word
    # must have exactly the claim's subject words (|S| >= 2)
    text = "Tổng tài sản của ngân hàng trong năm vừa qua theo báo cáo kiểm toán đã tăng 21,8%"
    c = Context(chunks=[mk_chunk(text=text)])
    v = verify_one(c, "Báo cáo kiểm toán ghi nhận tăng 21,8%", ["chunk:p3R_k"], text)
    assert v.failed_rule == "direction_mismatch"
    assert verify_one(c, "Tổng tài sản tăng 21,8%", ["chunk:p3R_k"], text).failed_rule == "direction_mismatch"
    same = "Tổng tài sản của ngân hàng trong năm vừa qua theo báo cáo kiểm toán tăng 21,8%"
    assert verify_one(c, same, ["chunk:p3R_k"], text).ok


def test_table_chunk_unit_not_applied_to_counted_nouns() -> None:
    c = Context(
        chunks=[mk_chunk(content_type="table", unit="triệu đồng", text="Số chi nhánh: 302 chi nhánh")]
    )
    v = verify_one(c, "Có 302 chi nhánh", ["chunk:p3R_k"], "302 chi nhánh")
    assert v.ok, v.failed_rule


# --- Fix round 4: direction signals bound to the subject clause of each direction word ---


def test_pass_real_kpi_sentence_supports_direction() -> None:
    c = Context(chunks=[mk_chunk(text="Chúng tôi là ai · Điểm nhấn 2025\n" + REAL_P5_LINE)])
    v = verify_one(c, "Tổng tài sản tăng 21,8% so với năm trước", ["chunk:p3R_k"], REAL_P5_LINE)
    assert v.ok, v.failed_rule


def test_pass_retail_loans_bound_through_fact_context(ctx: Context) -> None:
    v = verify_one(ctx, "Dư nợ vay của Khối Ngân hàng Bán lẻ tăng 26,9%", ["fact:p30R_k01_chg"], "")
    assert v.ok and v.printed_pages == [59], v.failed_rule


def test_fact_binds_only_when_subject_within_fact_vocabulary(ctx: Context) -> None:
    assert verify_one(ctx, "Tổng tài sản giảm 0,3%", ["fact:syn_tts_down"], "").ok
    for text in ("Lợi nhuận trên tổng tài sản giảm 0,3%", "Tổng tài sản có rủi ro giảm 0,3%"):
        assert verify_one(ctx, text, ["fact:syn_tts_down"], "").failed_rule == "direction_mismatch", text
    sub = verify_one(ctx, "CIR của công ty con TCBS giảm 0,5%", ["fact:p41R_k03_chg"], "")
    assert sub.failed_rule == "direction_mismatch"


def test_fact_label_must_be_the_subject_of_the_direction_word(ctx: Context) -> None:
    assert verify_one(ctx, "Tổng tài sản tăng 21,8%", ["fact:p3R_k07_chg"], "").ok
    for text in (
        "Cho vay khách hàng tăng 21,8%, cao hơn tổng tài sản",
        "Tổng tài sản 21,8%, cho vay khách hàng tăng",
    ):
        assert verify_one(ctx, text, ["fact:p3R_k07_chg"], "").failed_rule == "direction_mismatch", text


@pytest.mark.parametrize("neg", ["không tăng", "chưa tăng", "không hề tăng", "chẳng tăng"])
def test_negated_direction_word_fails(ctx: Context, neg: str) -> None:
    v = verify_one(ctx, f"Tổng tài sản {neg} 21,8%", ["fact:p3R_k07_chg"], "")
    assert v.failed_rule == "direction_mismatch"


def test_negated_evidence_direction_supplies_no_signal(ctx: Context) -> None:
    v = verify_one(ctx, "Tổng tài sản tăng", ["chunk:p10R_p01"], "Tổng tài sản không tăng")
    assert v.failed_rule == "direction_mismatch"


def test_evidence_subject_must_equal_claim_subject(ctx: Context) -> None:
    roa = "Lợi nhuận trên tổng tài sản (ROA) tăng 0,2 điểm %"
    bad = verify_one(ctx, "Tổng tài sản tăng 0,2 điểm %", ["chunk:p10R_p01"], roa)
    assert bad.failed_rule == "direction_mismatch"
    assert verify_one(ctx, "Lợi nhuận trên tổng tài sản (ROA) tăng 0,2 điểm %", ["chunk:p10R_p01"], roa).ok


def test_single_word_subject_gets_no_evidence_signal() -> None:
    line = "Tỷ lệ chi phí/thu nhập (CIR): 13,7 %, giảm 0,5% so với năm trước"
    c = Context(chunks=[mk_chunk(text=line)])
    assert verify_one(c, "CIR giảm 0,5%", ["chunk:p3R_k"], line).failed_rule == "direction_mismatch"
    assert verify_one(c, "Tỷ lệ chi phí/thu nhập (CIR) giảm 0,5%", ["chunk:p3R_k"], line).ok


def test_truoc_sau_are_not_stopwords(ctx: Context) -> None:
    ev = "Lợi nhuận trước thuế 32,5 Nghìn tỷ đồng, tăng 17,3% so với cùng kỳ"
    assert verify_one(ctx, "Lợi nhuận trước thuế tăng 17,3%", ["chunk:p3R_k"], ev).ok
    bad = verify_one(ctx, "Lợi nhuận sau thuế tăng 17,3%", ["chunk:p3R_k"], ev)
    assert bad.failed_rule == "direction_mismatch"


# --- Fix round 5: period phrases stay in the subject unless comparative; no accent folding ---


@pytest.mark.parametrize("period", ["năm trước", "kỳ trước", "năm ngoái"])
def test_period_phrase_in_subject_blocks(ctx: Context, period: str) -> None:
    v = verify_one(ctx, f"Tổng tài sản {period} tăng 21,8%", ["fact:p3R_k07_chg"], "")
    assert v.failed_rule == "direction_mismatch"


@pytest.mark.parametrize(
    "tail", ["so với năm trước", "so với cùng kỳ năm trước", "so với kỳ trước", "so với năm ngoái", "cùng kỳ"]
)
def test_comparative_period_phrase_is_stripped(tail: str) -> None:
    line = f"Tổng tài sản {tail} tăng 21,8%"
    c = Context(chunks=[mk_chunk(text=line)])
    assert verify_one(c, "Tổng tài sản tăng 21,8%", ["chunk:p3R_k"], line).ok


def test_subject_words_are_not_accent_folded(ctx: Context) -> None:
    ev = "Chi phí thuế tăng 10%"
    assert verify_one(ctx, ev, ["chunk:p10R_p01"], ev).ok
    assert (
        verify_one(ctx, "Chi phí thuê tăng 10%", ["chunk:p10R_p01"], ev).failed_rule == "direction_mismatch"
    )
    tax = kpi_change("thue", "Chi phí thuế", "10", "up", 7)
    c = Context(facts=[tax])
    assert verify_one(c, "Chi phí thuế tăng 10%", ["fact:thue"], "").ok
    assert verify_one(c, "Chi phí thuê tăng 10%", ["fact:thue"], "").failed_rule == "direction_mismatch"


# --- I2: rounding may not be coarser than the source -------------------------


@pytest.mark.parametrize(
    ("text", "src", "ok"),
    [
        ("ROA năm 2025 đạt 2%", "fact:p5_roa", False),
        ("ROA năm 2025 đạt 1%", "fact:p5_roa", False),
        ("ROA năm 2025 đạt 1,5%", "fact:p5_roa", True),
        ("ROA năm 2025 đạt 1,50%", "fact:p5_roa", True),
        ("Lợi nhuận năm 2025 đạt 1 nghìn tỷ đồng", "fact:p5_pbt", False),
        ("Lợi nhuận năm 2025 đạt 2 nghìn tỷ đồng", "fact:p5_pbt", False),
        ("Lợi nhuận năm 2025 đạt 1.000 tỷ đồng", "fact:p5_pbt", False),
        ("Lợi nhuận năm 2025 đạt 1.492 tỷ đồng", "fact:p5_pbt", True),
        ("Lợi nhuận năm 2025 đạt 1,49 nghìn tỷ đồng", "fact:p5_pbt", True),
        ("Lợi nhuận năm 2025 đạt 1,5 nghìn tỷ đồng", "fact:p5_pbt", False),
    ],
)
def test_rounding_not_coarser_than_source(ctx: Context, text: str, src: str, ok: bool) -> None:
    v = verify_one(ctx, text, [src], "")
    assert v.ok is ok, v.failed_rule
    assert v.failed_rule == (None if ok else "number_mismatch")


def test_evidence_number_rounding_not_coarser(ctx: Context) -> None:
    ok = verify_one(ctx, "ROA đạt 1,5%", ["chunk:p10R_p01"], "ROA đạt 1,5%")
    bad = verify_one(ctx, "ROA đạt 2%", ["chunk:p10R_p01"], "ROA đạt 1,5%")
    assert ok.ok and bad.failed_rule == "number_mismatch"


def test_scale_conversion_needs_three_significant_digits() -> None:
    f = fact(
        fact_id="tts",
        value=Decimal("1192344137"),
        unit="triệu đồng",
        value_vnd=Decimal("1192344137") * 10**6,
        raw="1.192.344.137",
        printed_pages=[297],
    )
    c = Context(facts=[f])
    assert verify_one(c, "Tổng tài sản đạt 1.192 nghìn tỷ đồng", ["fact:tts"], "").ok
    assert verify_one(c, "Tổng tài sản đạt 1.192.344 tỷ đồng", ["fact:tts"], "").ok
    assert verify_one(c, "Tổng tài sản đạt 1,19 triệu tỷ đồng", ["fact:tts"], "").failed_rule == (
        "number_mismatch"
    )  # unknown scale word: fails closed
    # after a scale conversion "1,5" is within its own tolerance but has only 2 significant digits
    two = fact(fact_id="two", value=Decimal("1492"), unit="tỷ đồng", raw="1.492", printed_pages=[5])
    c2 = Context(facts=[two])
    assert verify_one(c2, "Lợi nhuận đạt 1,49 nghìn tỷ đồng", ["fact:two"], "").ok
    assert verify_one(c2, "Lợi nhuận đạt 1,5 nghìn tỷ đồng", ["fact:two"], "").failed_rule == (
        "number_mismatch"
    )


# --- real-run findings (sample questions sq-01 / sq-03 / sq-06 / sq-07, index 5479a842036e) ---

P14_TEXT = (
    "Câu chuyện của Tech · Về chúng tôi · MẠNG LƯỚI GIAO DỊCH\n"
    ": 1 trụ sở chính\n: 2 văn phòng đại diện\n: 302 chi nhánh và phòng giao dịch trên toàn quốc"
)
P30_TEXT = (
    "Thành tựu của Tech · Khối Ngân hàng Bán lẻ (RBG) · Điểm nhấn 2025\n"
    "Dư nợ vay: 328,1 nghìn tỷ đồng, tăng 26,9% so với cùng kỳ năm trước"
)
P30_TITLE = "Thành tựu của Tech · Khối Ngân hàng Bán lẻ (RBG) · Điểm nhấn 2025"


def _p30_facts() -> list[Any]:
    common: dict[str, Any] = {
        "label": "Dư nợ vay",
        "label_norm": "du no vay",
        "table_title": P30_TITLE,
        "chapter": "Thành tựu của Tech",
        "source": "kpi",
        "printed_pages": [59],
        "period": "FY2025",
    }
    return [
        fact(fact_id="p30R_k01", value=Decimal("328.1"), unit="nghìn tỷ đồng", raw="328,1", **common),
        fact(
            fact_id="p30R_k01_chg",
            value=Decimal("26.9"),
            unit="%",
            raw="26,9% N/N",
            direction="up",
            change_basis="N/N",
            col_path="N/N",
            **common,
        ),
    ]


def test_date_restated_from_the_question_is_vouched_by_the_fact_period() -> None:
    f = fact(
        fact_id="p8L_t01_r02_c2",
        label="Tổng tài sản",
        value=Decimal("1192344"),
        unit="tỷ đồng",
        raw="1.192.344",
        period="FY2025",
    )
    claim = "Tổng tài sản của Techcombank tại ngày 31/12/2025 là 1.192.344 tỷ đồng."
    src = ["fact:p8L_t01_r02_c2"]
    v = verify_claims([ClaimOut(text=claim, sources=src, evidence="")], Context(facts=[f]), {})
    assert v[0].ok, v[0].failed_rule
    other = claim.replace("31/12/2025", "31/12/2024")
    v = verify_claims([ClaimOut(text=other, sources=src, evidence="")], Context(facts=[f]), {})
    assert v[0].failed_rule == "number_mismatch"


def test_year_of_a_cited_kpi_chunk_comes_from_its_own_facts() -> None:
    chunk = mk_chunk(chunk_id="p14R_k", text=P14_TEXT, printed_pages=[27], fact_ids=["p14R_k03"])
    k03 = fact(
        fact_id="p14R_k03",
        label="",
        value=Decimal(302),
        unit="chi nhánh và phòng giao dịch trên toàn quốc",
        raw="302",
        source="kpi",
        period="FY2025",
    )
    ctx = Context(chunks=[chunk], chunk_facts=[k03])
    claim = "Tính đến năm 2025, Techcombank có 302 chi nhánh và phòng giao dịch trên toàn quốc."
    ev = "302 chi nhánh và phòng giao dịch trên toàn quốc"
    v = verify_claims([ClaimOut(text=claim, sources=["chunk:p14R_k"], evidence=ev)], ctx, {})
    assert v[0].ok, v[0].failed_rule
    wrong = claim.replace("2025", "2024")
    v = verify_claims([ClaimOut(text=wrong, sources=["chunk:p14R_k"], evidence=ev)], ctx, {})
    assert v[0].failed_rule == "number_mismatch"


def test_direction_of_a_cited_kpi_chunk_comes_from_its_own_change_fact() -> None:
    chunk = mk_chunk(
        chunk_id="p30R_k", text=P30_TEXT, printed_pages=[59], fact_ids=["p30R_k01", "p30R_k01_chg"]
    )
    ctx = Context(chunks=[chunk], chunk_facts=_p30_facts())
    claim = (
        "Dư nợ vay của Khối Ngân hàng Bán lẻ năm 2025 là 328,1 nghìn tỷ đồng, "
        "tăng 26,9% so với cùng kỳ năm trước."
    )
    ev = "Dư nợ vay: 328,1 nghìn tỷ đồng, tăng 26,9% so với cùng kỳ năm trước"
    v = verify_claims([ClaimOut(text=claim, sources=["chunk:p30R_k"], evidence=ev)], ctx, {})
    assert v[0].ok, v[0].failed_rule
    down = claim.replace("tăng 26,9%", "giảm 26,9%")
    v = verify_claims([ClaimOut(text=down, sources=["chunk:p30R_k"], evidence=ev)], ctx, {})
    assert v[0].failed_rule == "direction_mismatch"


def test_facts_of_an_uncited_chunk_vouch_for_nothing() -> None:
    chunk = mk_chunk(chunk_id="p30R_k", text=P30_TEXT, fact_ids=["p30R_k01", "p30R_k01_chg"])
    other = mk_chunk(chunk_id="p14R_k", text=P14_TEXT, fact_ids=[])
    ctx = Context(chunks=[chunk, other], chunk_facts=_p30_facts())
    claim = "Techcombank có 328,1 nghìn tỷ đồng chi nhánh."
    ev = "302 chi nhánh và phòng giao dịch trên toàn quốc"
    v = verify_claims([ClaimOut(text=claim, sources=["chunk:p14R_k"], evidence=ev)], ctx, {})
    assert v[0].failed_rule == "number_mismatch"


def test_compound_growth_is_a_metric_name_not_a_direction() -> None:
    text = (
        "Chúng tôi là ai · Điểm nhấn 2025\n"
        "Tổng thu nhập hoạt động: 53,4 nghìn tỷ đồng, tăng trưởng kép (CAGR) 2018–2025: 16,5%"
    )
    ctx = Context(chunks=[mk_chunk(text=text)])
    claim = "Tốc độ tăng trưởng kép giai đoạn 2018–2025 của tổng thu nhập hoạt động là 16,5%."
    ev = "tăng trưởng kép (CAGR) 2018–2025: 16,5%"
    v = verify_claims([ClaimOut(text=claim, sources=["chunk:p3R_k"], evidence=ev)], ctx, {})
    assert v[0].ok, v[0].failed_rule


# --- dev-eval findings (own-01 / own-09 / own-35 / own-44 / own-17) ---

P8_ROW = "Lợi nhuận trước thuế | 27.538 | 31.500 | 32.538 | +18,16% | +3,30%"


def _row_ctx(row: str = P8_ROW, change_raw: str = "+18,16%") -> Context:
    """p.14 highlights table chunk with the SQL fact of its '% so với 2024' cell."""
    text = "KẾT QUẢ NỔI BẬT NĂM 2025 · Đơn vị: tỷ đồng\n| Chỉ tiêu | 2024 | 2025 > Kế hoạch |\n" + row
    chunk = mk_chunk(
        chunk_id="p8L_t01", content_type="table", unit="tỷ đồng", text=text, fact_ids=["p8L_t01_r03_c3"]
    )
    value = Decimal(change_raw.replace("+", "").replace("%", "").replace(",", "."))
    cell = fact(
        fact_id="p8L_t01_r03_c3",
        label="Lợi nhuận trước thuế",
        table_title="KẾT QUẢ NỔI BẬT NĂM 2025",
        col_path="% So sánh với > 2024",
        value=value,
        unit="%",
        raw=change_raw,
    )
    return Context(chunks=[chunk], chunk_facts=[cell])


def _one(claim: str, ctx: Context, sources: list[str], evidence: str = "") -> Any:
    return verify_claims([ClaimOut(text=claim, sources=sources, evidence=evidence)], ctx, {})[0]


@pytest.mark.parametrize(
    ("claim", "change_raw", "rule"),
    [
        ("Lợi nhuận trước thuế năm 2025 tăng 18,16% so với năm 2024.", "+18,16%", None),
        ("Lợi nhuận trước thuế năm 2025 giảm 18,16% so với năm 2024.", "+18,16%", "direction_mismatch"),
        # a negative source value never vouches for the unsigned claim number in the first place
        ("Lợi nhuận trước thuế năm 2025 tăng 18,16% so với năm 2024.", "-18,16%", "number_mismatch"),
        ("Lợi nhuận trước thuế năm 2025 tăng 18,16% so với năm 2024.", "18,16%", "direction_mismatch"),
        ("Tổng tài sản năm 2025 tăng 18,16% so với năm 2024.", "+18,16%", "direction_mismatch"),
    ],
)
def test_signed_change_cell_gives_its_own_row_a_direction(claim: str, change_raw: str, rule: Any) -> None:
    row = P8_ROW.replace("+18,16%", change_raw)
    assert _one(claim, _row_ctx(row, change_raw), ["chunk:p8L_t01"], row).failed_rule == rule


def test_evidence_with_a_longer_subject_still_blocks_the_direction() -> None:
    """own-35 stays fail-safe: the evidence subject ("…của Ngân hàng lũy kế…") is not the claim's."""
    evidence = (
        "Lợi nhuận sau thuế của Ngân hàng lũy kế cho năm tài chính kết thúc ngày 31 tháng 12 năm 2025 "
        "tăng 4.194.368 triệu đồng tương đương tăng 19,28% "
        "so với năm tài chính kết thúc ngày 31 tháng 12 năm 2024"
    )
    ctx = Context(chunks=[mk_chunk(chunk_id="p192R_x01", content_type="prose", text=evidence)])
    claim = "Lợi nhuận sau thuế hợp nhất năm 2025 tăng 19,28% so với năm 2024."
    assert _one(claim, ctx, ["chunk:p192R_x01"], evidence).failed_rule == "direction_mismatch"


def test_entity_outside_the_kpi_vocabulary_still_blocks_the_direction() -> None:
    """own-09 stays fail-safe: "TCBS" is not in the tile's label, heading or chapter."""
    title = "Thành tựu của Tech · DẤU ẤN WEALTHTECH NĂM 2025"
    common: dict[str, Any] = {"label": "Tỷ lệ chi phí/thu nhập (CIR)", "table_title": title, "source": "kpi"}
    k01 = fact(fact_id="k01", value=Decimal("13.7"), unit="%", raw="13,7", period="FY2025", **common)
    chg = fact(
        fact_id="k01_chg",
        value=Decimal("0.5"),
        unit="%",
        raw="0,5% so với năm 2024",
        direction="down",
        period="FY2025",
        **common,
    )
    ctx, src = Context(facts=[k01, chg]), ["fact:k01", "fact:k01_chg"]
    plain = "Tỷ lệ chi phí/thu nhập (CIR) năm 2025 là 13,7%, giảm 0,5% so với năm 2024."
    assert _one(plain, ctx, src).ok
    tcbs = plain.replace("(CIR) năm", "(CIR) của TCBS năm")
    assert _one(tcbs, ctx, src).failed_rule == "direction_mismatch"


P44 = (
    "Chúng tôi tập trung vào ba trụ cột chiến lược nhằm đáp ứng nhu cầu ngày càng đa dạng của nhà đầu tư.\n"
    "Trọng tâm năm 2026 Bứt phá tăng trưởng và đổi mới sản phẩm\n"
    "Techcom Capital sẽ tăng cường chất lượng dịch vụ."
)


def test_direction_word_quoted_verbatim_from_the_cited_chunk_passes() -> None:
    ctx = Context(chunks=[mk_chunk(chunk_id="p44R_x01", content_type="prose", text=P44)])
    ev = "Chúng tôi tập trung vào ba trụ cột chiến lược"
    ok = "Trọng tâm năm 2026 của Techcom Capital gồm: bứt phá tăng trưởng và đổi mới sản phẩm."
    assert _one(ok, ctx, ["chunk:p44R_x01"], ev).ok
    loose = "Techcom Capital tăng trưởng mạnh trong năm 2026."
    assert _one(loose, ctx, ["chunk:p44R_x01"], ev).failed_rule == "direction_mismatch"


def test_cash_outflow_in_parentheses_is_read_as_its_magnitude() -> None:
    paid = fact(
        fact_id="cf1",
        label="Cổ tức trả cho cổ đông",
        table_title="Báo cáo lưu chuyển tiền tệ hợp nhất",
        value=Decimal("-7084911"),
        raw="(7.084.911)",
        period="FY2025",
    )
    claim = "Cổ tức trả cho cổ đông trong năm 2025 là 7.084.911 triệu đồng."
    assert _one(claim, Context(facts=[paid]), ["fact:cf1"]).ok
    loss = paid.model_copy(update={"label": "Lãi/(lỗ) thuần từ hoạt động khác", "fact_id": "pl1"})
    claim = "Lãi thuần từ hoạt động khác năm 2025 là 7.084.911 triệu đồng."
    assert _one(claim, Context(facts=[loss]), ["fact:pl1"]).failed_rule == "number_mismatch"

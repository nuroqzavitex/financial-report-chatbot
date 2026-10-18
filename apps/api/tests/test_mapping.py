from decimal import Decimal

from ircb.answering.renderer import PARTIAL_TEXT, REFUSED_TEXT, render
from ircb.domain.models import CalcResult, Conflict, VerifiedClaim
from ircb_api.mapping import to_chat_answer

from tests.conftest import answer_with, ok_claim


def test_notes_and_operands_mapping(facts_store, chunks):
    a = answer_with(
        claims=[ok_claim("A [tr. 5]", calc_ids=["c1"])],
        text="A [tr. 5]\nMột phần câu hỏi không có thông tin trong Báo cáo thường niên 2025.",
        calcs=[
            CalcResult(
                id="c1",
                ok=True,
                value=Decimal("21.82"),
                unit="%",
                rendered="tăng 21,82%",
                formula="(a-b)/b",
                operand_fact_ids=["f25", "f24"],
                error=None,
            )
        ],
    )
    out = to_chat_answer(a, "s", facts_store, chunks)
    assert out.notes == ["Một phần câu hỏi không có thông tin trong Báo cáo thường niên 2025."]
    assert out.calcs[0].value == "21.82" and [o.fact_id for o in out.calcs[0].operands] == ["f25", "f24"]
    op = out.calcs[0].operands[0]
    assert (op.value, op.unit, op.period, op.raw, op.printed_pages) == (
        "1192.3",
        "tỷ đồng",
        "2025",
        "1192,3",
        [5],
    )


def test_sources_take_pages_from_store_and_evidence_only_for_chunks(facts_store, chunks):
    a = answer_with(claims=[ok_claim("A [tr. 5]")], text="A [tr. 5]")
    src = to_chat_answer(a, "s", facts_store, chunks).claims[0].sources
    assert [(s.kind, s.id, s.printed_pages, s.evidence) for s in src] == [
        ("fact", "f25", [5], ""),
        ("chunk", "c1", [2], "Tong tai san 1.192"),
    ]


def test_failed_calcs_are_dropped(facts_store, chunks):
    bad = CalcResult(
        id="c2",
        ok=False,
        value=None,
        unit=None,
        rendered=None,
        formula=None,
        operand_fact_ids=["f25"],
        error="x",
    )
    out = to_chat_answer(
        answer_with(claims=[ok_claim("A", calc_ids=["c2"])], text="A [tr. 5]", calcs=[bad]),
        "s",
        facts_store,
        chunks,
    )
    assert out.calcs == []


def test_renderer_contract_passed_claim_lines_then_notes(facts_store, chunks):
    """Pins the renderer contract `notes` relies on: one line per passed claim, then the note lines."""
    passed = [ok_claim("Tổng tài sản đạt 1.192", [5]), ok_claim("Dư nợ đạt 328,1", [6, 7])]
    failed = VerifiedClaim(
        text="SECRET 9.999",
        sources=["chunk:c1"],
        printed_pages=[9],
        ok=False,
        failed_rule="x",
        evidence="SECRET",
    )
    conflict = Conflict(kind="rounding", note="free text")
    status, text, _ = render([passed[0], failed, passed[1]], {}, conflict, "partial")
    a = answer_with(claims=[passed[0], failed, passed[1]], text=text, status=status, conflict=conflict)
    out = to_chat_answer(a, "s", facts_store, chunks)
    assert text.split("\n")[:2] == ["Tổng tài sản đạt 1.192 [tr. 5]", "Dư nợ đạt 328,1 [tr. 6, 7]"]
    assert [c.text for c in out.claims] == ["Tổng tài sản đạt 1.192", "Dư nợ đạt 328,1"]
    assert [c.citation for c in out.claims] == ["[tr. 5]", "[tr. 6, 7]"]
    assert out.notes == [
        "Số liệu tổng quan đã được làm tròn từ số kiểm toán.",
        "Chưa xác minh được một phần nội dung, xem [tr. 9].",
        PARTIAL_TEXT,
    ]
    assert out.conflict_kind == "rounding"
    assert "SECRET" not in out.model_dump_json()


def test_refused_and_error_have_only_the_text_as_note(facts_store, chunks):
    for status, text in [("refused", REFUSED_TEXT), ("error", "Lỗi khi gọi mô hình, vui lòng thử lại.")]:
        a = answer_with(claims=[ok_claim("A")], text=text, status=status)
        out = to_chat_answer(a, "s", facts_store, chunks)
        assert out.status == status and out.notes == [text] and out.claims == [] and out.calcs == []


def test_decimal_str_never_uses_exponent():
    from decimal import Decimal

    from ircb_api.mapping import decimal_str

    assert decimal_str(Decimal("1.1923E+12")) == "1192300000000"
    assert decimal_str(Decimal("21.82")) == "21.82"


def test_chat_mapping_uses_plain_decimals(facts_store, chunks):
    a = answer_with(claims=[ok_claim("A [tr. 5]")], text="A [tr. 5]", cost_usd="1E-7")
    out = to_chat_answer(a, "s", facts_store, chunks)
    assert out.cost_usd == "0.0000001"


def _growth_calc() -> CalcResult:
    return CalcResult(
        id="c1",
        ok=True,
        value=Decimal("21.82"),
        unit="%",
        rendered="tăng 21,82%",
        formula="(a-b)/b",
        operand_fact_ids=["f25", "f24"],
        error=None,
    )


def test_calc_of_a_failed_claim_is_never_mapped(facts_store, chunks):
    passed = ok_claim("Dư nợ đạt 328,1", [6], sources=["chunk:c1"])
    failed = VerifiedClaim(
        text="Tổng tài sản tăng tăng 21,82%",
        sources=["fact:f25", "fact:f24"],
        printed_pages=[5],
        ok=False,
        failed_rule="direction_near_placeholder",
        evidence="",
        calc_ids=["c1"],
    )
    status, text, _ = render([passed, failed], {}, None, "partial")
    a = answer_with(claims=[passed, failed], text=text, status=status, calcs=[_growth_calc()])
    out = to_chat_answer(a, "s", facts_store, chunks)
    assert out.status == "partial" and out.calcs == []
    payload = out.model_dump_json()
    assert "f25" not in payload and "f24" not in payload and "21,82" not in payload


def test_calc_of_a_passed_claim_is_kept(facts_store, chunks):
    claim = ok_claim("Tổng tài sản tăng 21,82%", sources=["fact:f25", "fact:f24"], calc_ids=["c1"])
    out = to_chat_answer(
        answer_with(claims=[claim], text="Tổng tài sản tăng 21,82% [tr. 5]", calcs=[_growth_calc()]),
        "s",
        facts_store,
        chunks,
    )
    assert [c.id for c in out.calcs] == ["c1"]

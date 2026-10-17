from decimal import Decimal

import pytest
from factories import fact
from ircb.answering.calc import execute_calcs, fill_placeholders, operand_facts
from ircb.domain.models import CalcSpec

TA25 = fact(
    fact_id="ta25", label_norm="tong tai san", unit="tỷ đồng", period="FY2025", value=Decimal("1192344")
)
TA24 = fact(
    fact_id="ta24", label_norm="tong tai san", unit="tỷ đồng", period="FY2024", value=Decimal("978799")
)
L25 = fact(fact_id="l25", label_norm="cho vay", unit="tỷ đồng", period="FY2025", value=Decimal("757118"))
L24 = fact(fact_id="l24", label_norm="cho vay", unit="tỷ đồng", period="FY2024", value=Decimal("623634"))
F = {f.fact_id: f for f in [TA25, TA24, L25, L24]}


def spec(op, a, b=None, id="c1", to_unit=None):
    return CalcSpec(id=id, op=op, a=a, b=b, to_unit=to_unit)


def nested():
    return execute_calcs(
        [
            spec("growth", "fact:ta25", "fact:ta24", id="c1"),
            spec("growth", "fact:l25", "fact:l24", id="c2"),
            spec("diff", "calc:c1", "calc:c2", id="c3"),
        ],
        F,
    )


def test_growth_renders_direction():
    r = execute_calcs([spec("growth", "fact:ta25", "fact:ta24")], F)["c1"]
    assert r.ok and r.rendered == "tăng 21,82%" and r.unit == "%"
    assert r.formula == "(1.192.344 − 978.799) / 978.799"
    assert r.operand_fact_ids == ["ta25", "ta24"]


def test_negative_growth():
    G = F | {"d23": TA25.model_copy(update={"fact_id": "d23", "period": "FY2023"})}
    r = execute_calcs([spec("growth", "fact:ta24", "fact:d23")], G)["c1"]
    assert r.rendered == "giảm 17,91%"


@pytest.mark.parametrize("op", ["growth", "diff"])
@pytest.mark.parametrize(
    ("p_new", "p_old"),
    [("FY2025", "FY2024"), ("2025-12-31", "2024-12-31"), ("2025", "2024"), ("31/12/2025", "31/12/2024")],
)
def test_swapped_operands_rejected_period_order(op, p_new, p_old):
    """Regression I1: a = earlier period, b = later period would flip the sign of a verified figure."""
    new = TA25.model_copy(update={"period": p_new})
    old = TA24.model_copy(update={"period": p_old})
    G = {"ta25": new, "ta24": old}
    swapped = execute_calcs([spec(op, "fact:ta24", "fact:ta25")], G)["c1"]
    assert not swapped.ok and swapped.error == "period_order"
    assert execute_calcs([spec(op, "fact:ta25", "fact:ta24")], G)["c1"].ok


def test_period_order_compares_across_formats():
    G = {
        "a": TA25.model_copy(update={"fact_id": "a", "period": "FY2025"}),
        "b": TA24.model_copy(update={"fact_id": "b", "period": "2024-12-31"}),
        "c": TA24.model_copy(update={"fact_id": "c", "period": "2025-12-31"}),
        "u": TA24.model_copy(update={"fact_id": "u", "period": "N/N"}),
    }
    assert execute_calcs([spec("growth", "fact:a", "fact:b")], G)["c1"].ok
    assert execute_calcs([spec("growth", "fact:b", "fact:a")], G)["c1"].error == "period_order"
    # FY2025 vs 31/12/2025: not strictly later
    assert execute_calcs([spec("growth", "fact:a", "fact:c")], G)["c1"].error == "period_order"
    # an unparseable period cannot be ordered: fail closed
    assert execute_calcs([spec("growth", "fact:a", "fact:u")], G)["c1"].error == "period_order"


def test_fact_vs_derived_calc_rejected():
    """A growth % calc minus a fact % has no defined metric/period: operand_mix (T18)."""
    G = F | {"p": fact(fact_id="p", label_norm="roa", unit="%", period="FY2024", value=Decimal(5))}
    res = execute_calcs(
        [spec("growth", "fact:ta25", "fact:ta24", id="c1"), spec("diff", "calc:c1", "fact:p", id="c2")], G
    )
    assert not res["c2"].ok and res["c2"].error == "operand_mix"


def test_converted_operand_keeps_metric_and_period():
    G = F | {
        "n24": fact(
            fact_id="n24",
            label_norm="tong tai san",
            unit="nghìn tỷ đồng",
            period="FY2024",
            value=Decimal("978.8"),
        )
    }
    ok = execute_calcs(
        [
            spec("convert", "fact:ta25", to_unit="nghìn tỷ đồng", id="c1"),
            spec("growth", "calc:c1", "fact:n24", id="c2"),
        ],
        G,
    )
    assert ok["c2"].ok and ok["c2"].rendered == "tăng 21,82%"
    swapped = execute_calcs(
        [
            spec("convert", "fact:ta25", to_unit="nghìn tỷ đồng", id="c1"),
            spec("growth", "fact:n24", "calc:c1", id="c2"),
        ],
        G,
    )
    assert swapped["c2"].error == "period_order"
    other = execute_calcs(
        [
            spec("convert", "fact:l25", to_unit="nghìn tỷ đồng", id="c1"),
            spec("growth", "calc:c1", "fact:n24", id="c2"),
        ],
        G,
    )
    assert other["c2"].error == "metric_mismatch"


def test_review_probe_swapped_growth_no_longer_verifies():
    """The final-review probe: 'giảm 17,87%' for a +21,76% change must not pass the verifier."""
    from ircb.answering.verifier import verify_claims
    from ircb.domain.models import ClaimOut
    from ircb.retrieval.hybrid import Context

    f25 = fact(
        fact_id="a25",
        value=Decimal("1192"),
        unit="nghìn tỷ đồng",
        period="FY2025",
        col_path="Năm 2025",
        label="Tổng tài sản",
        label_norm="tong tai san",
        printed_pages=[5],
        raw="1.192",
    )
    f24 = fact(
        fact_id="a24",
        value=Decimal("979"),
        unit="nghìn tỷ đồng",
        period="FY2024",
        col_path="Năm 2024",
        label="Tổng tài sản",
        label_norm="tong tai san",
        printed_pages=[5],
        raw="979",
    )
    calcs = execute_calcs([spec("growth", "fact:a24", "fact:a25")], {"a25": f25, "a24": f24})
    assert calcs["c1"].error == "period_order"
    claim = ClaimOut(text="Tổng tài sản năm 2025 {c1} so với năm 2024.", sources=["fact:a25"], evidence="")
    v = verify_claims([claim], Context(facts=[f25, f24]), calcs)[0]
    assert not v.ok and "17,87" not in v.text
    good = execute_calcs([spec("growth", "fact:a25", "fact:a24")], {"a25": f25, "a24": f24})
    assert good["c1"].rendered == "tăng 21,76%"


def test_zero_growth_unchanged():
    G = F | {"z": TA25.model_copy(update={"fact_id": "z", "period": "FY2023"})}
    assert execute_calcs([spec("growth", "fact:ta25", "fact:z")], G)["c1"].rendered == "không đổi"


def test_growth_rejects_different_metric():
    G = F | {
        "x": fact(
            fact_id="x", label_norm="cho vay khach hang", unit="tỷ đồng", period="FY2024", value=Decimal(1)
        )
    }
    r = execute_calcs([spec("growth", "fact:ta25", "fact:x")], G)["c1"]
    assert not r.ok and r.error == "metric_mismatch"


def test_growth_rejects_unit_mismatch():
    G = F | {
        "m": fact(
            fact_id="m", label_norm="tong tai san", unit="triệu đồng", period="FY2024", value=Decimal(5)
        )
    }
    r = execute_calcs([spec("growth", "fact:ta25", "fact:m")], G)["c1"]
    assert not r.ok and r.error == "unit_mismatch"


def test_same_period_rejected():
    r = execute_calcs([spec("diff", "fact:ta25", "fact:ta25")], F)["c1"]
    assert not r.ok and r.error == "same_period"


def test_unknown_operand():
    r = execute_calcs([spec("growth", "fact:nope", "fact:ta24")], F)["c1"]
    assert not r.ok and r.error == "unknown_operand"


def test_diff_money_keeps_unit_and_decimals():
    r = execute_calcs([spec("diff", "fact:ta25", "fact:ta24")], F)["c1"]
    assert r.rendered == "tăng 213.545 tỷ đồng" and r.unit == "tỷ đồng"


def test_diff_money_keeps_operand_decimals():
    G = {
        "a": fact(fact_id="a", label_norm="m", unit="tỷ đồng", period="FY2025", value=Decimal("12.50")),
        "b": fact(fact_id="b", label_norm="m", unit="tỷ đồng", period="FY2024", value=Decimal("10.25")),
    }
    assert execute_calcs([spec("diff", "fact:a", "fact:b")], G)["c1"].rendered == "tăng 2,25 tỷ đồng"


def test_nested_diff_gives_points():
    r = nested()["c3"]
    assert r.ok and r.unit == "điểm %"
    assert r.rendered == "tăng 0,41 điểm %"


def test_two_level_nesting_rejected():
    res = execute_calcs(
        [
            spec("growth", "fact:ta25", "fact:ta24", id="c1"),
            spec("growth", "fact:l25", "fact:l24", id="c2"),
            spec("diff", "calc:c1", "calc:c2", id="c3"),
            spec("diff", "calc:c3", "calc:c1", id="c4"),
        ],
        F,
    )
    assert res["c3"].ok
    assert not res["c4"].ok and res["c4"].error == "nesting_too_deep"


def test_cycle_rejected():
    res = execute_calcs(
        [spec("diff", "calc:c2", "fact:ta24", id="c1"), spec("diff", "calc:c1", "fact:ta24", id="c2")], F
    )
    assert not res["c1"].ok and not res["c2"].ok
    assert res["c1"].error == "cycle" and res["c2"].error == "cycle"


def test_divide_by_zero():
    G = F | {
        "zero": fact(
            fact_id="zero", label_norm="tong tai san", unit="tỷ đồng", period="FY2023", value=Decimal(0)
        )
    }
    r = execute_calcs([spec("growth", "fact:ta25", "fact:zero")], G)["c1"]
    assert not r.ok and r.error == "non_positive_base"
    r = execute_calcs([spec("ratio", "fact:ta25", "fact:zero")], G)["c1"]
    assert r.error == "division_by_zero"


def test_ratio_money_uses_vnd():
    G = F | {
        "m": fact(
            fact_id="m",
            label_norm="khac",
            unit="triệu đồng",
            period="FY2025",
            value=Decimal("976000000"),
            value_vnd=Decimal("976000000000000"),
        )
    }
    r = execute_calcs([spec("ratio", "fact:ta25", "fact:m")], G)["c1"]
    assert r.ok and r.unit == "lần" and r.rendered == "1,22 lần"


def test_ratio_not_comparable():
    G = F | {"p": fact(fact_id="p", unit="%", value=Decimal(5))}
    assert execute_calcs([spec("ratio", "fact:ta25", "fact:p")], G)["c1"].error == "not_comparable"


def test_convert():
    r = execute_calcs([spec("convert", "fact:ta25", to_unit="nghìn tỷ đồng")], F)["c1"]
    assert r.rendered == "1.192,34 nghìn tỷ đồng"


def test_convert_bad_unit():
    assert execute_calcs([spec("convert", "fact:ta25", to_unit="%")], F)["c1"].error == "bad_convert"


def test_fill_reports_unknown():
    assert fill_placeholders("A {c9}", {}) == ("A {c9}", ["c9"])


def test_fill_replaces_ok_and_reports_failed():
    res = execute_calcs(
        [spec("growth", "fact:ta25", "fact:ta24"), spec("growth", "fact:x", "fact:ta24", id="c2")], F
    )
    assert fill_placeholders("Tài sản {c1}; {c2}", res) == ("Tài sản tăng 21,82%; {c2}", ["c2"])


def test_operands_recursive():
    assert set(operand_facts("c3", nested())) == {"ta25", "ta24", "l25", "l24"}


def test_growth_negative_base_rejected_but_diff_ok():
    G = {
        "a": fact(fact_id="a", label_norm="m", unit="tỷ đồng", period="FY2025", value=Decimal(50)),
        "b": fact(fact_id="b", label_norm="m", unit="tỷ đồng", period="FY2024", value=Decimal(-100)),
    }
    r = execute_calcs([spec("growth", "fact:a", "fact:b")], G)["c1"]
    assert not r.ok and r.error == "non_positive_base"
    assert execute_calcs([spec("diff", "fact:a", "fact:b")], G)["c1"].rendered == "tăng 150 tỷ đồng"

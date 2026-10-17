from decimal import Decimal

from factories import fact, table, table_with, tile
from ircb.ingestion.facts import detect_period, fact_embed_text, facts_from_kpi, facts_from_table, label_norm
from ircb.ingestion.tables import Cell, TableRow


def test_negative_and_dash() -> None:
    fs = facts_from_table(table_with(["(415.884)", "-"]), chapter="Báo cáo tài chính")
    assert [f.value for f in fs] == [Decimal("-415884"), Decimal("0")]
    assert fs[1].raw == "-" and fs[0].chapter == "Báo cáo tài chính"


def test_value_vnd() -> None:
    f = facts_from_table(table_with(["1.192.344.137"], unit="triệu đồng"), None)[0]
    assert f.value_vnd == Decimal("1192344137000000")


def test_fact_id_and_fields() -> None:
    f = facts_from_table(table_with(["5", "7"]), None)[1]
    assert f.fact_id == "p149R_t02_r00_c1" and f.doc_id == "tcb-ar-2025"
    assert f.period == "2024-12-31" and f.pdf_page == 149 and f.printed_pages == [297]
    assert f.source == "table" and f.label_norm == "cho vay khach hang" and f.bbox == [1.0, 0.0, 2.0, 1.0]


def test_non_numeric_cell_skipped() -> None:
    fs = facts_from_table(table_with(["abc", "", "3"]), None)
    assert [f.fact_id[-2:] for f in fs] == ["c2"]


def test_no_unit_no_facts() -> None:
    assert facts_from_table(table_with(["1"], unit=None), None) == []


def test_percent_cell() -> None:
    t = table_with(["12,5%", "3"], cols=["% So sánh với > Kế hoạch", "2025"])
    a, b = facts_from_table(t, None)
    assert (a.unit, a.value, a.value_vnd, a.period) == ("%", Decimal("12.5"), None, None)
    assert b.unit == "triệu đồng" and b.period == "FY2025"


def test_total_row_flags() -> None:
    cell = Cell("2025", "9", (0.0, 0.0, 1.0, 1.0))
    t = table(rows=[TableRow("Tổng (A)", 1, "A", True, None, [cell])])
    f = facts_from_table(t, None)[0]
    assert f.is_total and f.parent_label == "A" and f.row_level == 1


def test_period() -> None:
    assert (
        detect_period("31/12/2024"),
        detect_period("Năm 2025"),
        detect_period("% So sánh với > Kế hoạch"),
    ) == ("2024-12-31", "FY2025", None)
    assert detect_period("2025") == "FY2025" and detect_period("2025 > Kế hoạch") == "FY2025"
    assert detect_period("Thuyết minh") is None


def test_label_norm() -> None:
    assert label_norm("  Đầu tư  Chứng khoán ") == "dau tu chung khoan"


def test_kpi_change_fact() -> None:
    fs = facts_from_kpi(tile(), 30, half="R", index=2)
    assert [f.fact_id for f in fs] == ["p30R_k02", "p30R_k02_chg"]
    assert fs[0].value == Decimal("328.1") and fs[0].value_vnd == Decimal("328.1") * 10**12
    assert fs[1].unit == "%" and fs[1].direction == "up" and fs[1].value == Decimal("26.9")
    assert fs[1].change_basis == "N/N" and fs[1].value_vnd is None and fs[0].source == "kpi"


def test_kpi_without_change_or_unit() -> None:
    assert len(facts_from_kpi(tile(change=None), 30)) == 1
    assert facts_from_kpi(tile(unit=None), 30) == []
    assert facts_from_kpi(tile(value="TOP 1"), 30) == []


def test_embed_text() -> None:
    f = fact(
        statement="B02/TCTD-HN",
        table_title="BCTHTC",
        parent_label="Cho vay khách hàng",
        label="Cho vay khách hàng",
        col_path="31/12/2025",
        unit="triệu đồng",
    )
    assert fact_embed_text(f) == (
        "B02/TCTD-HN · BCTHTC > Cho vay khách hàng > Cho vay khách hàng · 31/12/2025 · triệu đồng"
    )
    assert fact_embed_text(fact(label="A", unit="%")) == "A · %"


def test_absolute_change_column_keeps_unit_and_vnd() -> None:
    t = table_with(["1.000", "5%"], cols=["Thay đổi > Số tiền", "So với cuối năm trước (%)"])
    a, b = facts_from_table(t, None)
    assert (a.unit, a.value_vnd, a.period) == ("triệu đồng", Decimal("1000") * 10**6, None)
    assert (b.unit, b.value_vnd, b.period) == ("%", None, None)


def test_kpi_cagr_change_is_the_percent_not_the_year() -> None:
    # real p.5 tile: change_raw "Tăng trưởng kép 2018–2025: 16,5%" once parsed as 2018
    t = tile(change="Tăng trưởng kép 2018–2025: 16,5%", basis="CAGR 2018–2025", direction="unknown")
    assert facts_from_kpi(t, 3, half="R")[1].value == Decimal("16.5")


def test_kpi_facts_carry_the_report_period() -> None:
    # a None period kept every KPI fact out of period-filtered fact lookup ("tổng tài sản 2025")
    rbg = facts_from_kpi(tile(context="Khối Ngân hàng Bán lẻ (RBG) · Điểm nhấn 2025"), 30, "R")
    assert [f.period for f in rbg] == ["FY2025", "FY2025"]
    assert facts_from_kpi(tile(context="Điểm nhấn 2024"), 30)[0].period == "FY2024"
    assert facts_from_kpi(tile(context="Mạng lưới giao dịch"), 30)[0].period == "FY2025"

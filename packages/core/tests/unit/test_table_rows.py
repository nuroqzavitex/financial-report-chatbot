from decimal import Decimal

from ircb.ingestion.tables import Cell, TableRow, cell_value, hierarchy


def _row(label: str, *values: str) -> TableRow:
    cells = [Cell(f"c{j}", v, (0.0, 0.0, 0.0, 0.0)) for j, v in enumerate(values)]
    return TableRow(label, 0, None, False, None, cells)


def _run(spec: list[tuple[str, float, bool, tuple[str, ...]]]) -> list[TableRow]:
    rows = [_row(label, *vals) for label, _x, _b, vals in spec]
    label_x = [(i, x, b) for i, (label, x, b, _v) in enumerate(spec) if label]
    return hierarchy(rows, label_x)


def test_indent_and_bold_give_levels_and_parents() -> None:
    out = _run(
        [
            ("Cho vay khách hàng", 100.0, True, ("757.118.751",)),
            ("Cho vay khách hàng", 104.0, False, ("767.617.129",)),
            ("Dự phòng rủi ro cho vay khách hàng", 104.0, False, ("(10.498.378)",)),
        ]
    )
    assert [r.row_level for r in out] == [0, 2, 2]
    assert out[1].parent_label == "Cho vay khách hàng" and out[0].parent_label is None


def test_unlabelled_total_of_top_level_rows_is_grand_total() -> None:
    # p.329: group parents carry their own subtotal; the unlabelled row sums the parents
    out = _run(
        [
            ("Tiền gửi không kỳ hạn", 100.0, True, ("13.060.774",)),
            ("- Bằng VND", 104.0, False, ("4.125.406",)),
            ("- Bằng ngoại tệ", 104.0, False, ("8.935.368",)),
            ("Tiền gửi có kỳ hạn", 100.0, True, ("95.082.619",)),
            ("- Bằng VND", 104.0, False, ("67.362.419",)),
            ("- Bằng ngoại tệ", 104.0, False, ("27.720.200",)),
            ("", 0.0, False, ("108.143.393",)),
        ]
    )
    total = out[-1]
    assert total.is_total and total.label == "Tổng cộng" and total.parent_label is None


def test_unlabelled_subtotal_of_a_value_less_group() -> None:
    out = _run(
        [
            ("Tiền gửi", 100.0, True, ("",)),
            ("Bằng VND", 104.0, False, ("10",)),
            ("Bằng ngoại tệ", 104.0, False, ("(3)",)),
            ("", 0.0, False, ("7",)),
        ]
    )
    assert out[-1].label == "Tổng (Tiền gửi)" and out[-1].parent_label == "Tiền gửi"


def test_total_after_total_and_rows_after_a_grand_total() -> None:
    out = _run(
        [
            ("Nợ đủ tiêu chuẩn", 100.0, False, ("700", "98,34")),
            ("Nợ cần chú ý", 100.0, False, ("23", "1,66")),
            ("", 0.0, False, ("723", "100,00")),
            ("Cho vay ký quỹ", 100.0, False, ("44", "")),
            ("", 0.0, False, ("767", "")),
        ]
    )
    assert [r.label for r in out] == [
        "Nợ đủ tiêu chuẩn",
        "Nợ cần chú ý",
        "Tổng cộng",
        "Cho vay ký quỹ",
        "Tổng cộng",
    ]
    assert out[3].parent_label is None


def test_unverifiable_total_is_not_attributed() -> None:
    out = _run([("A", 100.0, True, ("5",)), ("B", 104.0, False, ("1",)), ("", 0.0, False, ("99",))])
    assert out[-1].label == "Tổng" and out[-1].parent_label is None and out[-1].is_total


def test_cell_value_dashes_and_blanks() -> None:
    assert cell_value("-") == 0 and cell_value("–") == 0 and cell_value("—") == 0
    assert cell_value("(10.498.378)") == Decimal("-10498378")
    assert cell_value("") is None and cell_value("Chủ tịch") is None


def test_non_numeric_unlabelled_row_continues_the_row_above() -> None:
    # review fix 1: a text-only row without a label is a wrapped continuation, never a total
    out = _run([("Kênh", 100.0, False, ("Hàng năm",)), ("", 0.0, False, ("Thường xuyên",))])
    assert out[-1].label == "Kênh" and not out[-1].is_total
    assert out[-1].row_level == out[0].row_level and out[-1].parent_label == out[0].parent_label


def test_bullet_labels_are_one_level_deeper() -> None:
    # review fix 3 (controller ruling): "- ", "+ ", "• " add one indent level before parenting
    out = _run(
        [
            ("Cam kết giao dịch hối đoái", 100.0, False, ("417.321.503",)),
            ("- Cam kết mua ngoại tệ giao ngay", 100.0, False, ("6.372.664",)),
            ("+ Khác", 100.0, False, ("1",)),
            ("• Khác nữa", 100.0, False, ("1",)),
            ("Bảo lãnh khác", 100.0, False, ("5",)),
        ]
    )
    assert [r.row_level for r in out] == [1, 2, 2, 2, 1]
    assert all(r.parent_label == "Cam kết giao dịch hối đoái" for r in out[1:4])
    assert out[4].parent_label is None


def test_total_parent_resolved_by_row_not_label() -> None:
    # review fix 4: parent and child share a label; the subtotal belongs to the value-less parent
    out = _run(
        [
            ("Tiền gửi", 100.0, True, ("",)),
            ("Tiền gửi", 104.0, False, ("10",)),
            ("Khác", 104.0, False, ("5",)),
            ("", 0.0, False, ("15",)),
        ]
    )
    assert out[-1].label == "Tổng (Tiền gửi)" and out[-1].row_level == 0 and out[-1].is_total


def test_markdown_depth_follows_row_level_not_label() -> None:
    # review fix 2: a sibling of a child that shares its parent's label must not nest under the child
    from ircb.ingestion.tables import ExtractedTable, table_to_markdown

    rows = _run(
        [
            ("Cho vay khách hàng", 100.0, True, ("757",)),
            ("Cho vay khách hàng", 104.0, False, ("767",)),
            ("Dự phòng rủi ro cho vay khách hàng", 104.0, False, ("(10)",)),
        ]
    )
    t = ExtractedTable("p1L_t01", 1, "L", [1], (0, 0, 1, 1), None, None, None, None, False, None, rows)
    body = [ln for ln in table_to_markdown(t).splitlines() if "757" in ln or "767" in ln or "(10)" in ln]
    assert body[0].startswith("| Cho vay")
    assert body[1].startswith("| · Cho vay") and body[2].startswith("| · Dự phòng")

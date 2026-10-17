import pymupdf as fitz
import pytest
from ircb.ingestion.tables import Cell, ExtractedTable, TableRow, extract_tables, table_to_markdown

pytestmark = pytest.mark.requires_pdf


def find_table(tables: list[ExtractedTable], label: str) -> ExtractedTable:
    for t in tables:
        if any(r.label == label for r in t.rows):
            return t
    raise AssertionError(f"no table with row {label!r}")


def cell(row: TableRow, col_path: str) -> Cell:
    for c in row.cells:
        if c.col_path == col_path:
            return c
    raise AssertionError(f"no column {col_path!r} in {[c.col_path for c in row.cells]}")


def test_parent_child_rows_297(doc: fitz.Document) -> None:
    t = find_table(extract_tables(doc, 149), label="Cho vay khách hàng")
    rows = [r for r in t.rows if r.label == "Cho vay khách hàng"]
    parent, child = sorted(rows, key=lambda r: r.row_level)
    assert cell(parent, "31/12/2025").raw == "757.118.751"
    assert cell(child, "31/12/2025").raw == "767.617.129"
    assert cell(parent, "31/12/2024").raw == "623.634.271"
    assert child.row_level > parent.row_level and child.parent_label is not None
    assert t.statement == "B02/TCTD-HN" and t.unit == "triệu đồng"


def test_297_context(doc: fitz.Document) -> None:
    t = find_table(extract_tables(doc, 149), label="Cho vay khách hàng")
    assert t.half == "R" and t.printed_pages == [297] and not t.spans_gutter
    assert t.table_id.startswith("p149R_t")
    rows = [r for r in t.rows if r.label == "Cho vay khách hàng"]
    parent, child = sorted(rows, key=lambda r: r.row_level)
    assert child.parent_label == "Cho vay khách hàng" and child.note_ref == "9"
    assert parent.note_ref is None
    # "Thuyết minh" feeds note_ref and is not a value column
    assert [c.col_path for c in parent.cells] == ["31/12/2025", "31/12/2024"]
    total = next(r for r in t.rows if r.label == "TỔNG TÀI SẢN")
    assert cell(total, "31/12/2025").raw == "1.192.344.137"
    empty = next(r for r in t.rows if r.label == "Chứng khoán đầu tư giữ đến ngày đáo hạn")
    assert cell(empty, "31/12/2025").raw == "-"


def test_gutter_table_374_375(doc: fitz.Document) -> None:
    g = [t for t in extract_tables(doc, 188) if t.spans_gutter]
    assert g and g[0].printed_pages == [374, 375]
    assert all(r.label for r in g[0].rows if any(c.raw for c in r.cells))  # không có số mồ côi


def test_gutter_table_not_duplicated_by_halves(doc: fitz.Document) -> None:
    tables = extract_tables(doc, 188)
    g = next(t for t in tables if t.spans_gutter)
    assert g.half == "G" and g.table_id == "p188G_t01" and g.unit == "triệu đồng"
    # the halves must not re-emit fragments of the gutter table (orphan numbers on the right)
    gx0, gy0, gx1, gy1 = g.bbox
    for t in tables:
        if t is g:
            continue
        x0, y0, x1, y1 = t.bbox
        assert y1 <= gy0 or y0 >= gy1 or x1 <= gx0 or x0 >= gx1
    # the last row has three values glued into one find_tables cell; they must be split by column
    last = next(r for r in g.rows if r.label == "Mức chênh nhạy cảm với lãi suất nội bảng")
    assert cell(last, "Ảnh hưởng do định lại lãi suất trong khoảng thời gian > Từ trên 6–12 tháng").raw == (
        "62.653.580"
    )
    assert cell(last, "Tổng cộng").raw == "190.609.272"


def test_multilevel_header_14(doc: fitz.Document) -> None:
    t = extract_tables(doc, 8)[0]
    assert any(">" in c.col_path for r in t.rows for c in r.cells)


def test_header_paths_and_unit_14(doc: fitz.Document) -> None:
    t = extract_tables(doc, 8)[0]
    assert t.printed_pages == [14] and t.half == "L"
    assert t.unit == "tỷ đồng"  # from the "Đơn vị: Tỷ đồng" line above the table
    row = next(r for r in t.rows if r.label == "Dư nợ tín dụng")  # superscript "1" dropped
    assert [c.col_path for c in row.cells] == [
        "2024",
        "2025 > Kế hoạch",
        "2025 > Thực hiện",
        "% So sánh với > 2024",
        "% So sánh với > Kế hoạch",
    ]
    assert cell(row, "2025 > Thực hiện").raw == "758.285"
    assert t.title is not None and "KẾT QUẢ NỔI BẬT" in t.title


def test_markdown_render(doc: fitz.Document) -> None:
    t = extract_tables(doc, 8)[0]
    md = table_to_markdown(t)
    assert "| 2025 > Thực hiện |" in md.replace("  ", " ")
    assert "758.285" in md and "Dư nợ tín dụng" in md
    assert "tỷ đồng" in md and "[tr. 14]" in md


def test_chapter_default_unit_fs(doc: fitz.Document) -> None:
    # every table in the consolidated FS chapter has a unit (header, "Đơn vị:" or chapter default)
    for p in (150, 166, 177):
        for t in extract_tables(doc, p):
            assert t.unit is not None, t.table_id


def test_unlabelled_total_is_grand_total_329(doc: fitz.Document) -> None:
    # 108.143.393 = 13.060.774 (không kỳ hạn) + 95.082.619 (có kỳ hạn), not a subtotal of "có kỳ hạn"
    t = find_table(extract_tables(doc, 165), label="Tiền gửi có kỳ hạn")
    total = next(r for r in t.rows if r.is_total)
    assert total.label == "Tổng cộng" and total.parent_label is None
    assert cell(total, "31/12/2025").raw == "108.143.393"
    assert t.note_no == "7.1" and t.printed_pages == [329]


def test_split_header_is_borrowed_377(doc: fitz.Document) -> None:
    # find_tables returns the header block and the body as two tables; they must be rejoined
    t = find_table(extract_tables(doc, 189), label="Tiền gửi tại NHNN")
    row = next(r for r in t.rows if r.label == "Tiền gửi tại NHNN")
    assert cell(row, "USD được quy đổi").raw == "13.682.567"
    assert t.unit == "triệu đồng" and t.note_no == "45.2"


def test_text_table_has_no_fake_total_138(doc: fitz.Document) -> None:
    # review fix 1: text-only tables (p.275) must not get "Tổng" rows nor swallow all rows as header
    for p in (122, 138):
        for t in extract_tables(doc, p):
            assert not any(r.is_total for r in t.rows), t.table_id
    t = next(t for t in extract_tables(doc, 138) if t.table_id == "p138R_t01")
    assert len(t.rows) > 3


def test_markdown_sibling_depth_297(doc: fitz.Document) -> None:
    t = find_table(extract_tables(doc, 149), label="Cho vay khách hàng")
    md = table_to_markdown(t).splitlines()
    gross = next(ln for ln in md if "767.617.129" in ln)
    prov = next(ln for ln in md if "(10.498.378)" in ln)
    assert gross.split("Cho vay")[0] == prov.split("Dự phòng")[0]  # same indent prefix


def test_bullet_children_300_345(doc: fitz.Document) -> None:
    t = next(t for t in extract_tables(doc, 150) if t.table_id == "p150R_t01")
    by = {r.label: r for r in t.rows}
    assert by["- Cam kết mua ngoại tệ giao ngay"].parent_label == "Cam kết giao dịch hối đoái"
    assert by["- Cam kết hoán đổi lãi suất bằng VND"].parent_label == "Các cam kết khác"
    t = find_table(extract_tables(doc, 173), label="- Dự phòng chung")
    child = next(r for r in t.rows if r.label == "- Dự phòng chung")
    assert child.parent_label is not None and child.row_level > min(r.row_level for r in t.rows)

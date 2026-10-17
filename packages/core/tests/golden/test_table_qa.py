from collections.abc import Iterator

import pymupdf as fitz
import pytest
from ircb.ingestion.table_qa import QAResult, coverage, fallback_tables, qa_tables
from ircb.ingestion.tables import Cell, ExtractedTable, TableRow, extract_tables

FS_PAGES = range(147, 194)


# ---------------------------------------------------------------- synthetic fixtures


def _put(page: fitz.Page, x: float, y: float, text: str, size: float = 7.5) -> None:
    page.insert_text((x, y), text, fontname="F0", fontsize=size)  # type: ignore[no-untyped-call]


def _blank() -> tuple[fitz.Document, fitz.Page]:
    d = fitz.open()
    page = d.new_page(width=595, height=842)  # type: ignore[no-untyped-call]
    # Droid Sans Fallback ships with MuPDF; it lacks some Vietnamese letters, so labels use only ones it has
    page.insert_font(fontname="F0", fontbuffer=fitz.Font("cjk").buffer)  # type: ignore[no-untyped-call]
    return d, page


@pytest.fixture
def multiline_page() -> Iterator[fitz.Page]:
    """Borderless table: header 2025 | 2024, a two-line label whose numbers sit on its last line."""
    d, page = _blank()
    _put(page, 360, 100, "31/12/2025")
    _put(page, 470, 100, "31/12/2024")
    _put(page, 50, 120, "Cho vay khách hàng")
    _put(page, 370, 120, "1.000.000")
    _put(page, 480, 120, "900.000")
    _put(page, 60, 132, "Trong đó:")
    _put(page, 60, 142, "Trái phiếu")
    _put(page, 380, 142, "400.000")
    _put(page, 480, 142, "350.000")
    _put(page, 60, 154, "Tín phiếu")
    _put(page, 380, 154, "600.000")
    _put(page, 480, 154, "550.000")
    _put(
        page,
        50,
        200,
        "Theo thuyết minh chi tiết, khoản cho vay khác là 12.345 và không thuộc danh sách bên trên.",
        8.5,
    )
    yield page
    d.close()


@pytest.fixture
def headerless_page() -> Iterator[fitz.Page]:
    """Continuation table without its own header: column names come from ``header_hint``."""
    d, page = _blank()
    _put(page, 50, 100, "Cho vay ngân hàng")
    _put(page, 370, 100, "5.000.000")
    _put(page, 480, 100, "4.000.000")
    _put(page, 50, 112, "Cho vay trung và dài")
    _put(page, 370, 112, "7.000.000")
    _put(page, 480, 112, "6.000.000")
    yield page
    d.close()


def _hint() -> ExtractedTable:
    cells = [
        Cell("31/12/2025", "1", (355.0, 90.0, 420.0, 102.0)),
        Cell("31/12/2024", "1", (465.0, 90.0, 530.0, 102.0)),
    ]
    row = TableRow("x", 0, None, False, None, cells)
    return ExtractedTable(
        "p1S_t01",
        1,
        "S",
        [1],
        (40.0, 80.0, 540.0, 110.0),
        "9. CHO VAY",
        "9",
        None,
        "triệu đồng",
        False,
        None,
        [row],
    )


def _row(t: ExtractedTable, label: str) -> TableRow:
    return next(r for r in t.rows if r.label == label)


def _val(r: TableRow, col: str) -> str:
    return next(c.raw for c in r.cells if c.col_path == col)


# ---------------------------------------------------------------- synthetic tests


def test_multiline_label_binds_last_line(multiline_page: fitz.Page) -> None:
    tables = fallback_tables(multiline_page, multiline_page.rect, None)
    assert len(tables) == 1
    t = tables[0]
    bond = _row(t, "Trái phiếu")
    assert _val(bond, "31/12/2025") == "400.000" and _val(bond, "31/12/2024") == "350.000"
    # the first label line keeps no numbers; it is not glued onto the line that carries them
    group = _row(t, "Trong đó:")
    assert all(not c.raw for c in group.cells)
    assert (
        bond.parent_label == "Cho vay khách hàng" and bond.row_level > _row(t, "Cho vay khách hàng").row_level
    )
    assert not any(r.label == "Trong đó: Trái phiếu" for r in t.rows)


def test_fallback_shape_and_prose_excluded(multiline_page: fitz.Page) -> None:
    t = fallback_tables(multiline_page, multiline_page.rect, None)[0]
    assert t.table_id == "p1S_f01" and t.half == "S" and t.printed_pages == [1]
    assert [c.col_path for c in t.rows[0].cells] == ["31/12/2025", "31/12/2024"]
    assert all("12.345" not in c.raw for r in t.rows for c in r.cells)
    assert t.bbox[3] < 190  # the paragraph below is not part of the table
    assert _val(_row(t, "Cho vay khách hàng"), "31/12/2025") == "1.000.000"


def test_header_hint_names_columns(headerless_page: fitz.Page) -> None:
    plain = fallback_tables(headerless_page, headerless_page.rect, None)[0]
    assert [c.col_path for c in plain.rows[0].cells] == ["col1", "col2"]
    t = fallback_tables(headerless_page, headerless_page.rect, _hint())[0]
    assert [c.col_path for c in t.rows[0].cells] == ["31/12/2025", "31/12/2024"]
    assert _val(_row(t, "Cho vay trung và dài"), "31/12/2024") == "6.000.000"
    assert t.unit == "triệu đồng"


def test_coverage_counts_only_table_numbers(multiline_page: fitz.Page) -> None:
    tables = fallback_tables(multiline_page, multiline_page.rect, None)
    assert coverage(multiline_page, multiline_page.rect, tables) == (7, 6)
    assert coverage(multiline_page, multiline_page.rect, []) == (7, 0)


# ---------------------------------------------------------------- golden (PDF) tests


@pytest.mark.requires_pdf
def test_fs_chapter_coverage(doc: fitz.Document) -> None:
    res = [r for p in FS_PAGES for r in qa_tables(doc, p)[1]]
    assert sum(r.covered for r in res) / sum(r.numbers for r in res) >= 0.99


@pytest.mark.requires_pdf
@pytest.mark.parametrize(
    "pdf_page,half", [(152, "R"), (153, "L"), (176, "R"), (182, "R"), (188, "R"), (191, "L")]
)
def test_low_halves_improved(doc: fitz.Document, pdf_page: int, half: str) -> None:
    r = next(r for r in qa_tables(doc, pdf_page)[1] if r.half == half)
    assert r.ratio >= 0.95 or r.used_fallback


@pytest.mark.requires_pdf
def test_qa_result_fields_and_tables(doc: fitz.Document) -> None:
    tables, res = qa_tables(doc, 149)
    assert [r.half for r in res] == ["L", "R"]
    assert all(isinstance(r, QAResult) and r.pdf_page == 149 for r in res)
    right = res[1]
    assert right.ratio == right.covered / right.numbers and right.none_columns == 0
    assert not right.used_fallback
    assert [t.table_id for t in tables] == [t.table_id for t in extract_tables(doc, 149)]


@pytest.mark.requires_pdf
def test_fallback_rebuilds_ruled_table_297(doc: fitz.Document) -> None:
    page = doc[148]
    W, H = page.rect.width, page.rect.height
    tables = fallback_tables(page, fitz.Rect(W / 2, 45, W, H), None)  # type: ignore[no-untyped-call]
    t = next(t for t in tables if any(r.label == "TỔNG TÀI SẢN" for r in t.rows))
    assert t.table_id.startswith("p149R_f") and t.printed_pages == [297]
    assert _val(_row(t, "TỔNG TÀI SẢN"), "31/12/2025") == "1.192.344.137"
    assert _row(t, "TỔNG TÀI SẢN").note_ref is None


def test_qa_keeps_fallback_when_it_covers_more(multiline_page: fitz.Page) -> None:
    tables, res = qa_tables(multiline_page.parent, 1)  # borderless: find_tables sees nothing
    assert [t.table_id for t in tables] == ["p1S_f01"]
    (r,) = res
    assert r.half == "S" and r.used_fallback and (r.numbers, r.covered) == (7, 6)
    assert r.ratio == 6 / 7 and r.none_columns == 0


@pytest.mark.requires_pdf
def test_fallback_wrapped_labels_and_spanning_header_379(doc: fitz.Document) -> None:
    page = doc[189]
    W, H = page.rect.width, page.rect.height
    t = fallback_tables(page, fitz.Rect(W / 2, 45, W, H), None)[0]  # type: ignore[no-untyped-call]
    # top-aligned wrapped label: continuation lines join the numbered row above
    row = _row(t, "Tiền gửi và cấp tín dụng cho các TCTD khác (*)")
    assert _val(row, "Tổng cộng") == "115.139.462"
    # an upper header cell centred over several columns names all of them, and no more
    assert _val(row, "Trong hạn > Đến 1 tháng") == "96.515.249"
    assert _val(row, "Trong hạn > Trên 5 năm") == "-"
    assert _val(row, "Quá hạn > Trên 3 tháng") == "87.783"

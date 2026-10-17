"""Fixture builders with sensible defaults (kept out of production models)."""

from decimal import Decimal
from typing import Any

from ircb.domain.models import Fact
from ircb.ingestion.kpi import KpiTile
from ircb.ingestion.tables import Cell, ExtractedTable, TableRow

BOX = (0.0, 0.0, 10.0, 10.0)


def fact(**kw: Any) -> Fact:
    base: dict[str, Any] = {
        "fact_id": "t_r00_c0",
        "doc_id": "tcb-ar-2025",
        "printed_pages": [1],
        "chapter": None,
        "statement": None,
        "note_no": None,
        "table_title": None,
        "label": "x",
        "label_norm": "x",
        "parent_label": None,
        "row_level": 0,
        "is_total": False,
        "col_path": None,
        "period": None,
        "value": Decimal(1),
        "unit": "triệu đồng",
        "value_vnd": None,
        "raw": None,
        "source": "table",
        "pdf_page": 1,
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "direction": None,
        "change_basis": None,
    }
    base.update(kw)
    return Fact(**base)


def table(rows: list[TableRow], **kw: Any) -> ExtractedTable:
    base: dict[str, Any] = {
        "table_id": "p149R_t02",
        "pdf_page": 149,
        "half": "R",
        "printed_pages": [297],
        "bbox": (596.0, 120.0, 1150.0, 520.0),
        "title": "Báo cáo tình hình tài chính hợp nhất",
        "note_no": None,
        "statement": "B02/TCTD-HN",
        "unit": "triệu đồng",
        "spans_gutter": False,
        "continues": None,
        "rows": rows,
    }
    base.update(kw)
    return ExtractedTable(**base)


def table_with(
    raws: list[str],
    unit: str | None = "triệu đồng",
    cols: list[str] | None = None,
    **kw: Any,
) -> ExtractedTable:
    """One-row table whose cells hold ``raws``."""
    cols = cols or [f"31/12/{2025 - i}" for i in range(len(raws))]
    cells = [
        Cell(c, r, (float(i), 0.0, float(i + 1), 1.0))
        for i, (c, r) in enumerate(zip(cols, raws, strict=True))
    ]
    row = TableRow("Cho vay khách hàng", 0, None, False, None, cells)
    return table(rows=[row], unit=unit, **kw)


def gutter_table() -> ExtractedTable:
    t = table_with(["1", "2"], table_id="p188_t01", pdf_page=188, half="S", printed_pages=[374, 375])
    t.spans_gutter = True
    return t


def tile(
    label: str = "Dư nợ vay",
    value: str = "328,1",
    unit: str | None = "nghìn tỷ đồng",
    change: str | None = "26,9%",
    direction: str = "up",
    basis: str | None = "N/N",
    context: str = "Khối Ngân hàng Bán lẻ",
) -> KpiTile:
    return KpiTile(label, value, unit, "", change, basis, direction, BOX, 30, context)  # type: ignore[arg-type]

"""Fact normalisation: table cells and KPI tiles become ``Fact`` records (spec §5.5)."""

import re
import unicodedata

from ircb.domain.models import Fact
from ircb.domain.numbers_vn import parse_vn
from ircb.domain.units import to_vnd
from ircb.ingestion.kpi import KpiTile
from ircb.ingestion.tables import ExtractedTable, TableRow, cell_value

DOC_ID = "tcb-ar-2025"
REPORT_PERIOD = "FY2025"  # KPI tiles of the 2025 annual report show 2025 values unless titled otherwise

_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/((?:19|20)\d{2})\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_NUM = re.compile(r"\d[\d.,]*")
_PCT_NUM = re.compile(r"(\d[\d.,]*)\s*%")
_COMPARISON_MARKERS = ("%", "so sánh", "so với", "thay đổi", "tăng trưởng")


def label_norm(s: str) -> str:
    """Lower-case, diacritics stripped (đ -> d), whitespace collapsed."""
    s = s.lower().replace("đ", "d")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _is_comparison(col_path: str) -> bool:
    low = col_path.lower()
    return any(m in low for m in _COMPARISON_MARKERS)


def detect_period(col_path: str) -> str | None:
    """``31/12/2025`` -> ``2025-12-31``; ``2025``/``Năm 2025`` -> ``FY2025``; %/comparison columns -> None."""
    if _is_comparison(col_path):
        return None
    m = _DATE.search(col_path)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    m2 = _YEAR.search(col_path)
    return f"FY{m2.group(0)}" if m2 else None


def fact_embed_text(f: Fact) -> str:
    path = " > ".join(p for p in (f.table_title, f.parent_label, f.label) if p)
    return " · ".join(p for p in (f.statement, path, f.col_path, f.unit) if p)


def row_facts(t: ExtractedTable, ri: int, row: TableRow, chapter: str | None) -> list[Fact]:
    if t.unit is None:  # spec: every fact has a unit
        return []
    out: list[Fact] = []
    for ci, cell in enumerate(row.cells):
        value = cell_value(cell.raw)
        if value is None:
            continue
        pct = cell.raw.strip().endswith("%") or "%" in cell.col_path
        unit = "%" if pct else t.unit
        out.append(
            Fact(
                fact_id=f"{t.table_id}_r{ri:02d}_c{ci}",
                doc_id=DOC_ID,
                printed_pages=list(t.printed_pages),
                chapter=chapter,
                statement=t.statement,
                note_no=t.note_no,
                table_title=t.title,
                label=row.label,
                label_norm=label_norm(row.label),
                parent_label=row.parent_label,
                row_level=row.row_level,
                is_total=row.is_total,
                col_path=cell.col_path,
                period=detect_period(cell.col_path),
                value=value,
                unit=unit,
                value_vnd=None if pct else to_vnd(value, unit),
                raw=cell.raw,
                source="table",
                pdf_page=t.pdf_page,
                bbox=[float(v) for v in cell.bbox],
                direction=None,
                change_basis=None,
            )
        )
    return out


def facts_from_table(t: ExtractedTable, chapter: str | None) -> list[Fact]:
    return [f for ri, row in enumerate(t.rows) for f in row_facts(t, ri, row, chapter)]


def kpi_change_number(tile: KpiTile) -> str | None:
    """Raw number text of the tile's change ("26,9" from "26,9% N/N"), if any.

    The number before "%", never a year: "Tăng trưởng kép 2018–2025: 16,5%" gives "16,5"."""
    if not tile.change_raw:
        return None
    if m := _PCT_NUM.search(tile.change_raw):
        return m.group(1)
    m = _NUM.search(tile.change_raw)
    return m.group(0) if m else None


def kpi_period(tile: KpiTile) -> str:
    """``FY<year>`` from the tile's heading ("Điểm nhấn 2024"), else the report year."""
    m = _YEAR.search(tile.context or "")
    return f"FY{m.group(0)}" if m else REPORT_PERIOD


def facts_from_kpi(
    tile: KpiTile,
    pdf_page: int,
    half: str = "L",
    index: int = 1,
    chapter: str | None = None,
) -> list[Fact]:
    """Main value fact plus, when present, a separate ``%`` change fact (``_chg``)."""
    if tile.unit is None:
        return []
    try:
        value = parse_vn(tile.value_raw).value
    except ValueError:
        return []
    fid = f"p{pdf_page}{half}_k{index:02d}"
    bbox = [float(v) for v in tile.bbox]

    def make(
        fact_id: str, col_path: str | None, v: object, unit: str, raw: str | None, direction: str | None
    ) -> Fact:
        return Fact.model_validate(
            {
                "fact_id": fact_id,
                "doc_id": DOC_ID,
                "printed_pages": [tile.printed_page],
                "chapter": chapter,
                "statement": None,
                "note_no": None,
                "table_title": tile.context or None,
                "label": tile.label,
                "label_norm": label_norm(tile.label),
                "parent_label": None,
                "row_level": 0,
                "is_total": False,
                "col_path": col_path,
                "period": kpi_period(tile),
                "value": v,
                "unit": unit,
                "value_vnd": to_vnd(value, unit) if unit != "%" else None,
                "raw": raw,
                "source": "kpi",
                "pdf_page": pdf_page,
                "bbox": bbox,
                "direction": direction,
                "change_basis": tile.change_basis if direction is not None else None,
            }
        )

    out = [make(fid, None, value, tile.unit, tile.value_raw, None)]
    num = kpi_change_number(tile)
    if num is not None:
        try:
            chg = parse_vn(num).value
        except ValueError:
            return out
        out.append(make(f"{fid}_chg", tile.change_basis, chg, "%", tile.change_raw, tile.direction))
    return out

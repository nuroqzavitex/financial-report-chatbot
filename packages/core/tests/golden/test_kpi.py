import re

import pymupdf as fitz
import pytest
from conftest import half_obj
from ircb.ingestion.kpi import KpiTile, arrow_direction, parse_kpi_tiles

pytestmark = pytest.mark.requires_pdf


def tiles(doc: fitz.Document, printed: int) -> list[KpiTile]:
    return parse_kpi_tiles(*half_obj(doc, printed))


def by_label(ts: list[KpiTile], needle: str) -> KpiTile:
    hits = [t for t in ts if needle.lower() in t.label.lower()]
    assert len(hits) == 1, f"{needle!r} matched {[t.label for t in hits]}"
    return hits[0]


# Ruling (controller, Task 8): p.5 visibly holds 12 tiles; the brief's 13 counted the
# "Điểm nhấn 2025" section heading as a tile.
def test_page5_twelve_tiles(doc: fitz.Document) -> None:
    t = tiles(doc, 5)
    assert len(t) == 12
    ta = by_label(t, "Tổng tài sản")
    assert (ta.value_raw, ta.unit) == ("1.192", "nghìn tỷ đồng")
    assert "21,8%" in (ta.change_raw or "")
    assert by_label(t, "CASA").value_raw == "40,4"
    assert by_label(t, "nợ xấu").value_raw == "1,13"
    toi = by_label(t, "Tổng thu nhập hoạt động")
    assert toi.value_raw == "53,4" and "16,5%" in (toi.change_raw or "")  # không phải 17,3%


def test_page5_units_bases_descriptions(doc: fitz.Document) -> None:
    t = tiles(doc, 5)
    ta = by_label(t, "Tổng tài sản")
    assert ta.change_basis == "so với năm trước"
    casa = by_label(t, "CASA")
    assert casa.unit == "%" and "dẫn đầu ngành" in casa.description.lower()
    npl = by_label(t, "nợ xấu")
    assert npl.unit == "%"
    assert "nhóm tốt nhất thị trường" in npl.description
    toi = by_label(t, "Tổng thu nhập hoạt động")
    assert toi.unit == "nghìn tỷ đồng" and toi.change_basis == "CAGR 2018–2025"
    assert by_label(t, "NAPAS").value_raw == "TOP 1"
    assert by_label(t, "Thị phần thu nhập từ hoạt động dịch vụ").value_raw == "16,0"  # 2-line label
    assert all("Điểm nhấn 2025" in x.context for x in t)


@pytest.mark.parametrize("printed", [5, 59])
def test_section_heading_is_not_a_tile(doc: fitz.Document, printed: int) -> None:
    t = tiles(doc, printed)
    assert not any("Điểm nhấn" in x.value_raw or "Điểm nhấn" in x.label for x in t)
    assert all(re.fullmatch(r"[~#]?\d[\d.,]*|TOP \d+", x.value_raw) for x in t)


def test_page59_rbg(doc: fitz.Document) -> None:
    t = tiles(doc, 59)
    assert len(t) == 4
    loan = by_label(t, "Dư nợ vay")
    assert (loan.value_raw, loan.unit, loan.direction) == ("328,1", "nghìn tỷ đồng", "up")
    assert loan.change_raw is not None and "26,9%" in loan.change_raw and "Bán lẻ" in loan.context
    assert loan.change_basis == "N/N"
    nii = by_label(t, "Thu nhập lãi thuần")  # finding #19: 9,4% belongs to NII, not Dư nợ vay
    assert nii.value_raw == "21,9" and "9,4%" in (nii.change_raw or "")
    assert "9,4%" not in (loan.change_raw or "") + loan.description


def test_page48_nine_tiles(doc: fitz.Document) -> None:
    t = tiles(doc, 48)
    assert len(t) == 9
    assert by_label(t, "Lợi nhuận trước thuế").value_raw == "32,5"
    assert by_label(t, "Lợi nhuận trước thuế").direction == "up"


def test_page81_cir_down(doc: fitz.Document) -> None:
    cir = by_label(tiles(doc, 81), "CIR")
    assert cir.direction == "down"
    assert cir.value_raw == "13,7" and "0,5%" in (cir.change_raw or "")


def test_arrow_direction_absent_is_unknown(doc: fitz.Document) -> None:
    page, h = half_obj(doc, 5)  # p.5 tiles have no vector arrows
    assert arrow_direction(page, (702.9, 602.6, 726.6, 614.8)) == "unknown"


def test_page117_tiles_captioned_below_take_the_caption_as_label(doc: fitz.Document) -> None:
    t = tiles(doc, 117)
    casa = by_label(t, "số dư CASA")
    assert (casa.value_raw, casa.unit) == ("16,6", "%")
    assert by_label(t, "Techcombank Rewards").value_raw == "13,1"
    assert not any("1,5x" in x.context or "2,8x" in x.context for x in t)  # figures are not region headings


def test_page77_label_from_description(doc: fitz.Document) -> None:
    pbt = by_label(tiles(doc, 77), "Lợi nhuận trước thuế năm 2025")
    assert (pbt.value_raw, pbt.unit) == ("7.109", "tỷ đồng")

import pymupdf as fitz
import pytest
from conftest import half_obj
from ircb.ingestion.glossary import load_glossary_extra, parse_glossary
from ircb.ingestion.prose import extract_prose

pytestmark = pytest.mark.requires_pdf


def test_glossary_pages(doc: fitz.Document) -> None:
    g = {e.term: e for e in parse_glossary(doc)}
    assert g["RBG"].printed_page == 387 and "Ngân hàng Bán lẻ" in g["RBG"].definition
    assert g["CASA"].printed_page == 386 and "Tiền gửi không kỳ hạn" in g["CASA"].definition
    assert len(g) >= 150


def test_glossary_bbox_covers_term_and_definition(doc: fitz.Document) -> None:
    e = next(e for e in parse_glossary(doc) if e.term == "CASA")
    assert e.bbox[2] > e.bbox[0] and e.bbox[3] > e.bbox[1]
    assert e.bbox[0] < 230  # starts at the term column of the 2nd sub-table


def test_glossary_extra() -> None:
    from pathlib import Path

    extra = load_glossary_extra(Path(__file__).resolve().parents[4] / "config" / "glossary_extra.json")
    assert extra["N/N"] == ["so với cùng kỳ năm trước"]
    assert extra["NPL"] == ["tỷ lệ nợ xấu", "nợ xấu"]
    assert extra["TM"] == ["thuyết minh"] and extra["total assets"] == ["tổng tài sản"]


def test_prose_page4(doc: fitz.Document) -> None:
    blocks = extract_prose(*half_obj(doc, 4), exclude_bboxes=[])
    text = " ".join(b.text for b in blocks)
    assert "302" in text and "29" in text and "34" in text
    assert all(b.printed_page == 4 for b in blocks)
    assert blocks[0].heading == "Chúng tôi là ai"
    assert blocks[0].text.startswith("Techcombank là một trong những ngân hàng")
    assert "302" in blocks[0].text or "302" in blocks[1].text
    assert blocks[1].heading is not None and "Ngân hàng tốt nhất" in blocks[1].heading
    assert blocks[1].text.startswith("Ngân hàng đầu tiên và duy nhất")


def test_prose_page5_numbers_are_not_headings(doc: fitz.Document) -> None:
    headings = {b.heading for b in extract_prose(*half_obj(doc, 5), exclude_bboxes=[])}
    assert "Tổng tài sản" in headings
    assert not any(h and any(ch.isdigit() for ch in h) and h.replace(" ", "")[0].isdigit() for h in headings)
    assert not any(h and ("1.192" in h or "86%" in h or "1,13%" in h) for h in headings)


def test_prose_excludes_regions(doc: fitz.Document) -> None:
    page, h = half_obj(doc, 4)
    full = " ".join(b.text for b in extract_prose(page, h, []))
    none = extract_prose(page, h, [(h.clip.x0, h.clip.y0, h.clip.x1, h.clip.y1)])
    assert full and none == []

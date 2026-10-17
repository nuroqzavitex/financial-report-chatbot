import pymupdf as fitz
import pytest
from conftest import half
from ircb.ingestion.layout import (
    Span,
    footnote_refs,
    is_furniture,
    median_size,
    spans_in,
    statement_code,
)

pytestmark = pytest.mark.requires_pdf


def test_superscript_removed(doc: fitz.Document) -> None:
    # Printed p.4 has no superscripts in this PDF; p.14 has "Dư nợ tín dụng¹", "khách hàng²".
    page, clip = half(doc, printed=14)
    text = " ".join(s.text for s in spans_in(page, clip)).replace(" ", "")
    assert "tíndụng" in text
    assert "tín dụng1" not in " ".join(s.text for s in spans_in(page, clip))
    assert "tíndụng1" not in text
    assert "kháchhàng2" not in text
    refs = footnote_refs(page, clip)
    assert refs and all(r.superscript for r in refs)
    assert {r.text.strip() for r in refs} >= {"1", "2"}
    assert not any(s.superscript for s in spans_in(page, clip))


def test_page4_has_no_glued_superscript(doc: fitz.Document) -> None:
    text = " ".join(s.text for s in spans_in(*half(doc, printed=4)))
    assert "tín dụng1" not in text.replace(" ", "")


def test_header_is_furniture(doc: fitz.Document) -> None:
    page, clip = half(doc, printed=297)
    assert not any(
        "Báo cáo thường niên 2025" in s.text for s in spans_in(page, clip) if not is_furniture(s, page.rect)
    )
    # left half of p.296 carries the running header in the furniture band
    page, clip = half(doc, printed=4)
    raw = page.get_text("dict", clip=clip)
    assert any(
        "Báo cáo thường niên 2025" in sp["text"]
        for b in raw["blocks"]
        for ln in b.get("lines", [])
        for sp in ln["spans"]
    )
    assert not any("Báo cáo thường niên 2025" in s.text for s in spans_in(page, clip))


def test_furniture_patterns(doc: fitz.Document) -> None:
    page, _ = half(doc, printed=297)
    r = page.rect

    def mk(text: str, y: float = 300.0) -> Span:
        return Span(text, (10.0, y, 50.0, y + 8), 8.5, False, False, 0)

    assert is_furniture(mk("anything", 20.0), r)
    assert is_furniture(mk("Báo cáo thường niên 2025"), r)
    assert is_furniture(mk("B02/TCTD-HN"), r)
    assert is_furniture(mk("tại ngày 31 tháng 12 năm 2025"), r)
    assert not is_furniture(mk("Tổng tài sản"), r)


def test_statement_code(doc: fitz.Document) -> None:
    assert statement_code(*half(doc, printed=297)) == "B02/TCTD-HN"
    assert statement_code(*half(doc, printed=4)) is None


def test_span_fields_and_median(doc: fitz.Document) -> None:
    spans = spans_in(*half(doc, printed=4))
    assert spans and all(isinstance(s.color, int) for s in spans)
    assert any(s.bold for s in spans)
    assert any(not s.bold for s in spans)
    assert median_size(spans) == pytest.approx(8.5)
    assert median_size([]) == 0.0


def test_long_flag1_spans_are_not_superscripts(doc: fitz.Document) -> None:
    page, clip = half(doc, printed=238)
    texts = " ".join(s.text for s in spans_in(page, clip))
    assert "thẻ xanh đầu tiên" in texts or "Eco card" in texts
    refs = footnote_refs(page, clip)
    assert all(1 <= len(r.text.strip()) <= 3 for r in refs)
    assert not any("Eco" in r.text or "xanh" in r.text for r in refs)

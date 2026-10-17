import pymupdf as fitz
import pytest
from ircb.ingestion import spread
from ircb.ingestion.spread import (
    PageMapError,
    build_page_map,
    split_halves,
    verify_page_map,
)

pytestmark = pytest.mark.requires_pdf


def test_rule_holds_everywhere(doc: fitz.Document) -> None:
    assert verify_page_map(doc) == []


def test_counts(doc: fitz.Document) -> None:
    halves = split_halves(doc)
    assert len(halves) == 1 + 196 * 2
    assert halves[0].printed_page == 1 and halves[0].half == "S"
    assert not halves[0].is_divider
    assert halves[1].half == "L" and halves[1].printed_page == 2
    assert halves[2].half == "R" and halves[2].printed_page == 3
    w, h = doc[1].rect.width, doc[1].rect.height
    assert halves[1].clip == fitz.Rect(0, 0, w / 2, h)
    assert halves[2].clip == fitz.Rect(w / 2, 0, w, h)


def test_dividers(doc: fitz.Document) -> None:
    div = {h.printed_page for h in split_halves(doc) if h.is_divider}
    assert {8, 24, 44, 100, 144, 290} <= div


def test_chapter_from_right_header(doc: fitz.Document) -> None:
    h = next(h for h in split_halves(doc) if h.printed_page == 297)
    assert h.chapter and "tài chính" in h.chapter.lower()
    left = next(h for h in split_halves(doc) if h.printed_page == 296)
    assert left.chapter == h.chapter


def test_build_page_map(doc: fitz.Document) -> None:
    infos = build_page_map(doc)
    assert len(infos) == 393 and infos[0].half == "S"
    assert [i.printed_page for i in infos] == list(range(1, 394))


def test_mismatch_raises(monkeypatch: pytest.MonkeyPatch, doc: fitz.Document) -> None:
    monkeypatch.setattr(spread, "_read_header_numbers", lambda page: (99, 100))
    with pytest.raises(PageMapError):
        build_page_map(doc)

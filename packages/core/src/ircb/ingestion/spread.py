"""Spread splitter and verified page map (spec §5.1).

PDF page 1 is the cover (printed page 1); every later PDF page ``p`` is an A3
spread holding printed pages ``2p-2`` (left) and ``2p-1`` (right).
"""

import re
from dataclasses import dataclass
from typing import Literal

import pymupdf as fitz

from ircb.domain.models import PageInfo

HEADER_BAND = 45  # pt: region at the top edge holding the printed page number
CORNER = 100  # pt: the number sits within 100pt of the left/right edge


class PageMapError(Exception):
    """The printed page numbers do not follow the 2p-2 / 2p-1 rule."""


@dataclass(frozen=True)
class HalfPage:
    pdf_page: int
    half: Literal["L", "R", "S"]
    printed_page: int
    clip: fitz.Rect
    chapter: str | None
    is_divider: bool


@dataclass(frozen=True)
class PageMismatch:
    pdf_page: int
    found: tuple[int | None, int | None]
    expected: tuple[int | None, int | None]


def _read_header_numbers(page: fitz.Page) -> tuple[int | None, int | None]:
    width = page.rect.width
    left = right = None
    for x0, y0, _x1, _y1, w, *_ in _words(page):
        if y0 < HEADER_BAND and re.fullmatch(r"\d{1,3}", w):
            if x0 < CORNER:
                left = int(w)
            elif x0 > width - CORNER:
                right = int(w)
    return left, right


def _rect(x0: float, y0: float, x1: float, y1: float) -> fitz.Rect:
    return fitz.Rect(x0, y0, x1, y1)  # type: ignore[no-untyped-call]


def _words(page: fitz.Page) -> list[tuple[float, float, float, float, str, int, int, int]]:
    words: list[tuple[float, float, float, float, str, int, int, int]] = page.get_text(  # type: ignore[no-untyped-call]
        "words"
    )
    return words


def _is_spread(page: fitz.Page) -> bool:
    return bool(page.rect.width > page.rect.height)


def _chapter(page: fitz.Page) -> str | None:
    """Right-hand header text (page number and ``|`` removed), or None."""
    half_w = page.rect.width / 2
    words = [
        w
        for w in _words(page)
        if w[1] < HEADER_BAND and w[0] >= half_w and w[4] != "|" and not re.fullmatch(r"\d{1,3}", w[4])
    ]
    words.sort(key=lambda w: (round(w[1]), w[0]))
    text = " ".join(w[4] for w in words).strip()
    return text or None


def split_halves(doc: fitz.Document) -> list[HalfPage]:
    out: list[HalfPage] = []
    for i in range(doc.page_count):
        page = doc[i]
        pn = i + 1
        w, h = page.rect.width, page.rect.height
        if not _is_spread(page):
            out.append(HalfPage(pn, "S", pn, _rect(0, 0, w, h), None, False))
            continue
        left, right = _read_header_numbers(page)
        chapter = _chapter(page)
        out.append(HalfPage(pn, "L", 2 * pn - 2, _rect(0, 0, w / 2, h), chapter, left is None))
        out.append(HalfPage(pn, "R", 2 * pn - 1, _rect(w / 2, 0, w, h), chapter, right is None))
    return out


def verify_page_map(doc: fitz.Document) -> list[PageMismatch]:
    """Header numbers that disagree with the rule; a missing number is a divider."""
    bad: list[PageMismatch] = []
    for i in range(doc.page_count):
        page = doc[i]
        pn = i + 1
        found = _read_header_numbers(page)
        if not _is_spread(page):
            expected: tuple[int | None, int | None] = (None, None)
            ok = found == expected
        else:
            expected = (2 * pn - 2, 2 * pn - 1)
            ok = all(f is None or f == e for f, e in zip(found, expected, strict=True))
        if not ok:
            bad.append(PageMismatch(pn, found, expected))
    return bad


def build_page_map(doc: fitz.Document) -> list[PageInfo]:
    mismatches = verify_page_map(doc)
    if mismatches:
        first = mismatches[0]
        raise PageMapError(
            f"{len(mismatches)} page(s) break the 2p-2/2p-1 rule; first: PDF p.{first.pdf_page} "
            f"found {first.found}, expected {first.expected}"
        )
    return [
        PageInfo(
            pdf_page=h.pdf_page,
            half=h.half,
            printed_page=h.printed_page,
            chapter=h.chapter,
            is_divider=h.is_divider,
        )
        for h in split_halves(doc)
    ]

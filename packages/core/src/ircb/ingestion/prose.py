"""Running prose with the nearest heading (spec §5.2): blocks of content spans in stream order."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf as fitz

from ircb.ingestion.layout import Span, median_size, spans_in
from ircb.ingestion.spread import HalfPage

BBox = tuple[float, float, float, float]

HEADING_SIZE_FACTOR = 1.15  # a heading is noticeably larger than body text ...
HEADING_MAX_CHARS = 80  # ... or a short bold line
_NUMERIC_RE = re.compile(r"[~#]?[\d.,\s]+%?|TOP\s*\d+", re.IGNORECASE)  # KPI big-number shape


@dataclass(frozen=True)
class ProseBlock:
    heading: str | None
    text: str
    bbox: BBox
    printed_page: int


def _centre_inside(s: Span, box: BBox) -> bool:
    cx = (s.bbox[0] + s.bbox[2]) / 2
    cy = (s.bbox[1] + s.bbox[3]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _cy(s: Span) -> float:
    return (s.bbox[1] + s.bbox[3]) / 2


def _is_heading(s: Span, med: float, spans: list[Span]) -> bool:
    text = s.text.strip()
    if _NUMERIC_RE.fullmatch(text):
        return False  # big KPI numbers are values, not headings
    if s.size >= HEADING_SIZE_FACTOR * med:
        return True
    if not (s.bold and len(text) <= HEADING_MAX_CHARS and not text.endswith((",", ";"))):
        return False
    # a bold line of its own, not an inline emphasis inside a sentence
    return all(o is s or o.bold or abs(_cy(o) - _cy(s)) >= 3 for o in spans)


def _union(spans: list[Span]) -> BBox:
    return (
        min(s.bbox[0] for s in spans),
        min(s.bbox[1] for s in spans),
        max(s.bbox[2] for s in spans),
        max(s.bbox[3] for s in spans),
    )


def extract_prose(page: fitz.Page, half: HalfPage, exclude_bboxes: list[BBox]) -> list[ProseBlock]:
    spans = [
        s
        for s in spans_in(page, half.clip)
        if s.text.strip() and not any(_centre_inside(s, b) for b in exclude_bboxes)
    ]
    if not spans:
        return []
    med = median_size(spans)
    blocks: list[ProseBlock] = []
    heading_parts: list[str] = []
    heading: str | None = None
    body: list[Span] = []
    last_was_heading = False
    trailing: list[Span] = []

    def flush() -> None:
        if body:
            text = " ".join(" ".join(s.text for s in body).split())
            if text:
                blocks.append(ProseBlock(heading, text, _union(body), half.printed_page))
            body.clear()

    for s in spans:
        if _is_heading(s, med, spans):
            if not last_was_heading:
                flush()
                heading_parts = []
                trailing = []
            heading_parts.append(s.text.strip())
            trailing.append(s)
            heading = " ".join(" ".join(heading_parts).split())
            last_was_heading = True
        else:
            body.append(s)
            last_was_heading = False
    flush()
    if heading_parts and last_was_heading:
        # trailing heading with no body: keep it (as its own text) instead of losing it
        blocks.append(ProseBlock(heading, heading or "", _union(trailing), half.printed_page))
    return blocks

"""Running prose with the nearest heading (spec §5.2): blocks of content spans in stream order."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf as fitz

from ircb.ingestion.kpi import is_figure
from ircb.ingestion.layout import Span, median_size, spans_in
from ircb.ingestion.spread import HalfPage

BBox = tuple[float, float, float, float]

HEADING_SIZE_FACTOR = 1.15  # a heading is noticeably larger than body text ...
HEADING_MAX_CHARS = 80  # ... or a short bold line
HEADING_RUN_MAX_CHARS = 120  # a longer run of large type is a pull quote, not a heading
_NUMERIC_RE = re.compile(r"[~#]?[\d.,\s]+%?|TOP\s*\d+", re.IGNORECASE)  # KPI big-number shape
STAT_MAX_CHARS = 30
CAPTION_GAP = 8.0  # pt between a figure and the first line of its caption
CAPTION_LINE_GAP = 3.0  # pt between the lines of one caption
CAPTION_MAX_LINES = 3  # more contiguous lines than this is a paragraph, not a caption
UNIT_GAP = 15.0  # pt between a figure and a unit word set beside it ("13,1 Triệu")


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


def _is_stat(s: Span, med: float) -> bool:
    text = s.text.strip()
    return s.size >= HEADING_SIZE_FACTOR * med and len(text) <= STAT_MAX_CHARS and is_figure(text)


def _is_heading(s: Span, med: float, spans: list[Span]) -> bool:
    text = s.text.strip()
    if _NUMERIC_RE.fullmatch(text) or _is_stat(s, med):
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


def _same_column(a: Span, b: Span) -> bool:
    return min(a.bbox[2], b.bbox[2]) > max(a.bbox[0], b.bbox[0])


def _caption(stat: Span, cands: list[Span], above: bool) -> tuple[float, list[Span]] | None:
    """(gap, lines) of the caption stacked directly above or below ``stat`` in its column."""
    lines: list[Span] = []
    edge, max_gap = (stat.bbox[1] if above else stat.bbox[3]), CAPTION_GAP
    first_gap = 0.0
    while True:
        best: tuple[float, Span] | None = None
        for c in cands:
            if any(c is ln for ln in lines) or not _same_column(stat, c):
                continue
            gap = edge - c.bbox[3] if above else c.bbox[1] - edge
            if -2.0 <= gap <= max_gap and (best is None or gap < best[0]):
                best = (gap, c)
        if best is None:
            break
        if not lines:
            first_gap = best[0]
        lines.append(best[1])
        if len(lines) > CAPTION_MAX_LINES:
            return None
        edge, max_gap = (best[1].bbox[1] if above else best[1].bbox[3]), CAPTION_LINE_GAP
    if not lines:
        return None
    return first_gap, (lines[::-1] if above else lines)


def _pair_stats(spans: list[Span], med: float) -> list[Span]:
    """Join each large infographic figure with its small caption into one body line "caption: figure".

    Otherwise the figure reads as a heading and its caption lands in another block, so
    "Số dư tiền gửi" and "24% N/N" never meet in one chunk.
    """
    stats = [s for s in spans if _is_stat(s, med)]
    if not stats:
        return spans
    cands = [
        s
        for s in spans
        if s.size < HEADING_SIZE_FACTOR * med
        and len(s.text.strip()) <= HEADING_MAX_CHARS
        and not _is_heading(s, med, spans)
    ]
    order = {id(s): i for i, s in enumerate(spans)}
    used: set[int] = set()
    merged: dict[int, Span] = {}  # id of the member first in stream order -> merged span
    for stat in stats:
        free = [c for c in cands if id(c) not in used]
        sides = [c for c in (_caption(stat, free, True), _caption(stat, free, False)) if c]
        if not sides:
            continue
        caption = min(sides, key=lambda c: c[0])[1]
        units = [
            c
            for c in free
            if all(c is not ln for ln in caption)
            and stat.bbox[1] <= _cy(c) <= stat.bbox[3]
            and 0 <= c.bbox[0] - stat.bbox[2] <= UNIT_GAP
            and len(c.text.strip()) <= 10
        ]
        members = [stat, *caption, *units]
        label = " ".join(" ".join(c.text for c in caption).split())
        value = " ".join(" ".join(s.text for s in [stat, *units]).split())
        first = min(members, key=lambda m: order[id(m)])
        merged[id(first)] = Span(f"{label}: {value}", _union(members), med, False, False, stat.color)
        used.update(id(m) for m in members)
    return [merged.get(id(s), s) for s in spans if id(s) in merged or id(s) not in used]


def _heading_flags(spans: list[Span], med: float) -> list[bool]:
    flags = [_is_heading(s, med, spans) for s in spans]
    i = 0
    while i < len(spans):
        if not flags[i]:
            i += 1
            continue
        style = (round(spans[i].size, 1), spans[i].bold)
        j = i
        while j < len(spans) and flags[j] and (round(spans[j].size, 1), spans[j].bold) == style:
            j += 1
        text = " ".join(" ".join(s.text for s in spans[i:j]).split())
        if len(text) > HEADING_RUN_MAX_CHARS or (len(text) > HEADING_MAX_CHARS and text.endswith(".")):
            flags[i:j] = [False] * (j - i)  # a sentence set in large type is body text
        i = j
    return flags


def extract_prose(page: fitz.Page, half: HalfPage, exclude_bboxes: list[BBox]) -> list[ProseBlock]:
    spans = [
        s
        for s in spans_in(page, half.clip)
        if s.text.strip() and not any(_centre_inside(s, b) for b in exclude_bboxes)
    ]
    if not spans:
        return []
    med = median_size(spans)
    spans = _pair_stats(spans, med)
    flags = _heading_flags(spans, med)
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

    for s, is_heading in zip(spans, flags, strict=True):
        if is_heading:
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

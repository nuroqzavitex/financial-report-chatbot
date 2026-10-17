"""Span-level layout extraction (spec §5.2): superscripts and page furniture."""

import re
from dataclasses import dataclass
from statistics import median
from typing import Any

import pymupdf as fitz

from ircb.domain.numbers_vn import normalize_chars
from ircb.ingestion.spread import HEADER_BAND

_FLAG_SUPERSCRIPT = 1
_FLAG_BOLD = 16
_SUPERSCRIPT_RE = re.compile(r"[\d*†‡§#]{1,3}")
_CODE_RE = re.compile(r"B\d{2}[a-z]?/TCTD(?:-HN)?")
_RUNNING_HEADER = "báo cáo thường niên 2025"
_AS_AT_RE = re.compile(r"tại ngày 31 tháng 12 năm 2025", re.IGNORECASE)


@dataclass(frozen=True)
class Span:
    text: str
    bbox: tuple[float, float, float, float]
    size: float
    bold: bool
    superscript: bool
    color: int


def _raw_spans(page: fitz.Page, clip: fitz.Rect) -> list[Span]:
    data: dict[str, Any] = page.get_text("dict", clip=clip)  # type: ignore[no-untyped-call]
    out: list[Span] = []
    for block in data["blocks"]:
        for line in block.get("lines", []):
            for sp in line["spans"]:
                flags = int(sp["flags"])
                text = normalize_chars(sp["text"])
                x0, y0, x1, y1 = sp["bbox"]
                out.append(
                    Span(
                        text=text,
                        bbox=(float(x0), float(y0), float(x1), float(y1)),
                        size=float(sp["size"]),
                        bold=bool(flags & _FLAG_BOLD) or "bold" in str(sp["font"]).lower(),
                        # the flag alone is not enough: long/alphabetic text can carry it too
                        superscript=bool(flags & _FLAG_SUPERSCRIPT)
                        and _SUPERSCRIPT_RE.fullmatch(text.strip()) is not None,
                        color=int(sp["color"]),
                    )
                )
    return out


def is_furniture(span: Span, page_rect: fitz.Rect) -> bool:  # noqa: ARG001
    """Running header band, report title, statement code, or the as-at date line."""
    text = span.text.strip()
    if span.bbox[1] < HEADER_BAND:
        return True
    return bool(_RUNNING_HEADER in text.lower() or _CODE_RE.fullmatch(text) or _AS_AT_RE.fullmatch(text))


def spans_in(page: fitz.Page, clip: fitz.Rect) -> list[Span]:
    """Content spans in stream order: superscripts and furniture dropped."""
    rect = page.rect
    return [s for s in _raw_spans(page, clip) if not s.superscript and not is_furniture(s, rect)]


def footnote_refs(page: fitz.Page, clip: fitz.Rect) -> list[Span]:
    return [s for s in _raw_spans(page, clip) if s.superscript]


def statement_code(page: fitz.Page, clip: fitz.Rect) -> str | None:
    for s in _raw_spans(page, clip):
        m = _CODE_RE.search(s.text)
        if m:
            return m.group(0)
    return None


def median_size(spans: list[Span]) -> float:
    return float(median(s.size for s in spans)) if spans else 0.0

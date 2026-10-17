"""Coordinate-based KPI tile parser with vector arrow direction (spec §5.4).

A tile is *label* → *big number* → *unit* → *description/comparison*; stream order
scrambles these (finding #19), so tiles are rebuilt from span geometry. The ▲/▼
glyph is a vector triangle (findings #10, #20), read from ``page.get_drawings()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import pymupdf as fitz

from ircb.domain.units import normalize_unit
from ircb.ingestion.layout import Span, median_size, spans_in
from ircb.ingestion.spread import HalfPage

Direction = Literal["up", "down", "unknown"]
BBox = tuple[float, float, float, float]

BIG_FACTOR = 2.2  # big number: size >= 2.2 x half-page median
HEADING_FACTOR = 1.4  # region heading: size >= 1.4 x median, not a number
COL_CENTER = 70.0  # span centre within +-70pt of the number's centre ...
COL_EXTENT = 110.0  # ... and fully inside +-110pt (keeps full-width prose out)
LABEL_MAX_GAP = 20.0  # first label line sits right above the number
LABEL_SPAN = 60.0  # whole label within 60pt above the number
LINE_GAP = 4.0  # lines of one label/description block touch (leading ~ -1.5pt)
UNIT_RIGHT = 30.0  # unit to the right starts within 30pt of the number
UNIT_BELOW = 8.0  # unit below starts within 8pt of the number
DESC_GAP = 35.0  # a larger vertical gap ends the description
RULE_MIN_W = 30.0  # horizontal tile separators are >= 30pt wide
ARROW_MAX = 12.0  # arrow glyph < 12pt
ARROW_DX = 15.0  # within 15pt left of the % span
ARROW_DY = 6.0  # centre-y offset < 6pt

# A big span is a KPI value only if it *is* a number (or "TOP n"): section headings such
# as "Điểm nhấn 2025" are big and contain digits but also letters, so they are rejected.
_VALUE_RE = re.compile(r"(?P<num>[~#]?\d[\d.,]*)\s*(?P<pct>%)?|TOP\s*\d+", re.IGNORECASE)
_CHANGE_RE = re.compile(
    r"(?:(?P<verb>Tăng|Giảm)\s+)?(?P<pct>[~]?\d[\d.,]*\s*%)\s*"
    r"(?P<basis>N/N|so với năm trước|so với năm \d{4})",
    re.IGNORECASE,
)
_CAGR_RE = re.compile(
    r"Tăng trưởng kép\s*(?P<y0>\d{4})\s*[–-]\s*(?P<y1>\d{4})\s*:\s*(?P<pct>\d[\d.,]*\s*%)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class KpiTile:
    label: str
    value_raw: str
    unit: str | None
    description: str
    change_raw: str | None
    change_basis: str | None
    direction: Direction
    bbox: BBox
    printed_page: int
    context: str


@dataclass(frozen=True)
class _Line:
    spans: tuple[Span, ...]

    @property
    def text(self) -> str:
        return " ".join(" ".join(s.text for s in self.spans).split())

    @property
    def bbox(self) -> BBox:
        return _union([s.bbox for s in self.spans])

    @property
    def top(self) -> float:
        return self.bbox[1]

    @property
    def bottom(self) -> float:
        return self.bbox[3]


def is_kpi_value(text: str) -> bool:
    """True for a big-number text ("1.192", "40,4%", "TOP 1"); False for headings."""
    return _VALUE_RE.fullmatch(text.strip()) is not None


def _union(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _cx(b: BBox) -> float:
    return (b[0] + b[2]) / 2


def _cy(b: BBox) -> float:
    return (b[1] + b[3]) / 2


def _lines(spans: list[Span]) -> list[_Line]:
    """Group spans into visual lines (centre-y within 3pt), each sorted left to right."""
    groups: list[list[Span]] = []
    for s in sorted(spans, key=lambda s: _cy(s.bbox)):
        if groups and abs(_cy(s.bbox) - _cy(groups[-1][-1].bbox)) < 3:
            groups[-1].append(s)
        else:
            groups.append([s])
    return [_Line(tuple(sorted(g, key=lambda s: s.bbox[0]))) for g in groups]


def _drawings(page: fitz.Page) -> list[dict[str, Any]]:
    drawings: list[dict[str, Any]] = page.get_drawings()
    return drawings


def _rules(drawings: list[dict[str, Any]]) -> list[BBox]:
    """Horizontal separator lines (tile borders)."""
    out: list[BBox] = []
    for d in drawings:
        r = d["rect"]
        if r.height < 1.5 and r.width >= RULE_MIN_W and any(it[0] == "l" for it in d["items"]):
            out.append((float(r.x0), float(r.y0), float(r.x1), float(r.y1)))
    return out


def _is_red(rgb: Any) -> bool:
    if not rgb or len(rgb) < 3:
        return False
    r, g, b = (float(v) for v in rgb[:3])
    return r > 0.6 and g < 0.3 and b < 0.3


def _arrow_candidate(drawings: list[dict[str, Any]], pct_bbox: BBox) -> Direction | None:
    """Decision of the first triangle just left of the % span; None when there is none."""
    for d in drawings:
        r = d["rect"]
        if not (r.width < ARROW_MAX and r.height < ARROW_MAX):
            continue
        dx = pct_bbox[0] - float(r.x1)
        if not (-1.0 <= dx < ARROW_DX) or abs(_cy((r.x0, r.y0, r.x1, r.y1)) - _cy(pct_bbox)) >= ARROW_DY:
            continue
        pts = {
            (round(float(p.x), 1), round(float(p.y), 1)) for it in d["items"] if it[0] == "l" for p in it[1:3]
        }
        if len(pts) != 3:
            continue
        ys = sorted(y for _, y in pts)
        geom: Direction = "unknown"
        if ys[1] - ys[0] > 0.5 and ys[2] - ys[1] < 0.5:
            geom = "up"  # one apex at the smallest y
        elif ys[2] - ys[1] > 0.5 and ys[1] - ys[0] < 0.5:
            geom = "down"
        red = _is_red(d.get("fill")) or _is_red(d.get("color"))
        if red and geom == "up":
            return "unknown"  # geometry and colour disagree: do not guess
        return geom  # colour alone never decides when geometry is unknown
    return None


def _arrow_from(drawings: list[dict[str, Any]], pct_bbox: BBox) -> Direction:
    return _arrow_candidate(drawings, pct_bbox) or "unknown"


def _decide_direction(drawings: list[dict[str, Any]], pct_bbox: BBox, verb: str | None) -> Direction:
    """Shape/colour decision; the printed Tăng/Giảm word applies only when no arrow exists."""
    cand = _arrow_candidate(drawings, pct_bbox)
    if cand is not None:
        return cand
    if verb:
        return "up" if verb.lower() == "tăng" else "down"  # printed word, not inferred
    return "unknown"


def arrow_direction(page: fitz.Page, pct_bbox: tuple[float, float, float, float]) -> Direction:
    """Direction of the vector ▲/▼ just left of a change-% span, or "unknown"."""
    return _arrow_from(_drawings(page), pct_bbox)


def _in_column(s: Span, cx: float) -> bool:
    return (
        abs(_cx(s.bbox) - cx) <= COL_CENTER and s.bbox[0] >= cx - COL_EXTENT and s.bbox[2] <= cx + COL_EXTENT
    )


def _rule_between(rules: list[BBox], cx: float, y_top: float, y_bottom: float) -> bool:
    return any(y_top < r[1] < y_bottom and r[0] < cx + COL_CENTER and r[2] > cx - COL_CENTER for r in rules)


def _heading_text(spans: list[Span], size: float) -> str:
    """Join the first vertically contiguous block of spans of the given size."""
    same = sorted((s for s in spans if abs(s.size - size) < 0.1), key=lambda s: (s.bbox[1], s.bbox[0]))
    block: list[Span] = []
    for s in same:
        if block and s.bbox[1] - block[-1].bbox[3] > size:
            break
        block.append(s)
    return " ".join(" ".join(s.text for s in block).split())


def _region_heading(heads: list[Span], top: float) -> str:
    """Nearest heading above ``top`` (multi-line headings joined)."""
    above = [h for h in heads if h.bbox[3] <= top + 1 and h.text.strip()]
    if not above:
        return ""
    nearest = max(above, key=lambda h: h.bbox[3])
    block = [nearest]
    for h in sorted((h for h in above if abs(h.size - nearest.size) < 0.1), key=lambda h: -h.bbox[3]):
        if h is nearest or h in block:
            continue
        if min(b.bbox[1] for b in block) - h.bbox[3] <= nearest.size * 0.5:
            block.append(h)
    block.sort(key=lambda h: (h.bbox[1], h.bbox[0]))
    return " ".join(" ".join(h.text for h in block).split())


@dataclass
class _Draft:
    big: Span
    label: list[_Line]
    unit_spans: list[Span]
    unit_line: _Line | None


def parse_kpi_tiles(page: fitz.Page, half: HalfPage) -> list[KpiTile]:
    spans = spans_in(page, half.clip)
    if not spans:
        return []
    med = median_size(spans)
    bigs = [s for s in spans if s.size >= BIG_FACTOR * med and is_kpi_value(s.text)]
    if not bigs:
        return []
    drawings = _drawings(page)
    rules = _rules(drawings)
    small = [s for s in spans if s not in bigs and s.text.strip()]

    # Spread-level section title (e.g. "Khối Ngân hàng Bán lẻ (RBG)" on the facing half).
    headings_all = [
        s
        for s in spans_in(page, page.rect)
        if s.size >= HEADING_FACTOR * med and not is_kpi_value(s.text) and s.text.strip()
    ]
    section = _heading_text(headings_all, max(s.size for s in headings_all)) if headings_all else ""
    region_heads = [s for s in spans if s.size >= HEADING_FACTOR * med and not is_kpi_value(s.text)]

    drafts: list[_Draft] = []
    consumed: set[int] = set()
    for big in bigs:
        cx = _cx(big.bbox)
        col = [s for s in small if _in_column(s, cx) and s.size < HEADING_FACTOR * med]
        lines = _lines(col)

        # Label: nearest line(s) directly above, stopping at a gap or a rule.
        above = sorted((ln for ln in lines if _cy(ln.bbox) < big.bbox[1] + 2), key=lambda ln: -ln.bottom)
        label: list[_Line] = []
        for ln in above:
            ref_top = label[-1].top if label else big.bbox[1]
            gap = ref_top - ln.bottom
            if (not label and gap > LABEL_MAX_GAP) or (label and gap > LINE_GAP):
                break
            if big.bbox[1] - ln.top > LABEL_SPAN or _rule_between(rules, cx, ln.bottom, ref_top):
                break
            label.append(ln)
        label.reverse()

        # Unit: to the right on the number's band (p.59), else the line just below (p.5).
        unit_spans = sorted(
            (
                s
                for s in small
                if big.bbox[2] - 2 <= s.bbox[0] <= big.bbox[2] + UNIT_RIGHT
                and big.bbox[1] <= _cy(s.bbox) <= big.bbox[3]
            ),
            key=lambda s: s.bbox[1],
        )
        unit_line: _Line | None = None
        m = _VALUE_RE.fullmatch(big.text.strip())
        is_pct = bool(m and m.group("pct"))
        if not unit_spans and not is_pct and m and m.group("num"):
            below = sorted((ln for ln in lines if ln.top >= big.bbox[3] - 2), key=lambda ln: ln.top)
            if below and below[0].top - big.bbox[3] <= UNIT_BELOW and not re.search(r"\d", below[0].text):
                unit_line = below[0]
        drafts.append(_Draft(big, label, unit_spans, unit_line))
        for ln in label:
            consumed.update(id(s) for s in ln.spans)
        consumed.update(id(s) for s in unit_spans)
        if unit_line:
            consumed.update(id(s) for s in unit_line.spans)

    tiles: list[KpiTile] = []
    for dr in drafts:
        big = dr.big
        cx = _cx(big.bbox)
        col = [
            s for s in small if _in_column(s, cx) and id(s) not in consumed and s.size < HEADING_FACTOR * med
        ]
        start = dr.unit_line.bottom if dr.unit_line else big.bbox[3]
        if dr.unit_spans:
            start = max(start, max(s.bbox[3] for s in dr.unit_spans))
        # Stops: a big vertical gap, a rule, another tile's number, or another tile's label/unit.
        stops = [b.bbox[1] for b in bigs if b is not big and abs(_cx(b.bbox) - cx) <= COL_EXTENT]
        stops += [s.bbox[1] for s in small if id(s) in consumed and _in_column(s, cx)]
        desc: list[_Line] = []
        prev = start
        for ln in sorted((ln for ln in _lines(col) if ln.top >= big.bbox[3] - 2), key=lambda ln: ln.top):
            if ln.top - prev > DESC_GAP or _rule_between(rules, cx, prev, ln.top + 1):
                break
            if any(prev <= y <= ln.top + 1 for y in stops):
                break
            desc.append(ln)
            prev = ln.bottom

        desc_text = " ".join(ln.text for ln in desc)
        change_raw, basis, verb, pct = _change(desc_text)
        direction: Direction = "unknown"
        if pct:
            token = pct.replace(" ", "")
            pct_span = next((s for ln in desc for s in ln.spans if token in s.text.replace(" ", "")), None)
            if pct_span is not None:
                direction = _decide_direction(drawings, pct_span.bbox, verb)
            elif verb:
                direction = "up" if verb.lower() == "tăng" else "down"
        description = desc_text.replace(change_raw, " ") if change_raw else desc_text
        description = " ".join(description.split())

        m = _VALUE_RE.fullmatch(big.text.strip())
        assert m is not None
        if m.group("num"):
            value_raw = m.group("num")
            unit: str | None = "%" if m.group("pct") else None
        else:
            value_raw = " ".join(big.text.split()).upper()
            unit = None
        unit_raw = " ".join(s.text for s in dr.unit_spans) if dr.unit_spans else None
        if unit_raw is None and dr.unit_line is not None:
            unit_raw = dr.unit_line.text
        if unit is None and unit_raw:
            unit_raw = " ".join(unit_raw.split())
            unit = normalize_unit(unit_raw) or unit_raw.lower()

        label_text = " ".join(ln.text for ln in dr.label)
        label_top = dr.label[0].top if dr.label else big.bbox[1]
        region = _region_heading(region_heads, label_top)
        parts: list[str] = []
        for p in (half.chapter, section, region):
            if p and p not in parts:
                parts.append(p)

        boxes = [big.bbox] + [ln.bbox for ln in dr.label] + [s.bbox for s in dr.unit_spans]
        boxes += [dr.unit_line.bbox] if dr.unit_line else []
        boxes += [ln.bbox for ln in desc]
        tiles.append(
            KpiTile(
                label=label_text,
                value_raw=value_raw,
                unit=unit,
                description=description,
                change_raw=change_raw,
                change_basis=basis,
                direction=direction,
                bbox=_union(boxes),
                printed_page=half.printed_page,
                context=" · ".join(parts),
            )
        )
    tiles.sort(key=lambda t: (round(t.bbox[1] / 20), t.bbox[0]))
    return tiles


def _change(text: str) -> tuple[str | None, str | None, str | None, str | None]:
    """(change_raw, change_basis, verb, pct) from a tile's description text."""
    m = _CHANGE_RE.search(text)
    if m:
        basis = m.group("basis")
        canon = "N/N" if basis.upper() == "N/N" else "so với năm trước"
        return m.group(0).strip(), canon, m.group("verb"), m.group("pct")
    c = _CAGR_RE.search(text)
    if c:
        return c.group(0).strip(), f"CAGR {c.group('y0')}–{c.group('y1')}", None, c.group("pct")
    return None, None, None, None

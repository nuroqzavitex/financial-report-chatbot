"""Table coverage QA and coordinate fallback (spec §5.3 step 5).

Coverage = number tokens on a half page that also appear in its tables / all number tokens on the half
(same token regex and multiset matching as ``scripts/profile_pdf.py``, so figures compare with the M0
baseline). A half below 0.95, or with a table column that is empty in every row, is rebuilt from word
coordinates: words clustered into lines by y (3pt), value columns anchored on the x ranges of the
numbers, header text placed over those anchors (or names borrowed from ``header_hint`` for a headerless
continuation table), and every text line kept as its own row so a number binds to the *last* line of a
multi-line label. The better of the two results is kept per half.
"""

import collections
import re
from dataclasses import dataclass
from typing import Any

import pymupdf as fitz

from ircb.domain.numbers_vn import normalize_chars
from ircb.domain.units import UNIT_SCALE, normalize_unit
from ircb.ingestion.layout import Span, is_furniture, statement_code
from ircb.ingestion.spread import HEADER_BAND, _rect
from ircb.ingestion.tables import (
    BBox,
    Cell,
    ExtractedTable,
    TableRow,
    cell_value,
    chapter_default_unit,
    extract_tables,
    hierarchy,
)

MIN_RATIO = 0.95
LINE_TOL = 3.0  # pt: words whose vertical centres differ less than this share a line
SEG_GAP = 6.0  # pt: a horizontal gap wider than this separates two cells of a line
MAX_GAP = 30.0  # pt: vertical gap that ends a table (spacer rows stay inside)
HEADER_JOIN = 3.0  # pt: header lines closer than this are one wrapped header cell
MAX_HEADER_LINES = 6
MAX_LEAD_LINES = 2
SPAN_TOL = 3.0  # pt: runs centred this much worse than the best one still count as centred
WRAP_GAP = 2.0  # pt: a wrapped label line sits this tight under its first line; rows are ~5pt apart
PROSE_FRAC = 0.55  # a single run of words wider than this share of the clip is running text
HEADING_SIZE = 9.5
STATEMENT_BAND = 85.0  # pt: statement title and "tại ngày ..." lines sit above this, never a header
TEXT_COL_MIN = 40.0  # pt: a header cell starting this far right of the table edge anchors a text column
_FLAG_SUPERSCRIPT = 1
_FLAG_BOLD = 16
# token regex of scripts/profile_pdf.py (M0 baseline), kept identical for comparable coverage
NUM = re.compile(r"^\(?-?\d{1,3}(\.\d{3})+(,\d+)?\)?$|^\(?\d+,\d+\)?$")
_YEAR_OR_DATE = re.compile(r"\(?(?:19|20)\d{2}\)?|\d{1,2}/\d{1,2}/(?:19|20)\d{2}")
_NOTE_REF = re.compile(r"\d{1,2}(?:\.\d{1,2}){1,2}")  # "12.1": a note number, never an amount
_UNIT_LINE = re.compile(r"^\s*Đơn vị(?: tính)?\s*:\s*(.+)$", re.IGNORECASE)
_NOTE_HEADER = re.compile(r"thuyết\s*minh|tm", re.IGNORECASE)
_NOTE_NO = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")


@dataclass(frozen=True)
class QAResult:
    pdf_page: int
    half: str
    numbers: int
    covered: int
    ratio: float
    none_columns: int
    used_fallback: bool  # the fallback ran (below threshold or empty column); kept tables carry ``_f``


@dataclass(frozen=True)
class _Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    bold: bool

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class _Line:
    words: list[_Word]
    segs: list[list[_Word]]
    kind: str  # "row" (has a value cell) | "text" | "prose" | "heading"

    @property
    def y0(self) -> float:
        return min(w.y0 for w in self.words)

    @property
    def y1(self) -> float:
        return max(w.y1 for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


# ---------------------------------------------------------------- coverage


def _tokens(page: fitz.Page, clip: fitz.Rect) -> list[str]:
    words = page.get_text("words", clip=clip)  # type: ignore[no-untyped-call]
    return [normalize_chars(str(w[4])) for w in words]


def _in(x: float, y: float, clip: fitz.Rect) -> bool:
    return bool(clip.x0 <= x <= clip.x1 and clip.y0 <= y <= clip.y1)


def coverage(page: fitz.Page, clip: fitz.Rect, tables: list[ExtractedTable]) -> tuple[int, int]:
    """(number tokens in ``clip``, how many of them appear in ``tables``) — multiset matching.

    A table counts only with the parts that lie in ``clip``: its labels/note refs when the table
    starts inside it, each cell by its centre (so a gutter-spanning table splits across halves).
    """
    need = collections.Counter(t for t in _tokens(page, clip) if NUM.match(t))
    have: collections.Counter[str] = collections.Counter()
    for t in tables:
        labels_in = _in(t.bbox[0], t.bbox[1], clip)
        for r in t.rows:
            toks: list[str] = []
            if labels_in:
                toks += r.label.split() + (r.note_ref or "").split()
            for c in r.cells:
                if _in((c.bbox[0] + c.bbox[2]) / 2, (c.bbox[1] + c.bbox[3]) / 2, clip):
                    toks += c.raw.split()
            have.update(normalize_chars(s) for s in toks if NUM.match(normalize_chars(s)))
    return sum(need.values()), sum(min(v, have[k]) for k, v in need.items())


def _none_columns(tables: list[ExtractedTable]) -> int:
    n = 0
    for t in tables:
        width = max((len(r.cells) for r in t.rows), default=0)
        for j in range(width):
            if all(j >= len(r.cells) or not r.cells[j].raw.strip() for r in t.rows):
                n += 1
    return n


# ---------------------------------------------------------------- words and lines


def _words(page: fitz.Page, clip: fitz.Rect) -> list[_Word]:
    """Words of non-superscript, non-furniture spans whose centres lie in ``clip``."""
    data: dict[str, Any] = page.get_text("rawdict", clip=clip)  # type: ignore[no-untyped-call]
    out: list[_Word] = []
    for block in data["blocks"]:
        for line in block.get("lines", []):
            for sp in line["spans"]:
                flags = int(sp["flags"])
                text = normalize_chars("".join(ch["c"] for ch in sp["chars"]))
                bbox = tuple(float(v) for v in sp["bbox"])
                bold = bool(flags & _FLAG_BOLD) or "bold" in str(sp["font"]).lower()
                span = Span(text, bbox, float(sp["size"]), bold, bool(flags & _FLAG_SUPERSCRIPT), 0)  # type: ignore[arg-type]
                if span.superscript or is_furniture(span, page.rect):
                    continue
                cur: list[tuple[str, BBox]] = []
                for ch in sp["chars"]:
                    c = normalize_chars(ch["c"])
                    b: BBox = tuple(float(v) for v in ch["bbox"])  # type: ignore[assignment]
                    if c.isspace() or (cur and b[0] - cur[-1][1][2] > 1.5):
                        _flush(cur, span, clip, out)
                        cur = []
                    if not c.isspace():
                        cur.append((c, b))
                _flush(cur, span, clip, out)
    return out


def _flush(cur: list[tuple[str, BBox]], span: Span, clip: fitz.Rect, out: list[_Word]) -> None:
    if not cur:
        return
    w = _Word(
        "".join(c for c, _ in cur),
        cur[0][1][0],
        min(b[1] for _, b in cur),
        cur[-1][1][2],
        max(b[3] for _, b in cur),
        span.size,
        span.bold,
    )
    if _in(w.cx, w.cy, clip):
        out.append(w)


def _is_value(text: str) -> bool:
    s = text.strip()
    if not s or _YEAR_OR_DATE.fullmatch(s):
        return False
    return bool(_NOTE_REF.fullmatch(s)) or cell_value(s) is not None


def _lines(words: list[_Word], width: float) -> list[_Line]:
    rows: list[list[_Word]] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x0)):
        if rows and abs(w.cy - sum(v.cy for v in rows[-1]) / len(rows[-1])) <= LINE_TOL:
            rows[-1].append(w)
        else:
            rows.append([w])
    out: list[_Line] = []
    for ws in rows:
        ws.sort(key=lambda w: w.x0)
        segs: list[list[_Word]] = [[ws[0]]]
        for w in ws[1:]:
            if w.x0 - segs[-1][-1].x1 > SEG_GAP:
                segs.append([w])
            else:
                segs[-1].append(w)
        values = [_seg_value(s) for s in segs]
        if any(s[-1].x1 - s[0].x0 > PROSE_FRAC * width for s in segs):
            kind = "prose"
        elif any(values[1:]) or all(values):
            kind = "row"
        elif max(w.size for w in ws) >= HEADING_SIZE:
            kind = "heading"
        else:
            kind = "text"
        out.append(_Line(ws, segs, kind))
    return out


# ---------------------------------------------------------------- columns


def _value_segs(line: _Line) -> list[list[_Word]]:
    if line.kind != "row":
        return []
    values = [s for s in line.segs if _seg_value(s)]
    # the first run of words is the label unless the whole line is values (an unlabelled total)
    return values if len(values) == len(line.segs) else [s for s in values if s is not line.segs[0]]


def _seg_value(seg: list[_Word]) -> bool:
    return all(_is_value(w.text) for w in seg)


def _columns(lines: list[_Line]) -> list[tuple[float, float]]:
    """Value columns as merged x ranges of the value cells of ``lines``."""
    spans = sorted((s[0].x0, s[-1].x1) for ln in lines for s in _value_segs(ln))
    cols: list[list[float]] = []
    for x0, x1 in spans:
        if cols and x0 <= cols[-1][1] + 2:
            cols[-1][1] = max(cols[-1][1], x1)
        else:
            cols.append([x0, x1])
    return [(a, b) for a, b in cols]


def _nearest(cols: list[tuple[float, float]], x0: float, x1: float) -> int:
    def dist(c: tuple[float, float]) -> float:
        overlap = min(c[1], x1) - max(c[0], x0)
        return -overlap if overlap > 0 else min(abs(c[0] - x1), abs(x0 - c[1]))

    return min(range(len(cols)), key=lambda j: dist(cols[j]))


def _over_values(line: _Line, cols: list[tuple[float, float]]) -> bool:
    return bool(cols) and any((s[0].x0 + s[-1].x1) / 2 > cols[0][0] for s in line.segs)


def _header(header: list[_Line], cols: list[tuple[float, float]]) -> tuple[list[str] | None, str | None]:
    """Column paths (``None`` when there is no header) and a unit read from the header lines."""
    if not header:
        return None, None
    segs: list[list[tuple[float, float, str]]] = []  # level -> header cells (x0, x1, text)
    unit: str | None = None
    prev: _Line | None = None
    for ln in header:
        m = _UNIT_LINE.match(ln.text)
        if m:
            unit = unit or normalize_unit(m.group(1))
            continue
        if prev is None or ln.y0 - prev.y1 >= HEADER_JOIN or not segs:
            segs.append([])
        prev = ln
        for s in ln.segs:
            x0, x1 = s[0].x0, s[-1].x1
            if (x0 + x1) / 2 > cols[0][0]:  # else a label-column header ("Chỉ tiêu")
                segs[-1].append((x0, x1, " ".join(w.text for w in s)))
    levels: list[list[list[str]]] = []  # level -> column -> texts
    for k, lv in enumerate(segs):
        levels.append([[] for _ in cols])
        for x0, x1, text in lv:
            hit = _span(cols, lv, x0, x1) if k < len(segs) - 1 else _covered(cols, x0, x1)
            for j in hit:
                levels[-1][j].append(text)
    found = [u for by_col in levels for col in by_col for u in map(_unit_cell, col) if u]
    money = [u for u in found if u in UNIT_SCALE]
    common = collections.Counter(money or found).most_common(1)
    unit = unit or (common[0][0] if common else None)
    paths: list[str] = []
    for j in range(len(cols)):
        parts: list[str] = []
        for by_col in levels:
            joined = " ".join(t for t in by_col[j] if unit is None or _unit_cell(t) != unit)
            if joined and (not parts or parts[-1] != joined):
                parts.append(joined)
        paths.append(" > ".join(parts) or f"col{j + 1}")
    return paths, unit


def _covered(cols: list[tuple[float, float]], x0: float, x1: float) -> list[int]:
    """Columns a header cell substantially covers, else the nearest one."""
    hit = [j for j, c in enumerate(cols) if min(c[1], x1) - max(c[0], x0) >= 0.5 * min(c[1] - c[0], x1 - x0)]
    return hit or [_nearest(cols, x0, x1)]


def _span(
    cols: list[tuple[float, float]], level: list[tuple[float, float, str]], x0: float, x1: float
) -> list[int]:
    """Columns under an upper-level header cell ("Năm 2025" over three columns): among runs of adjacent
    columns that hold the cell's own column and stay between the centres of its neighbours on the level,
    the longest whose centre lies within ``SPAN_TOL`` of the best-centred run."""
    cx = (x0 + x1) / 2
    centres = sorted((a + b) / 2 for a, b, _t in level)
    i = centres.index(cx)
    lo = centres[i - 1] if i else float("-inf")
    hi = centres[i + 1] if i + 1 < len(centres) else float("inf")
    own = _covered(cols, x0, x1)
    inside = {j for j, (a, b) in enumerate(cols) if lo < (a + b) / 2 < hi} | set(own)
    runs = [
        (abs((cols[s][0] + cols[e][1]) / 2 - cx), list(range(s, e + 1)))
        for s in inside
        for e in inside
        if s <= min(own) and e >= max(own) and set(range(s, e + 1)) <= inside
    ]
    if not runs:
        return own
    best = min(off for off, _r in runs)
    return max((r for off, r in runs if off <= best + SPAN_TOL), key=len)


def _unit_cell(text: str) -> str | None:
    """Unit when the whole header cell is one ("Triệu đồng", "(%)"); the table unit is dropped from
    column paths, other units ("%") stay part of them."""
    s = " ".join(text.strip("() ").lower().split())
    u = normalize_unit(s)
    return u if u is not None and s == u else None


def _text_columns(
    head: list[_Line], body: list[_Line], cols: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Text columns between the labels and the values ("Quan hệ"), anchored on header cells that
    start well right of the table's left edge; they end where the next column begins."""
    left = min(w.x0 for ln in body for w in ln.words)
    starts = sorted(
        s[0].x0
        for ln in head
        for s in ln.segs
        if s[0].x0 > left + TEXT_COL_MIN
        and (s[0].x0 + s[-1].x1) / 2 < cols[0][0]
        and s[-1].x1 < cols[0][0]
        and not _UNIT_LINE.match(" ".join(w.text for w in s))
    )
    merged: list[float] = []
    for x in starts:
        if not merged or x - merged[-1] > SEG_GAP:
            merged.append(x)
    edges = [*merged, cols[0][0]]
    return [(edges[k] - 2, edges[k + 1] - 1) for k in range(len(merged))]


def _hint_paths(hint: ExtractedTable, cols: list[tuple[float, float]], x0: float) -> list[str] | None:
    if not hint.rows or not hint.rows[0].cells:
        return None
    ref = hint.rows[0].cells
    if len(ref) == len(cols):
        return [c.col_path for c in ref]
    out: list[str] = []
    for a, b in cols:
        cx = (a + b) / 2 - x0
        best = min(ref, key=lambda c: abs((c.bbox[0] + c.bbox[2]) / 2 - hint.bbox[0] - cx))
        out.append(best.col_path)
    return out


# ---------------------------------------------------------------- tables


def _blocks(lines: list[_Line]) -> list[tuple[list[_Line], list[_Line]]]:
    """(header lines, body lines) of every run of table rows."""
    out: list[tuple[list[_Line], list[_Line]]] = []
    used = -1
    i = 0
    while i < len(lines):
        if lines[i].kind != "row":
            i += 1
            continue
        body = [i]
        k = i + 1
        while (
            k < len(lines)
            and lines[k].kind in ("row", "text")
            and lines[k].y0 - lines[body[-1]].y1 <= MAX_GAP
        ):
            cols = _columns([lines[j] for j in body])
            if lines[k].kind == "text" and _over_values(lines[k], cols):
                break  # header text of the next table
            body.append(k)
            k += 1
        while lines[body[-1]].kind != "row":
            body.pop()
        cols = _columns([lines[j] for j in body])
        lead: list[int] = []  # group labels between the header and the first row ("Tài sản")
        h = i - 1
        top = lines[i]
        while (
            h > used
            and len(lead) < MAX_LEAD_LINES
            and lines[h].kind == "text"
            and top.y0 - lines[h].y1 <= MAX_GAP
            and not _over_values(lines[h], cols)
        ):
            lead.insert(0, h)
            top = lines[h]
            h -= 1
        head: list[int] = []
        while (
            h > used
            and len(head) < MAX_HEADER_LINES
            and lines[h].kind == "text"
            and top.y0 - lines[h].y1 <= MAX_GAP
            and lines[h].y0 >= STATEMENT_BAND
            and not _is_heading(lines[h])
            and _over_values(lines[h], cols)
        ):
            head.insert(0, h)
            top = lines[h]
            h -= 1
            if _UNIT_LINE.match(top.text):
                break  # "Đơn vị: ..." sits on top of the header
        if not head:  # without a header above them the lead lines are headings, not rows
            lead = []
        out.append(([lines[j] for j in head], [lines[j] for j in lead + body]))
        used = body[-1]
        i = body[-1] + 1
    return out


def _wraps(
    prev: _Line | None,
    ln: _Line,
    label_words: list[_Word],
    label_x: list[tuple[int, float, bool]],
    rows: list[TableRow],
) -> bool:
    """``ln`` continues the label of the row above: label words only, set tight under it at the same
    indent, and the row above carries numbers (top-aligned wrap). Label lines *before* a numbered line
    stay rows of their own, so a number binds to the last line of a bottom-aligned label."""
    if prev is None or not rows or not label_x or label_x[-1][0] != len(rows) - 1:
        return False
    if len(label_words) != len(ln.words) or ln.y0 - prev.y1 > WRAP_GAP:
        return False
    if not any(c.raw for c in rows[-1].cells):
        return False
    return abs(label_words[0].x0 - label_x[-1][1]) <= 2


def _heading_above(lines: list[_Line], y: float) -> str | None:
    heads = [ln for ln in lines if ln.y1 <= y + 1 and ln.kind in ("heading", "text") and _is_heading(ln)]
    return heads[-1].text if heads else None


def _is_heading(ln: _Line) -> bool:
    size = max(w.size for w in ln.words)
    return size >= HEADING_SIZE or (size >= 8.4 and all(w.bold for w in ln.words))


def _unit_above(lines: list[_Line], y: float) -> str | None:
    for ln in reversed([ln for ln in lines if ln.y1 <= y + 1]):
        m = _UNIT_LINE.match(ln.text)
        if m:
            return normalize_unit(m.group(1))
    return None


def _half(page: fitz.Page, clip: fitz.Rect) -> tuple[str, list[int]]:
    p = int(page.number or 0) + 1
    if page.rect.width <= page.rect.height:
        return "S", [p]
    if (clip.x0 + clip.x1) / 2 < page.rect.width / 2:
        return "L", [2 * p - 2]
    return "R", [2 * p - 1]


def fallback_tables(
    page: fitz.Page, clip: fitz.Rect, header_hint: ExtractedTable | None
) -> list[ExtractedTable]:
    """Tables rebuilt from word coordinates in ``clip``; ``header_hint`` names the columns of a
    first table that has no header of its own (a continuation)."""
    clip = fitz.Rect(clip)  # type: ignore[no-untyped-call]
    lines = _lines(_words(page, clip), float(clip.width))
    half, printed = _half(page, clip)
    stmt = statement_code(page, clip)
    out: list[ExtractedTable] = []
    for n, (head, body) in enumerate(_blocks(lines), start=1):
        cols = _columns(body)
        if not cols:
            continue
        cols = _text_columns(head, body, cols) + cols
        paths, unit = _header(head, cols)
        all_words = [w for ln in head + body for w in ln.words]
        box: BBox = (
            min(w.x0 for w in all_words),
            min(w.y0 for w in all_words),
            max(w.x1 for w in all_words),
            max(w.y1 for w in all_words),
        )
        hint = header_hint if n == 1 else None
        if paths is None and hint is not None:
            paths = _hint_paths(hint, cols, box[0])
        if paths is None:
            paths = [f"col{j + 1}" for j in range(len(cols))]
        note_col = next((j for j, p in enumerate(paths) if _NOTE_HEADER.fullmatch(p.strip())), None)
        rows: list[TableRow] = []
        label_x: list[tuple[int, float, bool]] = []
        prev: _Line | None = None
        for ln in body:
            label_words = [w for w in ln.words if w.x0 < cols[0][0] - 1]
            if _wraps(prev, ln, label_words, label_x, rows):
                last = rows[-1]
                label = f"{last.label} {' '.join(w.text for w in label_words)}"
                rows[-1] = TableRow(label, 0, None, False, last.note_ref, last.cells)
                prev = ln
                continue
            prev = ln
            texts: list[list[str]] = [[] for _ in cols]
            for w in ln.words:
                if w not in label_words:
                    texts[_nearest(cols, w.x0, w.x1)].append(w.text)
            note = (" ".join(texts[note_col]) or None) if note_col is not None else None
            cells = [
                Cell(paths[j], " ".join(texts[j]), (a, ln.y0, b, ln.y1))
                for j, (a, b) in enumerate(cols)
                if j != note_col
            ]
            if label_words:
                label_x.append((len(rows), label_words[0].x0, label_words[0].bold))
            rows.append(TableRow(" ".join(w.text for w in label_words), 0, None, False, note, cells))
        title = _heading_above(lines, box[1]) or (hint.title if hint else None)
        m = _NOTE_NO.match(title) if title else None
        note_no = m.group(1) if m else (hint.note_no if hint else None)
        unit = unit or _unit_above(lines, box[1]) or (hint.unit if hint else None)
        out.append(
            ExtractedTable(
                table_id=f"p{int(page.number or 0) + 1}{half}_f{len(out) + 1:02d}",
                pdf_page=int(page.number or 0) + 1,
                half=half,
                printed_pages=printed,
                bbox=box,
                title=title,
                note_no=note_no,
                statement=stmt,
                unit=unit or chapter_default_unit(printed[0]),
                spans_gutter=False,
                continues=None,
                rows=hierarchy(rows, label_x),
            )
        )
    return out


# ---------------------------------------------------------------- QA


def _overlaps(a: BBox, b: BBox) -> bool:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    area = (a[2] - a[0]) * (a[3] - a[1])
    return area > 0 and max(w, 0) * max(h, 0) / area > 0.5


def qa_tables(doc: fitz.Document, pdf_page: int) -> tuple[list[ExtractedTable], list[QAResult]]:
    """Tables of one PDF page after coverage QA, and the QA result of each half."""
    page = doc[pdf_page - 1]
    W, H = float(page.rect.width), float(page.rect.height)
    tables = extract_tables(doc, pdf_page)
    gutter = [t for t in tables if t.half == "G"]
    sides = [("L", 0.0, W / 2), ("R", W / 2, W)] if W > H else [("S", 0.0, W)]
    kept: list[ExtractedTable] = []
    results: list[QAResult] = []
    previous: list[ExtractedTable] | None = None
    for side, x0, x1 in sides:
        clip = _rect(x0, HEADER_BAND, x1, H)
        own = [t for t in tables if t.half == side]
        numbers, covered = coverage(page, clip, own + gutter)
        ratio = covered / numbers if numbers else 1.0
        empty = _none_columns(own)
        ran = ratio < MIN_RATIO or empty > 0
        if ran:
            if side == "R":
                hints = [t for t in tables if t.half == "L"]
            else:
                if previous is None:
                    previous = extract_tables(doc, pdf_page - 1) if pdf_page > 1 else []
                hints = [t for t in previous if t.half != "G"]
            fb = [
                t
                for t in fallback_tables(page, clip, hints[-1] if hints else None)
                if not any(_overlaps(t.bbox, g.bbox) for g in gutter)
            ]
            fb_numbers, fb_covered = coverage(page, clip, fb + gutter)
            fb_ratio = fb_covered / fb_numbers if fb_numbers else 1.0
            if fb_ratio > ratio:
                own, covered, ratio, empty = fb, fb_covered, fb_ratio, _none_columns(fb)
        kept += own
        results.append(QAResult(pdf_page, side, numbers, covered, ratio, empty, ran))
    return kept + gutter, results

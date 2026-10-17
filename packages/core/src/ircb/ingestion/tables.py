"""Table extraction per half page, plus tables that straddle the gutter (spec §5.3 steps 1-4, 6-7).

Text is rebuilt from characters placed on the ``find_tables`` grid (not from ``Table.extract``) so that
superscript footnote markers are dropped and values glued into one merged cell are split by column.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import pymupdf as fitz

from ircb.domain.numbers_vn import normalize_chars, parse_vn
from ircb.domain.units import UNIT_SCALE, normalize_unit
from ircb.ingestion.layout import statement_code
from ircb.ingestion.spread import HEADER_BAND, _rect

BBox = tuple[float, float, float, float]

GUTTER_BAND = 20  # pt either side of W/2
INDENT_STEP = 4  # pt per row_level bucket (spec finding #13)
HEADING_MIN_SIZE = 9.5  # body text is 8.5pt, table text 7.5pt; headings are 10pt and up
SUBHEADING_MIN_SIZE = 8.5
STATEMENT_BAND = 85  # pt: statement/notes title and "tại ngày ..." lines sit above this
HEADER_ONLY_GAP = 30  # pt: find_tables sometimes splits a header block from its body
_FLAG_SUPERSCRIPT = 1
_FLAG_BOLD = 16
_DASHES = {"-", "–", "—", "‑", "−"}
_YEAR_OR_DATE = re.compile(r"(?:19|20)\d{2}|\d{1,2}/\d{1,2}/(?:19|20)\d{2}")
_UNIT_LINE = re.compile(r"^\s*Đơn vị(?: tính)?\s*:\s*(.+)$", re.IGNORECASE)
_NUMERIC_ONLY = re.compile(r"[\d.,%\s()+\-–—~≈]+")
_BULLET = re.compile(r"^[-–+•]\s")
_NOTE_NO = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")
_CONTINUED = "(tiếp theo)"
_SECTIONS_REL = Path("config") / "sections.json"


@dataclass(frozen=True)
class Cell:
    col_path: str
    raw: str
    bbox: BBox


@dataclass(frozen=True)
class TableRow:
    label: str
    row_level: int
    parent_label: str | None
    is_total: bool
    note_ref: str | None
    cells: list[Cell]


@dataclass
class ExtractedTable:
    table_id: str
    pdf_page: int
    half: str
    printed_pages: list[int]
    bbox: BBox
    title: str | None
    note_no: str | None
    statement: str | None
    unit: str | None
    spans_gutter: bool
    continues: str | None
    rows: list[TableRow]


@dataclass(frozen=True)
class _Char:
    c: str
    x0: float
    y0: float
    x1: float
    y1: float
    bold: bool
    line: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class _Line:
    text: str
    bbox: BBox
    size: float
    bold: bool


def cell_value(raw: str) -> Decimal | None:
    """Numeric value of a cell: a lone dash of any kind is zero, blank/non-numeric is None."""
    s = normalize_chars(raw).strip()
    if not s:
        return None
    if s in _DASHES:
        return Decimal(0)
    try:
        return parse_vn(s).value
    except ValueError:
        return None


# ---------------------------------------------------------------- page text


def _page_dict(page: fitz.Page) -> dict[str, Any]:
    data: dict[str, Any] = page.get_text("rawdict")  # type: ignore[no-untyped-call]
    return data


def _chars_and_lines(page: fitz.Page) -> tuple[list[_Char], list[_Line]]:
    chars: list[_Char] = []
    lines: list[_Line] = []
    line_id = 0
    for block in _page_dict(page)["blocks"]:
        for line in block.get("lines", []):
            line_id += 1
            text = ""
            size = 0.0
            first = len(chars)
            for sp in line["spans"]:
                flags = int(sp["flags"])
                if flags & _FLAG_SUPERSCRIPT:
                    continue
                bold = bool(flags & _FLAG_BOLD) or "bold" in str(sp["font"]).lower()
                size = max(size, float(sp["size"]))
                for ch in sp["chars"]:
                    c = normalize_chars(ch["c"])
                    x0, y0, x1, y1 = (float(v) for v in ch["bbox"])
                    chars.append(_Char(c, x0, y0, x1, y1, bold, line_id))
                    text += c
            x0, y0, x1, y1 = (float(v) for v in line["bbox"])
            if text.strip():
                bold_line = all(c.bold for c in chars[first:] if c.c.strip())
                lines.append(_Line(" ".join(text.split()), (x0, y0, x1, y1), size, bold_line))
    return chars, lines


def _inside(c: _Char, box: BBox) -> bool:
    return box[0] <= c.cx <= box[2] and box[1] <= c.cy <= box[3]


def _text(chars: list[_Char], box: BBox) -> list[str]:
    """Lines of text (stream order) whose characters' centres fall in ``box``."""
    out: list[str] = []
    cur = ""
    last = None
    for c in chars:
        if not _inside(c, box):
            continue
        if last is not None and c.line != last:
            out.append(cur)
            cur = ""
        cur += c.c
        last = c.line
    out.append(cur)
    return [t for t in (" ".join(s.split()) for s in out) if t]


# ---------------------------------------------------------------- grid


def _grid(t: Any) -> tuple[list[tuple[float, float]], list[tuple[float, float]], list[BBox]]:
    """Column x-ranges, row y-ranges (narrowest real cell wins) and every real cell rect."""
    rects: list[BBox] = []
    cols: list[tuple[float, float] | None] = [None] * t.col_count
    rows: list[tuple[float, float]] = []
    for r in t.rows:
        real = [tuple(float(v) for v in c) for c in r.cells if c is not None]
        rects.extend(real)  # type: ignore[arg-type]
        best = min(real, key=lambda b: b[3] - b[1])
        rows.append((best[1], best[3]))
        for j, c in enumerate(r.cells):
            if c is None:
                continue
            x0, x1 = float(c[0]), float(c[2])
            cur = cols[j]
            if cur is None or x1 - x0 < cur[1] - cur[0]:
                cols[j] = (x0, x1)
    tx0, _, tx1, _ = (float(v) for v in t.bbox)
    filled: list[tuple[float, float]] = []
    for j, cr in enumerate(cols):
        if cr is None:  # never seen alone: take the gap between neighbours
            left = filled[-1][1] if filled else tx0
            right = next((c[0] for c in cols[j + 1 :] if c is not None), tx1)
            cr = (left, right)
        filled.append(cr)
    return filled, rows, rects


def _is_value(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    if s in _DASHES:
        return True
    if _YEAR_OR_DATE.fullmatch(s):
        return False
    return bool(_NUMERIC_ONLY.fullmatch(s)) and any(ch.isdigit() for ch in s)


def _unit_of_line(line: str) -> str | None:
    """Unit when the whole line is a unit ("Triệu đồng", "(%)"), never on prose."""
    s = " ".join(line.strip().strip("()").lower().split())
    u = normalize_unit(s)
    return u if u is not None and s == u else None


def _header_paths(
    chars: list[_Char],
    cols: list[tuple[float, float]],
    rows: list[tuple[float, float]],
    rects: list[BBox],
    stop_before_last: bool = True,
) -> tuple[int, list[list[list[str]]]]:
    """Number of header rows and, per column, the header text lines of each header level.

    Header text is read from the real (possibly merged) cell covering each grid position, so a
    label centred across two columns ("2025") is not split. Header rows end at the first row
    holding a value (years and dates do not count) or with nothing beyond the label column.
    """
    levels: list[list[list[str]]] = [[] for _ in cols]
    n_hdr = 0
    for y0, y1 in rows[: max(len(rows) - 1, 0) if stop_before_last else len(rows)]:
        cy = (y0 + y1) / 2
        row: list[list[str]] = []
        for x0, x1 in cols:
            cx = (x0 + x1) / 2
            cover = next((b for b in rects if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]), (x0, y0, x1, y1))
            row.append(_text(chars, cover))
        texts = [" ".join(t) for t in row[1:]]
        if not any(texts) or any(_is_value(s) for s in texts):
            break
        for j, t in enumerate(row):
            levels[j].append(t)
        n_hdr += 1
    return n_hdr, levels


# ---------------------------------------------------------------- context


def _headings(lines: list[_Line], region: BBox, table_boxes: list[BBox]) -> list[tuple[float, str]]:
    """Heading blocks (top y, text) in ``region`` outside tables, adjacent lines merged.

    A heading is a line of >= 9.5pt, or a bold body-size (>= 8.5pt) sub-heading below the
    statement title band (that band holds "THUYẾT MINH ... (tiếp theo)" on every notes page).
    """
    big = [
        ln
        for ln in lines
        if (
            (ln.size >= HEADING_MIN_SIZE and ln.bbox[1] >= HEADER_BAND)
            or (ln.bold and ln.size >= SUBHEADING_MIN_SIZE and ln.bbox[1] >= STATEMENT_BAND)
        )
        and region[0] <= (ln.bbox[0] + ln.bbox[2]) / 2 <= region[2]
        and not any(b[0] <= ln.bbox[0] <= b[2] and b[1] <= ln.bbox[1] <= b[3] for b in table_boxes)
    ]
    big.sort(key=lambda ln: (ln.bbox[1], ln.bbox[0]))
    blocks: list[tuple[float, float, float, list[str]]] = []  # top, bottom, size, texts
    for ln in big:
        if blocks:
            top, bottom, size, texts = blocks[-1]
            if abs(size - ln.size) < 0.5 and -ln.size / 2 <= ln.bbox[1] - bottom < ln.size:
                blocks[-1] = (top, ln.bbox[3], size, [*texts, ln.text])
                continue
        blocks.append((ln.bbox[1], ln.bbox[3], ln.size, [ln.text]))
    return [(top, " ".join(texts).strip()) for top, _b, _s, texts in blocks]


def _unit_line_above(lines: list[_Line], box: BBox, floor: float) -> str | None:
    best: tuple[float, str] | None = None
    for ln in lines:
        m = _UNIT_LINE.match(ln.text)
        if not m or ln.bbox[3] > box[1] + 3 or ln.bbox[1] < floor:
            continue
        if ln.bbox[2] < box[0] or ln.bbox[0] > box[2]:
            continue
        u = normalize_unit(m.group(1))
        if u and (best is None or ln.bbox[1] > best[0]):
            best = (ln.bbox[1], u)
    return best[1] if best else None


@lru_cache(maxsize=4)
def _sections(path: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def _sections_path() -> Path:
    local = Path.cwd() / _SECTIONS_REL
    return local if local.exists() else Path(__file__).resolve().parents[5] / _SECTIONS_REL


def chapter_default_unit(printed: int) -> str | None:
    path = _sections_path()
    if not path.exists():
        return None
    for s in _sections(str(path)):
        if int(s["printed_start"]) <= printed <= int(s["printed_end"]):
            unit = s.get("default_unit")
            return str(unit) if unit else None
    return None


# ---------------------------------------------------------------- one table


def _header_only(t: Any, nxt: Any, chars: list[_Char]) -> list[list[list[str]]] | None:
    """Header levels of ``t`` when it is a value-free block sitting right on top of ``nxt``."""
    if nxt is None or t.col_count != nxt.col_count or not 0 <= nxt.bbox[1] - t.bbox[3] < HEADER_ONLY_GAP:
        return None
    if abs(t.bbox[0] - nxt.bbox[0]) > 10 or abs(t.bbox[2] - nxt.bbox[2]) > 10:
        return None
    cols, rows, rects = _grid(t)
    n_hdr, levels = _header_paths(chars, cols, rows, rects, stop_before_last=False)
    if n_hdr != len(rows):
        return None
    ncols, nrows, nrects = _grid(nxt)
    if _header_paths(chars, ncols, nrows, nrects)[0] != 0:
        return None
    return levels


def _build(
    t: Any, chars: list[_Char], lines: list[_Line], floor: float, borrowed: list[list[list[str]]] | None
) -> tuple[BBox, list[TableRow], str | None]:
    cols, rows, rects = _grid(t)
    n_hdr, levels = _header_paths(chars, cols, rows, rects)
    last_texts = [" ".join(_text(chars, (x0, rows[-1][0], x1, rows[-1][1]))) for x0, x1 in cols[1:]]
    if n_hdr > 1 and n_hdr == len(rows) - 1 and not any(map(_is_value, last_texts)):
        # value-free text table: header detection ran to the last row; only the first row is header
        n_hdr, levels = 1, [lv[:1] for lv in levels]
    if n_hdr == 0 and borrowed is not None:
        levels = [list(lv) for lv in borrowed]
    if t.header.external and t.header.names:
        for j, name in enumerate(t.header.names[: len(cols)]):
            levels[j].insert(0, [s.strip() for s in str(name or "").splitlines() if s.strip()])
    hdr_units = [u for lv in levels[1:] for lines_ in lv for u in map(_unit_of_line, lines_) if u]
    money = [u for u in hdr_units if u in UNIT_SCALE]
    common = Counter(money or hdr_units).most_common(1)
    box: BBox = tuple(float(v) for v in t.bbox)  # type: ignore[assignment]
    unit = common[0][0] if common else _unit_line_above(lines, box, floor)

    paths: list[str] = []
    for j, lv in enumerate(levels):
        parts: list[str] = []
        for lines_ in lv:
            kept = " ".join(s for s in lines_ if _unit_of_line(s) is None or _unit_of_line(s) != unit)
            if kept and (not parts or parts[-1] != kept):
                parts.append(kept)
        paths.append(" > ".join(parts) or f"col{j}")
    note_col = next((j for j, p in enumerate(paths) if j and "thuyết minh" in p.lower()), None)

    out: list[TableRow] = []
    label_x: list[tuple[int, float, bool]] = []  # (row index in out, x0, bold)
    for y0, y1 in rows[n_hdr:]:
        lx0, lx1 = cols[0]
        label_chars = [c for c in chars if c.c.strip() and _inside(c, (lx0, y0, lx1, y1))]
        label = " ".join(_text(chars, (lx0, y0, lx1, y1)))
        note = None
        cells: list[Cell] = []
        for j, (x0, x1) in enumerate(cols[1:], start=1):
            raw = " ".join(_text(chars, (x0, y0, x1, y1)))
            if j == note_col:
                note = raw or None
            else:
                cells.append(Cell(paths[j], raw, (x0, y0, x1, y1)))
        if not label and not any(c.raw for c in cells):
            continue
        if label_chars:
            label_x.append((len(out), label_chars[0].x0, label_chars[0].bold))
        out.append(TableRow(label, 0, None, False, note, cells))
    return box, hierarchy(out, label_x), unit


def hierarchy(rows: list[TableRow], label_x: list[tuple[int, float, bool]]) -> list[TableRow]:
    """row_level = 4pt x0 bucket + (0 bold | 1 regular), +1 for "- "/"+ "/"• " bullet labels;
    parent = nearest row above with a lower level, never looking past a grand total.
    Unlabelled rows with a number are totals (``_total_label``); without one they continue the row above.
    """
    min_x = min((x for _, x, _ in label_x), default=0.0)
    level = {i: round((x - min_x) / INDENT_STEP) + (0 if bold else 1) for i, x, bold in label_x}
    out: list[TableRow] = []
    parents: list[int | None] = []  # row index of each output row's parent
    for i, r in enumerate(rows):
        if not r.label and not any(cell_value(c.raw) is not None for c in r.cells):
            if out:  # wrapped text row: same label, level and parent as the row above
                above = out[-1]
                out.append(
                    TableRow(above.label, above.row_level, above.parent_label, False, r.note_ref, r.cells)
                )
                parents.append(parents[-1])
            else:
                out.append(r)
                parents.append(None)
            continue
        if r.label:
            lv = level.get(i, 1) + (1 if _BULLET.match(r.label) else 0)
            pidx = None
            for k in range(len(out) - 1, -1, -1):
                p = out[k]
                if p.is_total and p.parent_label is None:
                    break
                if not p.is_total and p.row_level < lv:
                    pidx = k
                    break
            out.append(
                TableRow(
                    r.label, lv, out[pidx].label if pidx is not None else None, False, r.note_ref, r.cells
                )
            )
            parents.append(pidx)
            continue
        label, pidx, lv = _total_label(out, parents, r)
        out.append(
            TableRow(label, lv, out[pidx].label if pidx is not None else None, True, r.note_ref, r.cells)
        )
        parents.append(pidx)
    return out


def _col_value(r: TableRow, j: int) -> Decimal:
    v = cell_value(r.cells[j].raw) if j < len(r.cells) else None
    return v if v is not None else Decimal(0)


def _total_label(
    done: list[TableRow], parents: list[int | None], total: TableRow
) -> tuple[str, int | None, int]:
    """Name an unlabelled total by checking which rows it actually sums (first value column).

    "Tổng (P)" when it equals the children of the nearest value-less group P (resolved by row index,
    labels repeat); "Tổng cộng" when it equals the top-level rows (alone, or after the previous
    total); otherwise plain "Tổng". Returns (label, parent row index, level).
    """
    j = next((k for k, c in enumerate(total.cells) if cell_value(c.raw) is not None), None)
    if j is None or not done:
        return "Tổng", None, 0
    target = _col_value(total, j)
    last_total = max((k for k, r in enumerate(done) if r.is_total), default=-1)
    since_idx = [k for k in range(last_total + 1, len(done)) if not done[k].is_total]
    since = [done[k] for k in since_idx]
    prev_idx = since_idx[-1] if since_idx else len(done) - 1
    pidx = parents[prev_idx]
    if pidx is not None:
        parent = done[pidx]
        kids = [r for r in done[pidx + 1 :] if not r.is_total and r.row_level > parent.row_level]
        if (
            cell_value(parent.cells[j].raw if j < len(parent.cells) else "") is None
            and sum((_col_value(r, j) for r in kids), Decimal(0)) == target
        ):
            return f"Tổng ({parent.label})", pidx, parent.row_level
    base = _col_value(done[last_total], j) if last_total >= 0 else Decimal(0)
    everything = [r for r in done if not r.is_total]
    for pool, offset in ((since, Decimal(0)), (since, base), (everything, Decimal(0))):
        if not pool:
            continue
        top = min(r.row_level for r in pool)
        if offset + sum((_col_value(r, j) for r in pool if r.row_level == top), Decimal(0)) == target:
            return "Tổng cộng", None, top
    return "Tổng", None, done[prev_idx].row_level


# ---------------------------------------------------------------- page


def _overlap(a: BBox, b: BBox) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    area = (a[2] - a[0]) * (a[3] - a[1])
    return max(w, 0) * max(h, 0) / area if area > 0 else 0.0


def _found(page: fitz.Page, clip: fitz.Rect | None = None) -> list[Any]:
    tf = page.find_tables(clip=clip) if clip is not None else page.find_tables()  # type: ignore[no-untyped-call]
    return list(tf.tables)


def _previous_headings(doc: fitz.Document, pdf_page: int) -> list[tuple[float, str]]:
    """Headings of the previous PDF page in reading order (left half, then right half)."""
    if pdf_page <= 1:
        return []
    page = doc[pdf_page - 2]
    W, H = float(page.rect.width), float(page.rect.height)
    _, lines = _chars_and_lines(page)
    return _headings(lines, (0.0, 0.0, W / 2, H), []) + _headings(lines, (W / 2, 0.0, W, H), [])


def _context(history: list[tuple[float, str]]) -> tuple[str | None, str | None]:
    """(title, note_no) from the headings seen so far: nearest heading, under the last numbered one."""
    if not history:
        return None, None
    title = history[-1][1]
    numbered = next((h for _, h in reversed(history) if _NOTE_NO.match(h)), None)
    m = _NOTE_NO.match(numbered) if numbered else None
    if numbered and numbered != title:
        title = f"{numbered} – {title}"
    return title, (m.group(1) if m else None)


def extract_tables(doc: fitz.Document, pdf_page: int) -> list[ExtractedTable]:
    """Tables of both halves and gutter-spanning tables of one PDF page (1-based)."""
    page = doc[pdf_page - 1]
    W, H = float(page.rect.width), float(page.rect.height)
    chars, lines = _chars_and_lines(page)
    if W > H:
        whole = _found(page)
        gutter = [t for t in whole if t.bbox[0] < W / 2 - GUTTER_BAND and t.bbox[2] > W / 2 + GUTTER_BAND]
        gboxes: list[BBox] = [tuple(float(v) for v in t.bbox) for t in gutter]  # type: ignore[misc]
        jobs: list[tuple[str, list[int], BBox, list[Any]]] = []
        for side, x0, x1, pp in (("L", 0.0, W / 2, 2 * pdf_page - 2), ("R", W / 2, W, 2 * pdf_page - 1)):
            found = [
                t
                for t in _found(page, _rect(x0, 0, x1, H))
                if not any(_overlap(tuple(float(v) for v in t.bbox), g) > 0.5 for g in gboxes)  # type: ignore[arg-type]
            ]
            jobs.append((side, [pp], (x0, 0.0, x1, H), found))
        jobs.append(("G", [2 * pdf_page - 2, 2 * pdf_page - 1], (0.0, 0.0, W, H), gutter))
    else:
        jobs = [("S", [pdf_page], (0.0, 0.0, W, H), _found(page))]
    all_boxes: list[BBox] = [tuple(float(v) for v in t.bbox) for _h, _p, _r, ts in jobs for t in ts]  # type: ignore[misc]

    out: list[ExtractedTable] = []
    earlier: list[tuple[float, str]] | None = None  # previous page's headings, loaded on demand
    for half, printed, region, found in jobs:
        found.sort(key=lambda t: (round(t.bbox[1]), t.bbox[0]))
        stmt = statement_code(page, _rect(*region))
        heads = _headings(lines, region, all_boxes)
        left = _headings(lines, (0.0, 0.0, W / 2, H), all_boxes) if half == "R" else []
        floor, n, borrowed = float(HEADER_BAND), 0, None
        for i, t in enumerate(found):
            header = _header_only(t, found[i + 1] if i + 1 < len(found) else None, chars)
            if header is not None:  # a header split off its body: lend it to the next table
                borrowed = header
                continue
            box, rows, unit = _build(t, chars, lines, floor, borrowed)
            floor, borrowed = box[3], None
            if not rows:
                continue
            above = [h for h in heads if h[0] <= box[1] + 3]
            history = left + above
            if not any(_NOTE_NO.match(h) for _, h in history):
                if earlier is None:
                    earlier = _previous_headings(doc, pdf_page)
                history = earlier + history
            title, note_no = _context(history)
            n += 1
            out.append(
                ExtractedTable(
                    table_id=f"p{pdf_page}{half}_t{n:02d}",
                    pdf_page=pdf_page,
                    half=half,
                    printed_pages=printed,
                    bbox=box,
                    title=title,
                    note_no=note_no,
                    statement=stmt,
                    unit=unit or chapter_default_unit(printed[0]),
                    spans_gutter=half == "G",
                    continues=None,
                    rows=rows,
                )
            )
    _link_continuations(doc, pdf_page, out)
    return out


def _link_continuations(doc: fitz.Document, pdf_page: int, tables: list[ExtractedTable]) -> None:
    """A table whose own heading says "(tiếp theo)" continues the last earlier table of its note
    (same page first, then the previous page). In this PDF "(tiếp theo)" appears only in the running
    notes header, never in a table heading, so nothing gets linked here (see task report).
    """
    previous: list[ExtractedTable] | None = None
    for i, t in enumerate(tables):
        if t.title is None or _CONTINUED not in t.title.lower() or t.note_no is None:
            continue
        prev = [p for p in tables[:i] if p.note_no == t.note_no]
        if not prev and pdf_page > 1:
            if previous is None:
                previous = extract_tables(doc, pdf_page - 1)
            prev = [p for p in previous if p.note_no == t.note_no]
        if prev:
            t.continues = prev[-1].table_id


def _md(text: str) -> str:
    return text.replace("|", r"\|")


def table_to_markdown(t: ExtractedTable) -> str:
    pages = ", ".join(str(p) for p in t.printed_pages)
    meta = [
        f"Đơn vị: {t.unit}" if t.unit else None,
        t.statement,
        f"Thuyết minh {t.note_no}" if t.note_no else None,
    ]
    head = f"### {t.title or 'Bảng'} [tr. {pages}]"
    if t.continues:
        head += " (tiếp theo)"
    cols = [c.col_path for c in t.rows[0].cells] if t.rows else []
    lines = [head, " · ".join(m for m in meta if m), "", "| Chỉ tiêu | " + " | ".join(map(_md, cols)) + " |"]
    lines.append("|" + "---|" * (len(cols) + 1))
    rank = {lv: k for k, lv in enumerate(sorted({r.row_level for r in t.rows}))}
    for r in t.rows:
        d = rank[r.row_level]
        label = ("· " * d) + r.label + (f" (TM {r.note_ref})" if r.note_ref else "")
        lines.append("| " + _md(label) + " | " + " | ".join(_md(c.raw) for c in r.cells) + " |")
    return "\n".join(lines) + "\n"

"""Chunk builders for prose, tables, KPI tile groups and glossary entries (spec §5.6)."""

import math
import re
from dataclasses import replace
from typing import Literal

from ircb.domain.models import Chunk
from ircb.ingestion.facts import DOC_ID, facts_from_kpi, kpi_change_number, label_norm, row_facts
from ircb.ingestion.glossary import GlossaryEntry
from ircb.ingestion.kpi import KpiTile
from ircb.ingestion.prose import ProseBlock
from ircb.ingestion.tables import ExtractedTable, table_to_markdown

Half = Literal["L", "R", "S"]
BBox = tuple[float, float, float, float]

TOKENS_PER_WORD = 1.3
MIN_TOKENS = 300
MAX_TOKENS = 500
MAX_WORDS = int(MAX_TOKENS / TOKENS_PER_WORD)
MIN_WORDS = math.ceil(MIN_TOKENS / TOKENS_PER_WORD)
MAX_TABLE_ROWS = 30

_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")
_BASIS_PHRASE = {"N/N": "so với cùng kỳ năm trước"}


def _union(boxes: list[BBox]) -> list[float]:
    return [
        float(min(b[0] for b in boxes)),
        float(min(b[1] for b in boxes)),
        float(max(b[2] for b in boxes)),
        float(max(b[3] for b in boxes)),
    ]


# ---------------------------------------------------------------- prose


def _pieces(text: str) -> list[tuple[str, bool]]:
    """(sentence, starts_new_paragraph) with no piece above MAX_WORDS."""
    out: list[tuple[str, bool]] = []
    for para in (p.strip() for p in text.split("\n")):
        if not para:
            continue
        first = True
        for sent in _SENTENCE_END.split(para):
            words = sent.split()
            for i in range(0, len(words), MAX_WORDS):
                out.append((" ".join(words[i : i + MAX_WORDS]), first))
                first = False
    return out


def chunks_from_prose(
    blocks: list[ProseBlock], pdf_page: int, half: Half, chapter: str | None
) -> list[Chunk]:
    """Pack prose into 300-500 token chunks within one half page, prepending ``chapter > heading``."""
    chunks: list[Chunk] = []
    lines: list[str] = []
    words = 0
    first_heading: str | None = None
    last_heading: str | None = None  # continuation chunks repeat the section heading
    used: list[ProseBlock] = []

    def flush() -> None:
        nonlocal lines, words, first_heading, used
        if lines:
            prefix = " > ".join(p for p in (chapter, first_heading) if p)
            body = "\n".join(lines)
            chunks.append(
                Chunk(
                    chunk_id=f"p{pdf_page}{half}_x{len(chunks) + 1:02d}",
                    doc_id=DOC_ID,
                    pdf_page=pdf_page,
                    half=half,
                    printed_pages=[used[0].printed_page],
                    chapter=chapter,
                    statement=None,
                    note_no=None,
                    content_type="prose",
                    unit=None,
                    text=f"{prefix}\n{body}" if prefix else body,
                    fact_ids=[],
                    bbox=_union([b.bbox for b in used]),
                )
            )
        lines, words, first_heading, used = [], 0, last_heading, []

    def add(block: ProseBlock, text: str, new_line: bool) -> None:
        nonlocal words
        if not any(block is b for b in used):
            used.append(block)
        if new_line or not lines:
            lines.append(text)
        else:
            lines[-1] += " " + text
        words += len(text.split())

    for block in blocks:
        if block.heading:
            last_heading = block.heading
            if words >= MIN_WORDS or words + len(block.heading.split()) > MAX_WORDS:
                flush()
            if not lines:
                first_heading = block.heading
                if not any(block is b for b in used):
                    used.append(block)
            else:
                add(block, block.heading, True)
        for sent, new_para in _pieces(block.text):
            if words + len(sent.split()) > MAX_WORDS:
                flush()
            add(block, sent, new_para)
    flush()
    return chunks


# ---------------------------------------------------------------- table


def chunks_from_table(t: ExtractedTable, chapter: str | None = None) -> list[Chunk]:
    """One chunk per table, or per row group (header repeated) when the table is long."""
    meta = " · ".join(
        p for p in (t.statement, t.note_no, t.title, f"Đơn vị: {t.unit}" if t.unit else None) if p
    )
    starts = list(range(0, max(len(t.rows), 1), MAX_TABLE_ROWS))
    out: list[Chunk] = []
    for gi, start in enumerate(starts):
        rows = t.rows[start : start + MAX_TABLE_ROWS]
        # table_to_markdown emits a title line, a meta line and a blank line before the grid.
        grid = table_to_markdown(replace(t, rows=rows)).splitlines()[3:]
        text = "\n".join([meta, *grid]) if meta else "\n".join(grid)
        fact_ids = [f.fact_id for off, r in enumerate(rows) for f in row_facts(t, start + off, r, chapter)]
        cid = t.table_id if len(starts) == 1 else f"{t.table_id}_g{gi + 1:02d}"
        out.append(
            Chunk(
                chunk_id=cid,
                doc_id=DOC_ID,
                pdf_page=t.pdf_page,
                half=t.half,
                printed_pages=list(t.printed_pages),
                chapter=chapter,
                statement=t.statement,
                note_no=t.note_no,
                content_type="table",
                unit=t.unit,
                text=text,
                fact_ids=fact_ids,
                bbox=[float(v) for v in t.bbox],
            )
        )
    return out


# ---------------------------------------------------------------- kpi


def _kpi_sentence(tile: KpiTile) -> str:
    value = tile.value_raw + (f" {tile.unit}" if tile.unit else "")
    s = f"{tile.label}: {value}"
    num = kpi_change_number(tile)
    if num is None:
        return s
    basis = tile.change_basis
    if basis and basis.startswith("CAGR"):  # "tăng trưởng kép (CAGR) 2018–2025: 16,5%"
        return f"{s}, tăng trưởng kép (CAGR) {basis[len('CAGR') :].strip()}: {num}%"
    if tile.direction in ("up", "down"):
        verb = "tăng" if tile.direction == "up" else "giảm"
        phrase = _BASIS_PHRASE.get(basis, basis) if basis else None
        return f"{s}, {verb} {num}%" + (f" {phrase}" if phrase else "")
    return f"{s}, thay đổi {num}%" + (f" {basis}" if basis else "")


def chunks_from_kpi(
    tiles: list[KpiTile], pdf_page: int, half: Half = "L", chapter: str | None = None
) -> list[Chunk]:
    """One chunk per half page's tile group, as normalised sentences."""
    if not tiles:
        return []
    lines: list[str] = []
    fact_ids: list[str] = []
    ctx: str | None = None
    for i, tile in enumerate(tiles, start=1):
        if tile.context and tile.context != ctx:
            lines.append(tile.context)
            ctx = tile.context
        lines.append(_kpi_sentence(tile))
        fact_ids += [f.fact_id for f in facts_from_kpi(tile, pdf_page, half, i, chapter)]
    return [
        Chunk(
            chunk_id=f"p{pdf_page}{half}_k",
            doc_id=DOC_ID,
            pdf_page=pdf_page,
            half=half,
            printed_pages=[tiles[0].printed_page],
            chapter=chapter,
            statement=None,
            note_no=None,
            content_type="kpi",
            unit=None,
            text="\n".join(lines),
            fact_ids=fact_ids,
            bbox=_union([t.bbox for t in tiles]),
        )
    ]


# ---------------------------------------------------------------- glossary


def _glossary_slug(term: str) -> str:
    return "_".join(re.sub(r"[^a-z0-9 ]", " ", label_norm(term)).split())


def chunks_from_glossary(
    entries: list[GlossaryEntry], pdf_page: int, half: Half = "L", chapter: str | None = None
) -> list[Chunk]:
    seen: dict[str, int] = {}
    out: list[Chunk] = []
    for e in entries:
        slug = _glossary_slug(e.term) or "term"
        seen[slug] = seen.get(slug, 0) + 1
        cid = f"g_{slug}" if seen[slug] == 1 else f"g_{slug}_{seen[slug]}"
        out.append(
            Chunk(
                chunk_id=cid,
                doc_id=DOC_ID,
                pdf_page=pdf_page,
                half=half,
                printed_pages=[e.printed_page],
                chapter=chapter,
                statement=None,
                note_no=None,
                content_type="glossary",
                unit=None,
                text=f"{e.term}: {e.definition}",
                fact_ids=[],
                bbox=[float(v) for v in e.bbox],
            )
        )
    return out

"""Glossary entries (spec §5.8): two-column tables of PDF page 194 plus hand-written extra synonyms."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz

from ircb.ingestion.tables import extract_tables

BBox = tuple[float, float, float, float]
GLOSSARY_PDF_PAGE = 194


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    definition: str
    printed_page: int
    bbox: BBox


def _union(a: BBox, b: BBox) -> BBox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def parse_glossary(doc: fitz.Document, pdf_page: int = GLOSSARY_PDF_PAGE) -> list[GlossaryEntry]:
    entries: list[GlossaryEntry] = []
    for table in extract_tables(doc, pdf_page):
        printed = table.printed_pages[0]
        for row in table.rows:
            term = " ".join(row.label.split())
            definition = " ".join(" ".join(c.raw for c in row.cells).split())
            boxes = [c.bbox for c in row.cells]
            if not term:
                # continuation row: the term cell is empty, the text extends the previous definition
                if entries and definition:
                    prev = entries[-1]
                    box = prev.bbox
                    for b in boxes:
                        box = _union(box, b)
                    entries[-1] = GlossaryEntry(
                        prev.term, f"{prev.definition} {definition}", prev.printed_page, box
                    )
                continue
            # the term cell sits left of the definition cell, on the same rows
            box = table.bbox
            if boxes:
                box = (
                    table.bbox[0],
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                )
            entries.append(GlossaryEntry(term, definition, printed, box))
    return entries


def load_glossary_extra(path: Path) -> dict[str, list[str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(k): [str(v) for v in vals] for k, vals in data.items()}

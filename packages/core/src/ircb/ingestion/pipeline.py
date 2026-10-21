"""Staged ingestion pipeline and build quality gates (spec §4.4).

extract   -> ``<out>/build/{pages,tables,kpi,qa,glossary}.jsonl`` + ``build/extract.json`` (PyMuPDF only)
normalize -> ``chunks.jsonl``, ``facts.jsonl``, ``glossary.json``, ``page_map.json``, ``ingest_report.json``
embed     -> ``vectors.parquet`` (dense via the cached ``Embedder``, BM25 sparse via ``tokenize``)

``build_index`` runs the three stages, applies the gates between normalize and embed (so a failing
build never pays for embedding) and writes ``manifest.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import pymupdf as fitz

from ircb.domain.models import Chunk, Fact, PageInfo
from ircb.ingestion.chunking import (
    chunks_from_glossary,
    chunks_from_kpi,
    chunks_from_prose,
    chunks_from_table,
)
from ircb.ingestion.facts import DOC_ID, fact_embed_text, facts_from_kpi, facts_from_table
from ircb.ingestion.glossary import GLOSSARY_PDF_PAGE, GlossaryEntry, load_glossary_extra, parse_glossary
from ircb.ingestion.images import classify_images
from ircb.ingestion.kpi import KpiTile, parse_kpi_tiles
from ircb.ingestion.prose import ProseBlock, extract_prose
from ircb.ingestion.spread import HalfPage, split_halves, verify_page_map
from ircb.ingestion.table_qa import MIN_RATIO, qa_tables
from ircb.ingestion.tables import Cell, ExtractedTable, TableRow, chapter_default_unit
from ircb.ingestion.units import unit_of
from ircb.retrieval.embed import Embedder, LiteLLMEmbedBackend
from ircb.retrieval.sparse_bm25 import encode_doc
from ircb.retrieval.tokenize_vi import TOKENIZER_VERSION, tokenize
from ircb.settings import Settings
from ircb.storage.artefacts import (
    CHUNKS,
    FACTS,
    GLOSSARY,
    MANIFEST,
    PAGE_MAP,
    REPORT,
    VECTORS,
    Manifest,
    VectorRecord,
    read_chunks,
    read_facts,
    read_json,
    read_jsonl,
    read_manifest,
    read_report,
    write_chunks,
    write_facts,
    write_glossary,
    write_json,
    write_jsonl,
    write_manifest,
    write_page_map,
    write_report,
    write_vectors,
)

Half = Literal["L", "R", "S"]
BBox = tuple[float, float, float, float]

GLOSSARY_EXTRA = Path(__file__).resolve().parents[5] / "config" / "glossary_extra.json"
BUILD = "build"
STAGING = ".tmp"
# final artefacts moved from the staging dir into out_dir; the manifest goes last
_FINAL = (CHUNKS, FACTS, GLOSSARY, PAGE_MAP, VECTORS, REPORT)
_YEAR = re.compile(r"(?<![\d.,])(?:19|20)\d{2}(?![\d])")


class GateError(Exception):
    """A build quality gate failed (spec §4.4): the index must not be shipped."""


# ---------------------------------------------------------------- gates


def check_gates(report: dict[str, Any]) -> list[str]:
    """Warnings of a build report; raises ``GateError`` listing every failing gate."""
    fails: list[str] = []
    if report.get("page_map_mismatches", 0):
        fails.append(f"page map mismatches: {report['page_map_mismatches']}")
    if report.get("facts_missing_unit", 0):
        fails.append(f"facts missing unit: {report['facts_missing_unit']}")
    if report.get("facts_missing_pages", 0):
        fails.append(f"facts missing printed_pages: {report['facts_missing_pages']}")
    kpi = report.get("kpi_golden_failed", [])
    if kpi:
        fails.append("kpi golden failed: " + "; ".join(map(str, kpi)))
    if fails:
        raise GateError(" | ".join(fails))
    return [f"coverage<{MIN_RATIO}: {p}{h}={r:.2f}" for p, h, r in report.get("low_halves", [])]


def _by_label(tiles: list[KpiTile], needle: str) -> KpiTile | None:
    hits = [t for t in tiles if needle.lower() in t.label.lower()]
    return hits[0] if len(hits) == 1 else None


def kpi_golden_check(doc: fitz.Document) -> list[str]:
    """Task 8 golden assertions for the KPI tiles of printed p.5 and p.59; empty when all hold."""
    by_printed = {h.printed_page: h for h in split_halves(doc)}
    fails: list[str] = []

    def tiles(printed: int) -> list[KpiTile]:
        h = by_printed[printed]
        return parse_kpi_tiles(doc[h.pdf_page - 1], h)

    def need(printed: int, ts: list[KpiTile], label: str, value: str, unit: str | None = None,
             change: str | None = None, direction: str | None = None) -> None:  # fmt: skip
        t = _by_label(ts, label)
        if t is None:
            fails.append(f"p{printed}: no single tile {label!r}")
            return
        if t.value_raw != value:
            fails.append(f"p{printed}: {label} value {t.value_raw!r} != {value!r}")
        if unit is not None and t.unit != unit:
            fails.append(f"p{printed}: {label} unit {t.unit!r} != {unit!r}")
        if change is not None and change not in (t.change_raw or ""):
            fails.append(f"p{printed}: {label} change {t.change_raw!r} lacks {change!r}")
        if direction is not None and t.direction != direction:
            fails.append(f"p{printed}: {label} direction {t.direction!r} != {direction!r}")

    p5 = tiles(5)
    if len(p5) != 12:
        fails.append(f"p5: {len(p5)} tiles, expected 12")
    need(5, p5, "Tổng tài sản", "1.192", unit="nghìn tỷ đồng")
    need(5, p5, "CASA", "40,4")
    need(5, p5, "nợ xấu", "1,13")
    need(5, p5, "Tổng thu nhập hoạt động", "53,4", change="16,5%")
    p59 = tiles(59)
    if len(p59) != 4:
        fails.append(f"p59: {len(p59)} tiles, expected 4")
    need(59, p59, "Dư nợ vay", "328,1", unit="nghìn tỷ đồng", change="26,9%", direction="up")
    return fails


def assert_unique_ids(chunks: Sequence[Chunk], facts: Sequence[Fact]) -> None:
    for name, ids in (("chunk_id", [c.chunk_id for c in chunks]), ("fact_id", [f.fact_id for f in facts])):
        dup = sorted(k for k, n in Counter(ids).items() if n > 1)
        if dup:
            raise GateError(f"duplicate {name}: {dup[:10]}")


# ---------------------------------------------------------------- helpers


def years_in_text(text: str) -> set[str]:
    """Four-digit years (19xx/20xx) standing alone, not inside a larger number."""
    return set(_YEAR.findall(text))


def compute_index_version(pdf_sha256: str, embed_model: str, dimensions: int, git_hash: str) -> str:
    raw = pdf_sha256 + TOKENIZER_VERSION + embed_model + str(dimensions) + git_hash
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def git_short_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent,
        )
    except (OSError, subprocess.CalledProcessError):
        return "nogit"
    return out.stdout.strip() or "nogit"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _bbox(v: Sequence[float]) -> BBox:
    return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))


def _table_from(d: dict[str, Any]) -> ExtractedTable:
    rows = [
        TableRow(
            r["label"],
            r["row_level"],
            r["parent_label"],
            r["is_total"],
            r["note_ref"],
            [Cell(c["col_path"], c["raw"], _bbox(c["bbox"])) for c in r["cells"]],
        )
        for r in d["rows"]
    ]
    return ExtractedTable(**{**d, "bbox": _bbox(d["bbox"]), "rows": rows})


def _printed(pdf_page: int, half: str) -> int:
    return pdf_page if half == "S" else 2 * pdf_page - (2 if half == "L" else 1)


def table_halves(tables: Sequence[dict[str, Any]]) -> set[tuple[int, str]]:
    """(pdf_page, half) holding at least one extracted table; a gutter table counts for L and R."""
    out: set[tuple[int, str]] = set()
    for t in tables:
        halves = ("L", "R") if t["half"] == "G" else (t["half"],)
        out |= {(int(t["pdf_page"]), h) for h in halves}
    return out


def low_halves(qa: Sequence[dict[str, Any]], with_tables: set[tuple[int, str]]) -> list[list[Any]]:
    """QA halves below ``MIN_RATIO`` that hold a table or belong to the FS chapter (default unit set).

    Narrative halves without tables carry their numbers in prose/KPI tiles; their table coverage is
    meaningless, so they never warn.
    """
    out: list[list[Any]] = []
    for q in qa:
        key = (int(q["pdf_page"]), str(q["half"]))
        if q["ratio"] >= MIN_RATIO:
            continue
        if key in with_tables or chapter_default_unit(_printed(*key)) is not None:
            out.append([key[0], key[1], round(q["ratio"], 4)])
    return out


def _build(out_dir: Path) -> Path:
    return out_dir / BUILD


# ---------------------------------------------------------------- stage 1: extract


def run_extract(pdf: Path, out_dir: Path) -> None:
    """Parse the PDF into intermediate JSONL under ``<out_dir>/build/``."""
    build = _build(out_dir)
    doc = fitz.open(pdf)  # type: ignore[no-untyped-call]
    try:
        halves = split_halves(doc)
        by_pdf: dict[int, list[HalfPage]] = {}
        for h in halves:
            by_pdf.setdefault(h.pdf_page, []).append(h)
        mismatches = verify_page_map(doc)
        pages: list[dict[str, Any]] = []
        tables_out: list[dict[str, Any]] = []
        kpi_out: list[dict[str, Any]] = []
        qa_out: list[dict[str, Any]] = []
        years: set[str] = set()
        glossary_tables = 0
        for pdf_page in range(1, doc.page_count + 1):
            page = doc[pdf_page - 1]
            years |= years_in_text(str(page.get_text()))  # type: ignore[no-untyped-call]
            tables, qa = qa_tables(doc, pdf_page)
            qa_out += [asdict(q) for q in qa]
            if pdf_page == GLOSSARY_PDF_PAGE:
                glossary_tables = len(tables)  # glossary rows become glossary chunks, not tables
            else:
                tables_out += [asdict(t) for t in tables]
            table_boxes = [t.bbox for t in tables]
            for h in by_pdf[pdf_page]:
                tiles = parse_kpi_tiles(page, h)
                kpi_out += [
                    {"pdf_page": pdf_page, "half": h.half, "index": i, "tile": asdict(t)}
                    for i, t in enumerate(tiles, start=1)
                ]
                prose = extract_prose(page, h, exclude_bboxes=[t.bbox for t in tiles] + table_boxes)
                pages.append(
                    {
                        "pdf_page": h.pdf_page,
                        "half": h.half,
                        "printed_page": h.printed_page,
                        "chapter": h.chapter,
                        "is_divider": h.is_divider,
                        "prose": [asdict(b) for b in prose],
                    }
                )
        glossary = [asdict(e) for e in parse_glossary(doc)]
        images = [
            {"xref": i.xref, "pdf_page": i.pdf_page, "note": i.note}
            for i in classify_images(doc)
            if i.label == "informative"
        ]
        meta = {
            "pdf_sha256": _sha256_file(pdf),
            "pdf_pages": doc.page_count,
            "page_map_mismatches": [
                f"PDF p.{m.pdf_page} found {m.found}, expected {m.expected}" for m in mismatches
            ],
            "periods_seen": sorted(years),
            "kpi_golden_failed": kpi_golden_check(doc),
            "informative_images_pending_vlm": images,
            "glossary_page_tables": glossary_tables,
        }
    finally:
        doc.close()  # type: ignore[no-untyped-call]
    write_jsonl(build / "pages.jsonl", pages)
    write_jsonl(build / "tables.jsonl", tables_out)
    write_jsonl(build / "kpi.jsonl", kpi_out)
    write_jsonl(build / "qa.jsonl", qa_out)
    write_jsonl(build / "glossary.jsonl", glossary)
    write_json(build / "extract.json", meta)


# ---------------------------------------------------------------- stage 2: normalize


def run_normalize(out_dir: Path) -> None:
    """Turn ``build/`` into chunks, facts, glossary, page map and the ingest report."""
    build = _build(out_dir)
    meta: dict[str, Any] = read_json(build / "extract.json")
    pages = read_jsonl(build / "pages.jsonl")
    chapter_of: dict[tuple[int, str], str | None] = {(p["pdf_page"], p["half"]): p["chapter"] for p in pages}

    chunks: list[Chunk] = []
    facts: list[Fact] = []
    for p in pages:
        blocks = [
            ProseBlock(b["heading"], b["text"], _bbox(b["bbox"]), b["printed_page"]) for b in p["prose"]
        ]
        chunks += chunks_from_prose(
            blocks, p["pdf_page"], p["half"], p["chapter"], unit_of(p["printed_page"])
        )

    kpi_rows = read_jsonl(build / "kpi.jsonl")
    groups: dict[tuple[int, str], list[KpiTile]] = {}
    for r in kpi_rows:
        tile = KpiTile(**{**r["tile"], "bbox": _bbox(r["tile"]["bbox"])})
        groups.setdefault((r["pdf_page"], r["half"]), []).append(tile)
    for (pdf_page, half), tiles in groups.items():
        chapter = chapter_of.get((pdf_page, half))
        h = cast(Half, half)
        chunks += chunks_from_kpi(tiles, pdf_page, h, chapter)
        # same 1-based tile order as chunks_from_kpi, so the chunk's fact_ids resolve
        for i, tile in enumerate(tiles, start=1):
            facts += facts_from_kpi(tile, pdf_page, h, i, chapter)

    tables_without_unit = 0
    table_rows = read_jsonl(build / "tables.jsonl")
    tables = [_table_from(d) for d in table_rows]
    for t in tables:
        chapter = chapter_of.get((t.pdf_page, "L" if t.half == "G" else t.half))
        # a gutter-spanning table ("G") covers the whole spread; Chunk.half has no "G" -> "S"
        division = unit_of(t.printed_pages[0])
        chunks += chunks_from_table(replace(t, half="S") if t.half == "G" else t, chapter, division)
        if t.unit is None:
            tables_without_unit += 1  # chunks only, no facts
            continue
        facts += facts_from_table(t, chapter)

    entries = [GlossaryEntry(**{**e, "bbox": _bbox(e["bbox"])}) for e in read_jsonl(build / "glossary.jsonl")]
    by_half: dict[str, list[GlossaryEntry]] = {}
    for e in entries:
        half = "L" if e.printed_page == 2 * GLOSSARY_PDF_PAGE - 2 else "R"
        by_half.setdefault(half, []).append(e)
    for half, es in sorted(by_half.items()):
        chunks += chunks_from_glossary(
            es, GLOSSARY_PDF_PAGE, cast(Half, half), chapter_of.get((GLOSSARY_PDF_PAGE, half))
        )

    assert_unique_ids(chunks, facts)

    page_map = [
        PageInfo(
            pdf_page=p["pdf_page"],
            half=p["half"],
            printed_page=p["printed_page"],
            chapter=p["chapter"],
            is_divider=p["is_divider"],
        )
        for p in pages
    ]
    extra = load_glossary_extra(GLOSSARY_EXTRA) if GLOSSARY_EXTRA.exists() else {}
    write_chunks(out_dir, chunks)
    write_facts(out_dir, facts)
    write_page_map(out_dir, page_map)
    write_glossary(out_dir, {"entries": [asdict(e) for e in entries], "extra": extra})

    qa = read_jsonl(build / "qa.jsonl")
    write_report(
        out_dir,
        {
            "doc_id": DOC_ID,
            "pdf_sha256": meta["pdf_sha256"],
            "n_chunks": len(chunks),
            "n_facts": len(facts),
            "content_types": dict(sorted(Counter(c.content_type for c in chunks).items())),
            "fact_sources": dict(sorted(Counter(f.source for f in facts).items())),
            "n_tables": len(tables),
            "tables_without_unit": tables_without_unit,
            "glossary_page_tables": meta["glossary_page_tables"],
            "n_kpi_tiles": len(kpi_rows),
            "n_glossary_entries": len(entries),
            "page_map_mismatches": len(meta["page_map_mismatches"]),
            "page_map_mismatch_detail": meta["page_map_mismatches"],
            "facts_missing_unit": sum(1 for f in facts if not f.unit),
            "facts_missing_pages": sum(1 for f in facts if not f.printed_pages),
            "kpi_golden_failed": meta["kpi_golden_failed"],
            "low_halves": low_halves(qa, table_halves(table_rows)),
            "table_qa": qa,
            "informative_images_pending_vlm": meta["informative_images_pending_vlm"],
            "periods_seen": meta["periods_seen"],
        },
    )


# ---------------------------------------------------------------- stage 3: embed


def _sparse(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    toks = [tokenize(t) for t in texts]
    avg = sum(map(len, toks)) / len(toks) if toks else 0.0
    out = []
    for tk in toks:
        sv = encode_doc(tk, avg)
        out.append((sv.indices, sv.values))
    return out


def run_embed(out_dir: Path, embedder: Embedder) -> None:
    """Dense + BM25 vectors of every chunk (``chunk.text``) and fact (``fact_embed_text``)."""
    chunks = read_chunks(out_dir)
    facts = [Fact.model_validate(f) for f in read_facts(out_dir)]
    groups: list[tuple[Literal["chunk", "fact"], list[str], list[str]]] = [
        ("chunk", [c["chunk_id"] for c in chunks], [c["text"] for c in chunks]),
        ("fact", [f.fact_id for f in facts], [fact_embed_text(f) for f in facts]),
    ]
    dense = embedder.embed([t for _k, _ids, texts in groups for t in texts])
    bad = {len(v) for v in dense} - {embedder.dimensions}
    if bad:
        raise ValueError(f"embedding dimension {sorted(bad)} != configured {embedder.dimensions}")
    records: list[VectorRecord] = []
    pos = 0
    for kind, ids, texts in groups:
        for id_, (idx, vals) in zip(ids, _sparse(texts), strict=True):
            records.append(VectorRecord(id_, kind, dense[pos], idx, vals))
            pos += 1
    write_vectors(out_dir, records)


# ---------------------------------------------------------------- build


def _provider(model: str) -> str:
    return model.split("/", 1)[0] if "/" in model else "openai"


def build_index(
    pdf_path: Path, out_dir: Path, settings: Settings, embedder: Embedder | None = None
) -> Manifest:
    pdf_path, out_dir = Path(pdf_path), Path(out_dir)
    if embedder is None:
        embedder = Embedder(
            LiteLLMEmbedBackend(settings),
            settings.embed_cache_dir,
            settings.embed_model,
            settings.embed_dimensions,
        )
    stage = out_dir / STAGING
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    run_extract(pdf_path, stage)
    timings["extract"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    run_normalize(stage)
    timings["normalize"] = round(time.perf_counter() - t0, 2)
    report = read_report(stage)
    try:
        report["warnings"] = check_gates(report)
    except GateError as exc:
        # out_dir is untouched; the failed report stays in the staging dir for inspection
        report["gate_error"] = str(exc)
        report["timings_s"] = timings
        write_report(stage, report)
        raise
    t0 = time.perf_counter()
    run_embed(stage, embedder)
    timings["embed"] = round(time.perf_counter() - t0, 2)
    report["timings_s"] = timings
    write_report(stage, report)
    manifest = Manifest(
        index_version=compute_index_version(
            report["pdf_sha256"], embedder.model, embedder.dimensions, git_short_hash()
        ),
        doc_id=DOC_ID,
        pdf_sha256=report["pdf_sha256"],
        embed_provider=_provider(embedder.model),
        embed_model=embedder.model,
        embed_dimensions=embedder.dimensions,
        tokenizer_version=TOKENIZER_VERSION,
        periods_seen=report["periods_seen"],
        n_chunks=report["n_chunks"],
        n_facts=report["n_facts"],
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    write_manifest(stage, manifest)
    _promote(stage, out_dir)
    return manifest


def reembed_index(out_dir: Path, embedder: Embedder) -> Manifest:
    """Re-run only the embed stage over a shipped index and update the manifest's embed fields."""
    out_dir = Path(out_dir)
    old = read_manifest(out_dir)
    run_embed(out_dir, embedder)
    new = old.model_copy(
        update={
            "embed_provider": _provider(embedder.model),
            "embed_model": embedder.model,
            "embed_dimensions": embedder.dimensions,
            "index_version": compute_index_version(
                old.pdf_sha256, embedder.model, embedder.dimensions, git_short_hash()
            ),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    write_manifest(out_dir, new)
    return new


def _promote(stage: Path, out_dir: Path) -> None:
    """Move a complete staged build into ``out_dir``. The old manifest is removed first and the new
    one moved last, so a manifest on disk always describes the files next to it."""
    missing = [n for n in (*_FINAL, MANIFEST) if not (stage / n).exists()]
    if missing:
        raise FileNotFoundError(f"incomplete staged build, missing {missing}")
    (out_dir / MANIFEST).unlink(missing_ok=True)
    for name in _FINAL:
        (stage / name).replace(out_dir / name)
    if (stage / BUILD).exists():
        shutil.rmtree(out_dir / BUILD, ignore_errors=True)
        (stage / BUILD).replace(out_dir / BUILD)
    (stage / MANIFEST).replace(out_dir / MANIFEST)
    shutil.rmtree(stage)


def _settings() -> Settings:
    try:
        return Settings()  # pydantic-settings reads LLM_MODEL from the env
    except ValueError:  # LLM_MODEL unset: ingestion never calls the LLM
        return Settings(llm_model="unused")


def main(argv: Sequence[str] | None = None, embedder: Embedder | None = None) -> int:
    """``python -m ircb.ingestion.pipeline <pdf> --out <dir>``; ``embedder`` is a test seam."""
    ap = argparse.ArgumentParser(prog="python -m ircb.ingestion.pipeline", description=__doc__)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, default=Path("index"))
    args = ap.parse_args(argv)
    m = build_index(args.pdf, args.out, _settings(), embedder)
    print(f"index {m.index_version}: {m.n_chunks} chunks, {m.n_facts} facts -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

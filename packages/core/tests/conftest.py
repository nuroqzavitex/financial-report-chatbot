from collections.abc import Iterator
from pathlib import Path

import pymupdf as fitz
import pytest
from ircb.ingestion.spread import HalfPage, split_halves

PDF_NAME = "techcombank-bao-cao-thuong-nien-2025-vie-update.pdf"
PDF_FILE = Path(__file__).resolve().parents[3] / "data" / PDF_NAME


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "requires_pdf: test needs the report PDF under data/")


@pytest.fixture(scope="session")
def pdf_path() -> Path:
    if not PDF_FILE.exists():
        pytest.skip(f"PDF not found: {PDF_FILE}")
    return PDF_FILE


@pytest.fixture(scope="session")
def doc(pdf_path: Path) -> Iterator[fitz.Document]:
    d = fitz.open(pdf_path)
    yield d
    d.close()


_HALF_CACHE: dict[int, dict[int, HalfPage]] = {}


def half_obj(doc: fitz.Document, printed: int) -> tuple[fitz.Page, HalfPage]:
    """Page and ``HalfPage`` holding printed page ``printed`` (split cached per doc)."""
    by_printed = _HALF_CACHE.get(id(doc))
    if by_printed is None:
        by_printed = {h.printed_page: h for h in split_halves(doc)}
        _HALF_CACHE[id(doc)] = by_printed
    h = by_printed[printed]
    return doc[h.pdf_page - 1], h


def half(doc: fitz.Document, printed: int) -> tuple[fitz.Page, fitz.Rect]:
    page, h = half_obj(doc, printed)
    return page, h.clip

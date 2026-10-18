"""Render a printed half page as PNG with the evidence highlighted."""

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

import pymupdf as fitz

from ircb.domain.models import PageInfo

_EVIDENCE_CHARS = 120
_FILL = (1.0, 0.92, 0.0)
_BORDER = (1.0, 0.55, 0.0)


class PageNotFound(LookupError):
    """The printed page is not in the page map."""


class PdfMissing(FileNotFoundError):
    """The source PDF is not available on this host."""


class PageRenderer:
    def __init__(self, pdf_path: Path, page_map: list[PageInfo], cache_dir: Path, zoom: float = 2.0) -> None:
        self._pdf_path = pdf_path
        self._by_printed = {p.printed_page: p for p in page_map}
        self._cache_dir = cache_dir
        self._zoom = zoom
        # PyMuPDF is not thread-safe, and on Windows a concurrent read_bytes of a cache file being
        # os.replace'd raises PermissionError: one lock covers cache check, render and write.
        self._lock = threading.Lock()

    @property
    def pdf_available(self) -> bool:
        return self._pdf_path.is_file()

    def has_page(self, printed: int) -> bool:
        return printed in self._by_printed

    def _key(self, printed: int, rect: list[float] | None, evidence: str | None) -> str:
        raw = json.dumps([printed, rect, evidence, self._zoom], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def render(self, printed: int, rect: list[float] | None = None, evidence: str | None = None) -> bytes:
        info = self._by_printed.get(printed)
        if info is None:
            raise PageNotFound(printed)
        if not self.pdf_available:
            raise PdfMissing(str(self._pdf_path))
        cached = self._cache_dir / f"{self._key(printed, rect, evidence)}.png"
        with self._lock:
            if cached.is_file():
                return cached.read_bytes()
            png = self._render(info, rect, evidence)
            self._write(cached, png)
            return png

    def _render(self, info: PageInfo, rect: list[float] | None, evidence: str | None) -> bytes:
        doc = fitz.open(self._pdf_path)  # type: ignore[no-untyped-call]
        try:
            page = doc[info.pdf_page - 1]
            w, h = page.rect.width, page.rect.height
            if info.half == "L":
                clip = fitz.Rect(0, 0, w / 2, h)  # type: ignore[no-untyped-call]
            elif info.half == "R":
                clip = fitz.Rect(w / 2, 0, w, h)  # type: ignore[no-untyped-call]
            else:
                clip = fitz.Rect(0, 0, w, h)  # type: ignore[no-untyped-call]

            hits: list[fitz.Rect] = []
            if evidence:
                needle = " ".join(evidence.split())[:_EVIDENCE_CHARS]
                if needle:
                    hits = list(page.search_for(needle, clip=clip))
            if not hits and rect is not None and len(rect) == 4:
                inter = fitz.Rect(*rect) & clip  # type: ignore[no-untyped-call]
                if not inter.is_empty:
                    hits = [inter]
            for r in hits:
                page.draw_rect(r, color=_BORDER, fill=_FILL, fill_opacity=0.35, width=1.5)
            pix = page.get_pixmap(matrix=fitz.Matrix(self._zoom, self._zoom), clip=clip)  # type: ignore[no-untyped-call]
            png: bytes = pix.tobytes("png")  # type: ignore[no-untyped-call]
        finally:
            doc.close()  # type: ignore[no-untyped-call]
        return png

    def _write(self, cached: Path, png: bytes) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(png)
            os.replace(tmp, cached)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

"""Render a printed half page as PNG with the evidence highlighted."""

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

import numpy as np
import pymupdf as fitz

from ircb.domain.models import PageInfo

_EVIDENCE_CHARS = 120
_NGRAM = 6  # words per run when the whole quote is not on this page
_EDGE_PUNCT = ",.;:!?()\"'“”"
_STYLE = "red-text-3"  # part of the cache key: a new highlight style never serves old PNGs
_RED = np.array([200.0, 0.0, 0.0])
_GREY_SPREAD = 60  # max - min channel of a black/grey text pixel; coloured ink is left as it is


def _evidence_hits(page: fitz.Page, clip: fitz.Rect, evidence: str) -> list[fitz.Rect]:
    """Where the evidence is on the page: the whole quote, else each run of ``_NGRAM`` consecutive
    words of it that the page has. A claim citing several pages quotes one chunk only, so on its other
    pages the same facts are worded a little differently; the runs still find them."""
    words = evidence.split()
    whole = " ".join(words)[:_EVIDENCE_CHARS]
    if not whole:
        return []
    hits = list(page.search_for(whole, clip=clip))
    if hits or len(words) <= _NGRAM:
        return hits
    words = [w.strip(_EDGE_PUNCT) for w in words]  # "định," in the quote is "định." on this page
    words = [w for w in words if w]
    seen: set[tuple[float, ...]] = set()
    for i in range(len(words) - _NGRAM + 1):
        for r in page.search_for(" ".join(words[i : i + _NGRAM]), clip=clip):
            key = tuple(round(v, 1) for v in r)
            if key not in seen:
                seen.add(key)
                hits.append(r)
    return hits


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
        raw = json.dumps([printed, rect, evidence, self._zoom, _STYLE], ensure_ascii=False)
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

            hits = _evidence_hits(page, clip, evidence) if evidence else []
            if not hits and rect is not None and len(rect) == 4:
                inter = fitz.Rect(*rect) & clip  # type: ignore[no-untyped-call]
                if not inter.is_empty:
                    hits = [inter]
            pix = page.get_pixmap(matrix=fitz.Matrix(self._zoom, self._zoom), clip=clip, alpha=False)  # type: ignore[no-untyped-call]
            if hits:
                pix = self._redden(pix, clip, hits)
            png: bytes = pix.tobytes("png")  # type: ignore[no-untyped-call]
        finally:
            doc.close()  # type: ignore[no-untyped-call]
        return png

    def _redden(self, pix: fitz.Pixmap, clip: fitz.Rect, hits: list[fitz.Rect]) -> fitz.Pixmap:
        """Black/grey ink inside the hits turns red, keeping its darkness (anti-aliased edges stay
        smooth); white paper and coloured ink are unchanged. No box is drawn."""
        img = (
            np.frombuffer(pix.samples, dtype=np.uint8)
            .reshape(pix.height, pix.width, pix.n)
            .astype(np.float64)
        )
        rgb = img[..., :3]
        for r in hits:
            x0 = max(int((r.x0 - clip.x0) * self._zoom), 0)
            y0 = max(int((r.y0 - clip.y0) * self._zoom), 0)
            x1 = min(int((r.x1 - clip.x0) * self._zoom) + 1, pix.width)
            y1 = min(int((r.y1 - clip.y0) * self._zoom) + 1, pix.height)
            if x0 >= x1 or y0 >= y1:
                continue
            box = rgb[y0:y1, x0:x1]
            grey = (box.max(axis=2) - box.min(axis=2)) <= _GREY_SPREAD
            ink = (255.0 - box.mean(axis=2)) / 255.0  # 0 paper .. 1 black
            red = 255.0 * (1.0 - ink[..., None]) + _RED * ink[..., None]
            box[grey] = red[grey]
        out = np.clip(img, 0, 255).astype(np.uint8)
        return fitz.Pixmap(fitz.csRGB, pix.width, pix.height, out.tobytes(), False)  # type: ignore[no-untyped-call]

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

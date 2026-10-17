"""Image triage (spec §5.14): rules mark decorative images, the rest need a manual label.

Rules: placed more than twice in the document, covering over 60% of a page, or under 1% of every
placement -> ``decorative``. Remaining images take their label from ``config/images.json`` or are ``review``.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pymupdf as fitz

Label = Literal["decorative", "informative", "review"]

MAX_PLACEMENTS = 2
FULL_BLEED = 0.60
ICON = 0.01
DEFAULT_LABELS = Path(__file__).resolve().parents[5] / "config" / "images.json"


@dataclass(frozen=True)
class ImageInfo:
    xref: int
    pdf_page: int
    label: Label
    placements: int = 1
    max_cover: float = 0.0
    note: str = ""


def load_labels(path: Path | None) -> dict[int, dict[str, str]]:
    if path is None or not Path(path).exists():
        return {}
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(r["xref"]): r for r in rows}


def classify_images(doc: fitz.Document, labels_path: Path | None = DEFAULT_LABELS) -> list[ImageInfo]:
    first_page: dict[int, int] = {}
    placements: dict[int, int] = defaultdict(int)
    cover: dict[int, float] = defaultdict(float)
    for i in range(doc.page_count):
        page = doc[i]
        area = float(page.rect.width * page.rect.height)
        for img in page.get_images(full=True):  # type: ignore[no-untyped-call]
            xref = int(img[0])
            rects = page.get_image_rects(xref)
            first_page.setdefault(xref, i + 1)
            for r in rects:
                placements[xref] += 1
                cover[xref] = max(cover[xref], float(r.width * r.height) / area)
    labels = load_labels(labels_path)
    out: list[ImageInfo] = []
    for xref in sorted(first_page):
        n, c = placements[xref], cover[xref]
        note = ""
        label: Label
        if n > MAX_PLACEMENTS or c > FULL_BLEED or c < ICON:
            label = "decorative"
        elif xref in labels and labels[xref].get("label") in ("decorative", "informative"):
            label = labels[xref]["label"]  # type: ignore[assignment]
            note = labels[xref].get("note", "")
        else:
            label = "review"
        out.append(ImageInfo(xref, first_page[xref], label, n, c, note))
    return out


def contact_sheet(
    doc: fitz.Document, infos: list[ImageInfo], out_dir: Path, per_sheet: int = 12
) -> list[Path]:
    """Render labelled thumbnails of ``infos`` into PNG sheets under ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cols, cell_w, cell_h = 4, 220.0, 200.0
    paths: list[Path] = []
    for s in range(0, len(infos), per_sheet):
        chunk = infos[s : s + per_sheet]
        rows = (len(chunk) + cols - 1) // cols
        sheet = fitz.open()  # type: ignore[no-untyped-call]
        page = sheet.new_page(width=cols * cell_w, height=rows * cell_h)
        for k, info in enumerate(chunk):
            x, y = (k % cols) * cell_w, (k // cols) * cell_h
            box = fitz.Rect(x + 4, y + 18, x + cell_w - 4, y + cell_h - 4)  # type: ignore[no-untyped-call]
            page.insert_text((x + 4, y + 12), f"xref {info.xref}  pdf p.{info.pdf_page}", fontsize=9)
            try:
                pix = fitz.Pixmap(doc, info.xref)  # type: ignore[no-untyped-call]
                if pix.alpha or pix.colorspace is None or pix.colorspace.n > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)  # type: ignore[no-untyped-call]
                page.insert_image(box, pixmap=pix)  # type: ignore[no-untyped-call]
            except (RuntimeError, ValueError):
                page.insert_text((x + 8, y + 60), "(cannot render)", fontsize=9)
        path = out_dir / f"contact_{s // per_sheet + 1:02d}.png"
        page.get_pixmap(dpi=110).save(path)  # type: ignore[no-untyped-call]
        paths.append(path)
        sheet.close()  # type: ignore[no-untyped-call]
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pdf", type=Path, default=Path("data") / "techcombank-bao-cao-thuong-nien-2025-vie-update.pdf"
    )
    ap.add_argument("--contact-sheet", type=Path, default=None)
    ap.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = ap.parse_args()
    doc = fitz.open(args.pdf)  # type: ignore[no-untyped-call]
    infos = classify_images(doc, args.labels)
    counts: dict[str, int] = defaultdict(int)
    for i in infos:
        counts[i.label] += 1
    print(dict(counts))
    if args.contact_sheet:
        review = [i for i in infos if i.label == "review"]
        for p in contact_sheet(doc, review, args.contact_sheet):
            print(p)


if __name__ == "__main__":
    main()

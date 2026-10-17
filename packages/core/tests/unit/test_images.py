import json
from pathlib import Path

import pymupdf as fitz
from ircb.ingestion.images import classify_images


def _png(color: tuple[int, int, int], size: int = 8) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size), False)  # type: ignore[no-untyped-call]
    pix.set_rect(pix.irect, color)  # type: ignore[no-untyped-call]
    return bytes(pix.tobytes("png"))  # type: ignore[no-untyped-call]


def _build(tmp: Path) -> tuple[fitz.Document, dict[str, int]]:
    d = fitz.open()
    for _ in range(4):
        d.new_page(width=1000, height=500)  # type: ignore[no-untyped-call]
    pages = [d[i] for i in range(4)]
    logo, labelled, unlabelled, full, icon = (_png((i * 40, 0, 0)) for i in range(5))
    r = fitz.Rect  # type: ignore[no-untyped-call]
    ids: dict[str, int] = {}
    for p in pages[:3]:  # same image placed 3 times (one per page)
        p.insert_image(r(10, 10, 300, 200), stream=logo)
    pages[0].insert_image(r(400, 10, 700, 250), stream=labelled)
    pages[1].insert_image(r(400, 10, 700, 250), stream=unlabelled)
    pages[2].insert_image(r(0, 0, 1000, 500), stream=full)
    pages[3].insert_image(r(10, 10, 30, 30), stream=icon)
    for i in range(4):
        for im in pages[i].get_images(full=True):
            ids[f"{i}:{im[0]}"] = im[0]
    path = tmp / "t.pdf"
    d.save(path)
    d.close()
    return fitz.open(path), ids


def test_images_rules(tmp_path: Path) -> None:
    doc, _ = _build(tmp_path)
    by_page: dict[int, list[int]] = {}
    for i in range(doc.page_count):
        by_page[i + 1] = [im[0] for im in doc[i].get_images(full=True)]
    logo = by_page[1][0]
    labelled = by_page[1][1]
    unlabelled = by_page[2][1]
    full = by_page[3][1]
    icon = by_page[4][0]
    labels = tmp_path / "images.json"
    labels.write_text(
        json.dumps([{"xref": labelled, "pdf_page": 1, "label": "informative", "note": "chart"}]),
        encoding="utf-8",
    )
    got = {i.xref: i for i in classify_images(doc, labels)}
    assert got[logo].label == "decorative" and got[logo].placements == 3  # repeated > 2 times
    assert got[full].label == "decorative"  # > 60% of the page
    assert got[icon].label == "decorative"  # < 1% of the page
    assert got[labelled].label == "informative" and got[labelled].note == "chart"
    assert got[unlabelled].label == "review"
    # without labels the previously labelled image falls back to review
    assert {i.xref: i for i in classify_images(doc, None)}[labelled].label == "review"

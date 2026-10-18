import struct
import threading
from pathlib import Path

import pymupdf as fitz
import pytest
from ircb.domain.models import PageInfo
from ircb.pages import PageNotFound, PageRenderer, PdfMissing
from ircb.storage import artefacts


def png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", png[16:24])
    return int(w), int(h)


def _text(page: fitz.Page, x: float, y: float, s: str) -> None:
    page.insert_text((x, y), s, fontsize=14)  # type: ignore[no-untyped-call]


@pytest.fixture
def page_map() -> list[PageInfo]:
    return [
        PageInfo(pdf_page=1, half="S", printed_page=1, chapter=None, is_divider=False),
        PageInfo(pdf_page=2, half="L", printed_page=2, chapter=None, is_divider=False),
        PageInfo(pdf_page=2, half="R", printed_page=3, chapter=None, is_divider=False),
    ]


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    d = fitz.open()  # type: ignore[no-untyped-call]
    p1 = d.new_page(width=300, height=400)  # type: ignore[no-untyped-call]
    _text(p1, 50, 100, "Cover")
    p2 = d.new_page(width=600, height=400)  # type: ignore[no-untyped-call]
    _text(p2, 50, 60, "Tong tai san 1.192")
    _text(p2, 350, 60, "Du no vay 328,1")
    path = tmp_path / "synthetic.pdf"
    d.save(path)  # type: ignore[no-untyped-call]
    d.close()
    return path


@pytest.fixture
def renderer(pdf: Path, page_map: list[PageInfo], tmp_path: Path) -> PageRenderer:
    return PageRenderer(pdf, page_map, tmp_path / "cache")


def test_half_page_dimensions(renderer: PageRenderer) -> None:
    assert png_size(renderer.render(3)) == (600, 800)
    assert png_size(renderer.render(1)) == (600, 800)


def test_evidence_highlight_changes_pixels_inside_clip(renderer: PageRenderer) -> None:
    plain, lit = renderer.render(2), renderer.render(2, evidence="Tong tai san 1.192")
    assert plain != lit


def test_rect_fallback_and_outside_rect_ignored(renderer: PageRenderer) -> None:
    assert renderer.render(2, rect=[40, 40, 200, 80]) != renderer.render(2)
    assert renderer.render(2, rect=[400, 40, 500, 80]) == renderer.render(2)


def test_cache_hit_writes_one_file(renderer: PageRenderer, tmp_path: Path) -> None:
    renderer.render(3, evidence="Du no vay")
    renderer.render(3, evidence="Du no vay")
    assert len(list((tmp_path / "cache").glob("*.png"))) == 1


def test_unknown_page_and_missing_pdf(tmp_path: Path, page_map: list[PageInfo]) -> None:
    r = PageRenderer(tmp_path / "missing.pdf", page_map, tmp_path / "c")
    assert not r.pdf_available and r.has_page(2) and not r.has_page(999)
    with pytest.raises(PageNotFound):
        r.render(999)
    with pytest.raises(PdfMissing):
        r.render(2)


@pytest.mark.requires_pdf
def test_real_p59_kpi_highlight(pdf_path: Path, tmp_path: Path) -> None:
    index = Path(__file__).resolve().parents[4] / "index"
    if not (index / "page_map.json").exists():
        pytest.skip("index/ missing")
    r = PageRenderer(pdf_path, artefacts.read_page_map(index), tmp_path)
    assert r.render(59, evidence="Dư nợ vay") != r.render(59)


def test_cache_write_is_atomic_and_matches_returned_bytes(renderer: PageRenderer, tmp_path: Path) -> None:
    png = renderer.render(3, evidence="Du no vay")
    files = list((tmp_path / "cache").iterdir())
    assert [f.suffix for f in files] == [".png"]
    assert files[0].read_bytes() == png


def test_concurrent_cold_renders_of_one_key_all_succeed(renderer: PageRenderer, tmp_path: Path) -> None:
    n = 12
    barrier = threading.Barrier(n)
    results: list[bytes] = []
    errors: list[BaseException] = []

    def work() -> None:
        barrier.wait()
        try:
            results.append(renderer.render(2, evidence="Tong tai san 1.192"))
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(results) == n and len(set(results)) == 1
    assert len(list((tmp_path / "cache").glob("*.png"))) == 1

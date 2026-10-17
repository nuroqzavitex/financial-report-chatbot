from typing import Any

import pymupdf as fitz
from ircb.ingestion.kpi import _arrow_from

PCT = (100.0, 100.0, 130.0, 110.0)  # % span; arrow must sit just left of x=100


def _tri(apex_up: bool, fill: tuple[float, float, float]) -> dict[str, Any]:
    p = lambda x, y: fitz.Point(x, y)  # noqa: E731
    pts = [p(90, 109), p(96, 109), p(93, 101)] if apex_up else [p(90, 101), p(96, 101), p(93, 109)]
    items = [("l", pts[0], pts[1]), ("l", pts[1], pts[2]), ("l", pts[2], pts[0])]
    return {"rect": fitz.Rect(90, 101, 96, 109), "items": items, "fill": fill, "color": None}


RED, GREEN = (0.9, 0.1, 0.1), (0.1, 0.6, 0.2)


def test_up_green_down_red() -> None:
    assert _arrow_from([_tri(True, GREEN)], PCT) == "up"
    assert _arrow_from([_tri(False, RED)], PCT) == "down"


def test_red_with_unknown_geometry_is_not_down() -> None:
    sq = {
        "rect": fitz.Rect(90, 101, 96, 109),
        "items": [("re", fitz.Rect(90, 101, 96, 109))],
        "fill": RED,
        "color": None,
    }
    # non-triangle red shape: no usable candidate
    assert _arrow_from([sq], PCT) == "unknown"
    # triangle whose geometry is ambiguous (all y distinct) but red: geometry result, not "down"
    amb = _tri(True, RED)
    amb["items"] = [
        ("l", fitz.Point(90, 101), fitz.Point(96, 105)),
        ("l", fitz.Point(96, 105), fitz.Point(93, 109)),
        ("l", fitz.Point(93, 109), fitz.Point(90, 101)),
    ]
    assert _arrow_from([amb], PCT) == "unknown"


def test_conflict_is_unknown() -> None:
    assert _arrow_from([_tri(True, RED)], PCT) == "unknown"


def test_printed_word_fallback_only_without_candidate() -> None:
    from ircb.ingestion.kpi import _decide_direction

    assert _decide_direction([], PCT, "Tăng") == "up"
    assert _decide_direction([], PCT, "Giảm") == "down"
    # candidate exists but conflicts -> stays unknown despite printed word
    assert _decide_direction([_tri(True, RED)], PCT, "Tăng") == "unknown"
    assert _decide_direction([_tri(False, RED)], PCT, "Tăng") == "down"

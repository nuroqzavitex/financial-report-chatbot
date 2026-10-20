import pymupdf as fitz
from ircb.ingestion.prose import extract_prose
from ircb.ingestion.spread import HalfPage

BODY, BIG = 9.0, 14.0


def _make(items: list[tuple[float, float, str, float, bool]]) -> tuple[fitz.Page, HalfPage]:
    """items: (x, y, text, fontsize, bold) on one 400x500 page; y is the text baseline."""
    d = fitz.open()
    d.new_page(width=400, height=500)
    page = d[0]
    for x, y, text, size, bold in items:
        page.insert_text((x, y), text, fontsize=size, fontname="hebo" if bold else "helv")
    clip = fitz.Rect(0, 0, 400, 500)
    return page, HalfPage(1, "S", 1, clip, None, False)


def _body(y: float, text: str) -> tuple[float, float, str, float, bool]:
    return (20, y, text, BODY, False)


def test_size_rule_heading_and_blocks() -> None:
    page, half = _make(
        [
            (20, 100, "Muc mot", BIG, False),
            _body(120, "doan mot dong mot"),
            _body(132, "doan mot dong hai"),
            (20, 160, "Muc hai", BIG, False),
            _body(180, "doan hai"),
        ]
    )
    blocks = extract_prose(page, half, [])
    assert [(b.heading, b.text) for b in blocks] == [
        ("Muc mot", "doan mot dong mot doan mot dong hai"),
        ("Muc hai", "doan hai"),
    ]
    assert all(b.printed_page == 1 for b in blocks)


def test_bold_line_is_heading_but_inline_bold_is_not() -> None:
    page, half = _make(
        [
            (20, 100, "Tieu de dam", BODY, True),
            _body(120, "noi dung mot"),
            _body(140, "cau co"),
            (60, 140, "chu dam", BODY, True),
            (110, 140, "giua dong", BODY, False),
        ]
    )
    blocks = extract_prose(page, half, [])
    assert blocks[0].heading == "Tieu de dam"
    assert len(blocks) == 1  # inline bold on a line with body text does not split the block


def test_numeric_spans_are_not_headings() -> None:
    page, half = _make(
        [
            (20, 100, "1.192", 30.0, True),
            (20, 140, "86%", 30.0, False),
            (20, 180, "TOP 1", 30.0, False),
            _body(200, "mo ta mot"),
            _body(212, "mo ta hai"),
            _body(224, "mo ta ba"),
        ]
    )
    blocks = extract_prose(page, half, [])
    assert len(blocks) == 1 and blocks[0].heading is None
    assert "1.192" in blocks[0].text and "86%" in blocks[0].text


def test_trailing_heading_without_body_is_kept() -> None:
    page, half = _make(
        [_body(100, "doan dau"), _body(112, "doan hai"), (20, 160, "Tieu de cuoi", BIG, False)]
    )
    blocks = extract_prose(page, half, [])
    assert [b.heading for b in blocks] == [None, "Tieu de cuoi"]
    assert blocks[1].text == "Tieu de cuoi"


def test_heading_directly_followed_by_heading_is_not_lost() -> None:
    page, half = _make(
        [
            _body(80, "doan dau"),
            _body(90, "doan hai"),
            (20, 120, "Tieu de", BIG, False),
            (20, 140, "phu", BIG, False),
            _body(160, "noi dung"),
        ]
    )
    blocks = extract_prose(page, half, [])
    assert [b.heading for b in blocks] == [None, "Tieu de phu"]


def test_exclude_bboxes_exclude_only_part_of_half() -> None:
    page, half = _make(
        [_body(100, "giu lai"), _body(112, "giu nua"), _body(300, "bo di"), _body(312, "bo nua")]
    )
    box = (0.0, 280.0, 400.0, 330.0)
    text = " ".join(b.text for b in extract_prose(page, half, [box]))
    assert "giu lai" in text and "giu nua" in text
    assert "bo di" not in text and "bo nua" not in text


def test_figure_joins_caption_above_in_its_column() -> None:
    page, half = _make(
        [
            _body(60, "doan mo dau"),
            _body(72, "doan mo dau hai"),
            (20, 110, "So du tien gui", BODY, False),
            (220, 110, "So khach moi", BODY, False),
            (24, 136, "24% N/N", 22.0, False),
            (224, 136, "65% N/N", 22.0, False),
        ]
    )
    blocks = extract_prose(page, half, [])
    assert len(blocks) == 1 and blocks[0].heading is None  # figures are not headings
    assert "So du tien gui: 24% N/N" in blocks[0].text
    assert "So khach moi: 65% N/N" in blocks[0].text
    assert blocks[0].text.count("24% N/N") == 1


def test_figure_joins_multiline_caption_below_and_unit_beside() -> None:
    page, half = _make(
        [
            (20, 100, "Tong quan", BIG, False),
            (20, 140, "1,5x", 22.0, False),
            _body(158, "khach hang moi"),
            _body(169, "so voi 2024"),
            (20, 220, "13,1", 22.0, False),
            (70, 214, "Trieu", BODY, False),
            _body(236, "hoi vien"),
        ]
    )
    blocks = extract_prose(page, half, [])
    assert [b.heading for b in blocks] == ["Tong quan"]
    assert "khach hang moi so voi 2024: 1,5x" in blocks[0].text
    assert "hoi vien: 13,1 Trieu" in blocks[0].text


def test_figure_next_to_a_paragraph_keeps_the_paragraph() -> None:
    lines = [_body(100 + 11 * i, f"dong van ban {i}") for i in range(5)]
    page, half = _make([*lines, (20, 176, "17%", 22.0, False)])
    text = " ".join(b.text for b in extract_prose(page, half, []))
    assert ":" not in text  # five contiguous lines are a paragraph, not a caption
    assert text.startswith("dong van ban 0") and "17%" in text


def test_numbered_heading_is_not_a_figure() -> None:
    page, half = _make([(20, 100, "4.21. Thue", BIG, False), _body(120, "noi dung")])
    assert [b.heading for b in extract_prose(page, half, [])] == ["4.21. Thue"]


def test_pull_quote_in_large_type_is_body_not_heading() -> None:
    quote = [
        (20, 140, "Nhung buoc tien nay dong vai tro then chot trong viec", 10.5, True),
        (20, 153, "cai thien trai nghiem khach hang va khang dinh vi the", 10.5, True),
        (20, 166, "cua ngan hang nhu mot doi tac chinh duoc uu tien.", 10.5, True),
    ]
    page, half = _make(
        [(20, 100, "Diem nhan", BIG, False), _body(120, "doan mot"), *quote, _body(186, "doan hai")]
    )
    blocks = extract_prose(page, half, [])
    assert [b.heading for b in blocks] == ["Diem nhan"]
    assert "then chot" in blocks[0].text and blocks[0].text.endswith("doan hai")

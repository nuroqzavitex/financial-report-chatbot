from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from ircb.domain.numbers_vn import find_numbers, format_vn, normalize_chars, parse_vn


@pytest.mark.parametrize(
    "raw,val,pct",
    [
        ("1.192", Decimal("1192"), False),
        ("53,4", Decimal("53.4"), False),
        ("1.192.344.137", Decimal("1192344137"), False),
        ("(415.884)", Decimal("-415884"), False),
        ("-", Decimal("0"), False),
        ("7100", Decimal("7100"), False),
        ("+18,36%", Decimal("18.36"), True),
        ("~3,0%", Decimal("3.0"), True),
        ("-2,5", Decimal("-2.5"), False),
    ],
)
def test_parse_vn(raw, val, pct):
    p = parse_vn(raw)
    assert p.value == val and p.is_percent == pct


def test_yoy_basis():
    p = parse_vn("18,2% N/N")
    assert p.basis == "YoY" and p.value == Decimal("18.2")


def test_approx():
    assert parse_vn("~3,0%").approx
    assert not parse_vn("3,0%").approx


@pytest.mark.parametrize("raw", ["abc", "", "1.19", "12,3,4"])
def test_parse_vn_invalid(raw):
    with pytest.raises(ValueError):
        parse_vn(raw)


def test_find_numbers_mixed():
    vals = [n.value for n in find_numbers("hơn 7100 tỷ đồng, đạt 7.109 Tỷ đồng")]
    assert vals == [Decimal("7100"), Decimal("7109")]


def test_find_numbers_no_split_and_spans():
    text = "Tổng 1.192.344.137 triệu, tăng +18,36% N/N, lỗ (415.884)."
    nums = find_numbers(text)
    assert [n.value for n in nums] == [
        Decimal("1192344137"),
        Decimal("18.36"),
        Decimal("-415884"),
    ]
    assert nums[1].is_percent and nums[1].basis == "YoY"
    for n in nums:
        assert text[n.span[0] : n.span[1]] == n.raw


def test_find_numbers_skip_years():
    text = "Năm 2024, trong giai đoạn 2021-2025 đạt 2025 chi nhánh, năm 2025 là 53,4%"
    assert [n.value for n in find_numbers(text)] == [Decimal("2025"), Decimal("53.4")]
    assert len(find_numbers(text, skip_years=False)) == 6


def test_normalize_chars():
    assert normalize_chars("1\xa0000\u20115") == "1 000-5"


@given(st.integers(min_value=-(10**12), max_value=10**12))
def test_roundtrip_int(n):
    assert parse_vn(format_vn(Decimal(n))).value == n


def test_format_vn():
    assert format_vn(Decimal("1192.344"), 2) == "1.192,34"
    assert format_vn(Decimal("-1192344")) == "-1.192.344"
    assert format_vn(Decimal("53.4")) == "53,4"
    assert format_vn(Decimal("2.5"), 0) == "3"
    assert format_vn(Decimal("-0.001"), 2) == "0,00"

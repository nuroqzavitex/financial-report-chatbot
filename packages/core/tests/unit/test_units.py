from decimal import Decimal

import pytest
from ircb.domain.units import UNIT_SCALE, UnitError, convert, normalize_unit, to_vnd


def test_units():
    assert to_vnd(Decimal("1.192"), "nghìn tỷ đồng") == Decimal("1192000000000")
    assert convert(Decimal("1192344137"), "triệu đồng", "nghìn tỷ đồng") == Decimal("1192.344137")
    assert normalize_unit("Đơn vị: Tỷ đồng") == "tỷ đồng"
    assert to_vnd(Decimal("40.4"), "%") is None
    with pytest.raises(UnitError):
        convert(Decimal(1), "%", "tỷ đồng")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Nghìn tỷ đồng", "nghìn tỷ đồng"),
        ("Triệu đồng", "triệu đồng"),
        ("Đơn vị: triệu đồng", "triệu đồng"),
        ("đồng", "đồng"),
        ("Điểm %", "điểm %"),
        ("%", "%"),
        ("Lần", "lần"),
        ("kg", None),
    ],
)
def test_normalize_unit(raw, expected):
    assert normalize_unit(raw) == expected


def test_scale_and_non_money():
    assert UNIT_SCALE == {
        "đồng": 1,
        "triệu đồng": 10**6,
        "tỷ đồng": 10**9,
        "nghìn tỷ đồng": 10**12,
    }
    assert to_vnd(Decimal(2), "điểm %") is None
    assert to_vnd(Decimal(2), "lần") is None
    assert to_vnd(Decimal(2), "Tỷ đồng") == Decimal(2000000000)

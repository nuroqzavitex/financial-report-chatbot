"""Money/ratio unit scales (pure)."""

from __future__ import annotations

from decimal import Decimal

UNIT_SCALE: dict[str, int] = {
    "đồng": 1,
    "triệu đồng": 10**6,
    "tỷ đồng": 10**9,
    "nghìn tỷ đồng": 10**12,
}

_NON_MONEY = ("điểm %", "%", "lần")
# Longest first so "nghìn tỷ đồng" wins over "tỷ đồng" over "đồng", "điểm %" over "%".
_KNOWN = sorted([*UNIT_SCALE, *_NON_MONEY], key=len, reverse=True)


class UnitError(ValueError):
    pass


def normalize_unit(raw: str) -> str | None:
    s = " ".join(raw.replace("\xa0", " ").lower().split())
    for u in _KNOWN:
        if u in s:
            return u
    return None


def to_vnd(value: Decimal, unit: str) -> Decimal | None:
    u = normalize_unit(unit)
    if u is None or u not in UNIT_SCALE:
        return None
    return value * UNIT_SCALE[u]


def convert(value: Decimal, from_unit: str, to_unit: str) -> Decimal:
    f, t = normalize_unit(from_unit), normalize_unit(to_unit)
    if f not in UNIT_SCALE or t not in UNIT_SCALE:
        raise UnitError(f"cannot convert {from_unit!r} to {to_unit!r}")
    return value * UNIT_SCALE[f] / UNIT_SCALE[t]

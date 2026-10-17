"""Vietnamese-format number parsing and formatting (pure, Decimal-only)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_NUM = r"(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"

_PARSE_RE = re.compile(
    rf"""^(?P<approx>[~≈])?\s*
    (?P<open>\()?\s*(?P<sign>[+-])?(?P<num>{_NUM})\s*(?P<pct>%)?\s*(?P<close>\))?
    (?:\s*(?P<yoy>N/N))?$""",
    re.VERBOSE,
)

_FIND_RE = re.compile(
    rf"""(?<![\w.,])
    (?:[~≈]\s*)?
    (?:
        \((?:[+-])?{_NUM}(?:\s*%)?\)
      | [+-]?{_NUM}(?:\s*%)?
    )
    (?![\d]|[.,]\d)
    (?:\s+N/N\b|N/N\b)?""",
    re.VERBOSE,
)

_YEAR_CONTEXT_RE = re.compile(r"(?:năm|giai đoạn)\s+(?:\d{4}\s*[-–]\s*)?$", re.IGNORECASE)
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


@dataclass(frozen=True)
class ParsedNumber:
    value: Decimal
    raw: str
    is_percent: bool = False
    basis: str | None = None
    approx: bool = False
    span: tuple[int, int] = (0, 0)


def normalize_chars(s: str) -> str:
    return s.replace("\xa0", " ").replace("‑", "-")


def _to_decimal(num: str) -> Decimal:
    return Decimal(num.replace(".", "").replace(",", "."))


def parse_vn(raw: str) -> ParsedNumber:
    s = normalize_chars(raw).strip()
    if s == "-":
        return ParsedNumber(Decimal("0"), raw, span=(0, len(raw)))
    m = _PARSE_RE.match(s)
    if not m or bool(m["open"]) != bool(m["close"]):
        raise ValueError(f"not a Vietnamese number: {raw!r}")
    try:
        value = _to_decimal(m["num"])
    except InvalidOperation as e:  # pragma: no cover - regex guarantees validity
        raise ValueError(f"not a Vietnamese number: {raw!r}") from e
    if m["open"] or m["sign"] == "-":
        value = -value
    return ParsedNumber(
        value=value,
        raw=raw,
        is_percent=bool(m["pct"]),
        basis="YoY" if m["yoy"] else None,
        approx=bool(m["approx"]),
        span=(0, len(raw)),
    )


def find_numbers(text: str, skip_years: bool = True) -> list[ParsedNumber]:
    text = normalize_chars(text)
    out: list[ParsedNumber] = []
    for m in _FIND_RE.finditer(text):
        token = m.group(0)
        if skip_years and _YEAR_RE.match(token) and _YEAR_CONTEXT_RE.search(text[: m.start()]):
            continue
        try:
            p = parse_vn(token)
        except ValueError:
            continue
        out.append(ParsedNumber(p.value, token, p.is_percent, p.basis, p.approx, (m.start(), m.end())))
    return out


def format_vn(value: Decimal, decimals: int | None = None) -> str:
    if decimals is not None:
        value = value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    s = format(value, "f")
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    int_part, _, frac = s.partition(".")
    grouped = f"{int(int_part):,}".replace(",", ".")
    body = grouped + ("," + frac if frac else "")
    if neg and value != 0:
        body = "-" + body
    return body

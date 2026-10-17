"""Deterministic period guard: refuse questions about years the report does not cover."""

import re
from dataclasses import dataclass

from ircb.domain.models import RewriteResult

REPORT_YEAR = 2025
LAST_FORECAST_YEAR = 2026

_QUANTITY_WORDS = r"tỷ|triệu|nghìn|đồng|khách hàng|chi nhánh|nhân viên|thẻ|người|giao dịch|%"
# A 19xx/20xx token is a year unless glued to digit separators or followed by a quantity/unit word.
_YEAR_RE = re.compile(
    rf"(?<!\d)(?<!\d[.,])\b(?:19|20)\d{{2}}\b(?![.,]\d)(?!\s*(?:{_QUANTITY_WORDS}))",
    re.IGNORECASE,
)
_FY_RE = re.compile(r"\bFY\s?(\d{4}|\d{2})\b", re.IGNORECASE)


@dataclass(frozen=True)
class GuardRefusal:
    reason: str


def _refusal(year: str) -> GuardRefusal:
    return GuardRefusal(f"Báo cáo thường niên {REPORT_YEAR} không có số liệu/dự báo cho năm {year}.")


def explicit_years(text: str) -> list[str]:
    """Explicit years in ``text`` (4-digit and FYxx forms), ascending and deduplicated.

    Relative phrases ("năm nay", "năm ngoái", "năm trước") are not explicit and never match.
    """
    years = set(_YEAR_RE.findall(text))
    for m in _FY_RE.finditer(text):
        y = m.group(1)
        years.add(y if len(y) == 4 else f"20{y}")
    return sorted(years)


def period_guard(question: str, periods_seen: set[str]) -> GuardRefusal | None:
    for y in explicit_years(question):
        if y not in periods_seen:
            return _refusal(y)
    return None


def post_rewrite_guard(rw: RewriteResult, periods_seen: set[str]) -> GuardRefusal | None:
    for p in rw.periods:
        for y in explicit_years(p):
            if y not in periods_seen:
                return _refusal(y)
    if rw.is_forecast:
        for y in explicit_years(" ".join([*rw.periods, rw.standalone_query])):
            if int(y) > LAST_FORECAST_YEAR and y not in periods_seen:
                return _refusal(y)
    return None

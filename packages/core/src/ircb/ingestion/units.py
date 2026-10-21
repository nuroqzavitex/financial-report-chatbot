"""Business unit (khối / công ty con) of a printed page, from ``config/units.json``.

A unit's name is printed on its opening page only (CIBG on p. 68), so a chunk of a later page of
the same unit ("Số dư tiền gửi: 24% N/N", p. 71) never mentions it and a question naming the unit
cannot find it. The page ranges are curated like ``config/sections.json``: the report has eleven
units, and their headings are too irregular in size and layout to detect reliably.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

_UNITS_REL = Path("config") / "units.json"


def units_path() -> Path:
    local = Path.cwd() / _UNITS_REL
    return local if local.exists() else Path(__file__).resolve().parents[5] / _UNITS_REL


@cache
def _load(path: str) -> tuple[tuple[int, int, str], ...]:
    p = Path(path)
    if not p.exists():
        return ()
    rows = json.loads(p.read_text(encoding="utf-8"))
    return tuple((int(r["printed_start"]), int(r["printed_end"]), str(r["title"])) for r in rows)


def unit_of(printed: int, path: Path | None = None) -> str | None:
    """Title of the unit whose page range holds ``printed``; None outside every unit."""
    for start, end, title in _load(str(path or units_path())):
        if start <= printed <= end:
            return title
    return None

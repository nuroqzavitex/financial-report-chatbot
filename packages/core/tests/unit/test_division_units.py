import json
from pathlib import Path

from ircb.ingestion.units import unit_of


def test_unit_of_page_ranges(tmp_path: Path) -> None:
    cfg = tmp_path / "units.json"
    cfg.write_text(
        json.dumps([{"title": "Khối A (A)", "printed_start": 10, "printed_end": 12}]), encoding="utf-8"
    )
    assert [unit_of(p, cfg) for p in (9, 10, 12, 13)] == [None, "Khối A (A)", "Khối A (A)", None]
    assert unit_of(10, tmp_path / "missing.json") is None


def test_shipped_units_cover_the_report_divisions() -> None:
    assert unit_of(71) == "Khối Ngân hàng Doanh nghiệp và Định chế Tài chính (CIBG)"
    assert unit_of(59) == "Khối Ngân hàng Bán lẻ (RBG)"
    assert "TCBS" in (unit_of(78) or "")
    assert unit_of(5) is None and unit_of(300) is None

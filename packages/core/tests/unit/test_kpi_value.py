import pytest
from ircb.ingestion.kpi import is_kpi_value


@pytest.mark.parametrize("text", ["1.192", "40,4%", "1,13%", "TOP 1", "86%", "18", "~16%", "#1", "60% "])
def test_kpi_values_accepted(text: str) -> None:
    assert is_kpi_value(text)


@pytest.mark.parametrize(
    "text", ["Điểm nhấn 2025", "Năm 2025", "DẤU ẤN WEALTHTECH NĂM 2025", "Chúng tôi là ai", ""]
)
def test_section_headings_rejected(text: str) -> None:
    assert not is_kpi_value(text)

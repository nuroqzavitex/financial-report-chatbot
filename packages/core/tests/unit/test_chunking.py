from factories import gutter_table, table, table_with, tile
from ircb.ingestion.chunking import (
    chunks_from_glossary,
    chunks_from_kpi,
    chunks_from_prose,
    chunks_from_table,
)
from ircb.ingestion.glossary import GlossaryEntry
from ircb.ingestion.prose import ProseBlock
from ircb.ingestion.tables import Cell, TableRow

BOX = (0.0, 0.0, 10.0, 10.0)


def _tokens(s: str) -> float:
    return len(s.split()) * 1.3


def test_gutter_chunk_two_pages() -> None:
    cs = chunks_from_table(gutter_table())
    assert len(cs) == 1 and cs[0].printed_pages == [374, 375] and cs[0].content_type == "table"


def test_table_chunk_text_and_facts() -> None:
    c = chunks_from_table(table_with(["1", "x"]), chapter="BCTC")[0]
    assert c.chunk_id == "p149R_t02" and c.chapter == "BCTC" and c.unit == "triệu đồng"
    assert c.text.startswith("B02/TCTD-HN · Báo cáo tình hình tài chính hợp nhất · Đơn vị: triệu đồng\n")
    assert "| Cho vay khách hàng | 1 | x |" in c.text
    assert c.fact_ids == ["p149R_t02_r00_c0"] and c.doc_id == "tcb-ar-2025" and c.half == "R"


def test_long_table_split_repeats_header() -> None:
    rows = [TableRow(f"Dòng {i}", 0, None, False, None, [Cell("2025", str(i), BOX)]) for i in range(70)]
    cs = chunks_from_table(table(rows=rows))
    assert [c.chunk_id for c in cs] == ["p149R_t02_g01", "p149R_t02_g02", "p149R_t02_g03"]
    assert all("| Chỉ tiêu | 2025 |" in c.text for c in cs)
    assert "Dòng 69" in cs[-1].text and "Dòng 69" not in cs[0].text
    assert cs[1].fact_ids[0] == f"p149R_t02_r{len(cs[0].fact_ids):02d}_c0"


def test_table_without_unit_has_no_fact_ids() -> None:
    assert chunks_from_table(table_with(["1"], unit=None))[0].fact_ids == []


def test_kpi_chunk_sentence() -> None:
    c = chunks_from_kpi([tile()], 30, "R")[0]
    assert c.chunk_id == "p30R_k" and c.content_type == "kpi" and c.printed_pages == [30]
    assert "328,1 nghìn tỷ đồng" in c.text
    assert c.text == (
        "Khối Ngân hàng Bán lẻ\nDư nợ vay: 328,1 nghìn tỷ đồng, tăng 26,9% so với cùng kỳ năm trước"
    )
    assert c.fact_ids == ["p30R_k01", "p30R_k01_chg"]


def test_kpi_direction_words() -> None:
    down = chunks_from_kpi([tile(direction="down")], 30, "R")[0].text
    unk = chunks_from_kpi([tile(direction="unknown")], 30, "R")[0].text
    assert "giảm 26,9%" in down and "tăng" not in down
    assert "tăng" not in unk and "giảm" not in unk and "thay đổi 26,9% N/N" in unk


def test_kpi_other_basis_and_no_change() -> None:
    c = chunks_from_kpi(
        [tile(basis="CAGR 2018–2025", change="15,2%"), tile(label="CIR", change=None)], 30, "L"
    )[0]
    assert "tăng trưởng kép (CAGR) 2018–2025: 15,2%" in c.text and "CIR: 328,1 nghìn tỷ đồng" in c.text
    assert c.fact_ids == ["p30L_k01", "p30L_k01_chg", "p30L_k02"]


def test_glossary_chunk() -> None:
    e = GlossaryEntry("Tỷ lệ CIR", "Chi phí trên thu nhập", 400, BOX)
    c = chunks_from_glossary([e], 200, "R", "Phụ lục")[0]
    assert c.chunk_id == "g_ty_le_cir" and c.content_type == "glossary" and c.printed_pages == [400]
    assert c.text == "Tỷ lệ CIR: Chi phí trên thu nhập" and c.chapter == "Phụ lục"


def _block(heading: str | None, n_words: int, sent: int = 12) -> ProseBlock:
    words = [f"w{i}" for i in range(n_words)]
    sentences = [" ".join(words[i : i + sent]) + "." for i in range(0, n_words, sent)]
    return ProseBlock(heading, " ".join(sentences), BOX, 20)


def test_prose_prefix_and_ids() -> None:
    cs = chunks_from_prose([_block("Chiến lược", 300)], 11, "L", "Tổng quan")
    assert len(cs) == 1
    assert cs[0].chunk_id == "p11L_x01" and cs[0].text.startswith("Tổng quan > Chiến lược\n")
    assert cs[0].content_type == "prose" and cs[0].printed_pages == [20] and cs[0].fact_ids == []


def test_prose_splits_to_token_budget() -> None:
    cs = chunks_from_prose([_block("H", 1500)], 11, "L", None)
    assert len(cs) >= 3
    assert [c.chunk_id for c in cs][:2] == ["p11L_x01", "p11L_x02"]
    assert cs[0].text.startswith("H\n")
    for c in cs[:-1]:
        assert 300 <= _tokens(c.text.split("\n", 1)[1]) <= 500
    assert all(_tokens(c.text.split("\n", 1)[1]) <= 500 for c in cs)


def test_prose_merges_small_blocks() -> None:
    cs = chunks_from_prose([_block("A", 100), _block("B", 100), _block("C", 100)], 11, "R", "Ch")
    assert len(cs) == 1 and cs[0].text.startswith("Ch > A\n") and "\nB\n" in cs[0].text


def test_prose_oversize_sentence_is_hard_split() -> None:
    b = ProseBlock(None, " ".join(f"w{i}" for i in range(1000)), BOX, 20)
    cs = chunks_from_prose([b], 11, "L", None)
    assert len(cs) >= 3 and all(_tokens(c.text) <= 500 for c in cs)


def test_glossary_ids_deduplicated_and_slugged() -> None:
    es = [GlossaryEntry(t, "d", 400, BOX) for t in ("ROE (%)", "ROE", "roe", "NIM")]
    ids = [c.chunk_id for c in chunks_from_glossary(es, 200, "R")]
    assert ids == ["g_roe", "g_roe_2", "g_roe_3", "g_nim"]


def test_kpi_cagr_sentence_shows_the_percent() -> None:
    t = tile(change="Tăng trưởng kép 2018–2025: 16,5%", basis="CAGR 2018–2025", direction="unknown")
    text = chunks_from_kpi([t], 3, "R")[0].text
    assert "tăng trưởng kép (CAGR) 2018–2025: 16,5%" in text and "2018%" not in text

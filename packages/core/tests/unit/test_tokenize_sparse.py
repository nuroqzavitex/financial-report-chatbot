from ircb.retrieval.sparse_bm25 import SparseVec, encode_doc, encode_query
from ircb.retrieval.tokenize_vi import TOKENIZER_VERSION, term_id, tokenize


def test_keeps_codes():
    assert "b05/tctd-hn" in tokenize("Theo B05/TCTD-HN")
    assert "casa" in tokenize("Tỷ lệ CASA")


def test_bigrams():
    assert "tổng_tài" in tokenize("tổng tài sản")


def test_tokenize_emits_unaccented_variant():
    assert set(tokenize("tong tai san")) & set(tokenize("tổng tài sản")) >= {"tong", "tai", "san"}


def test_d_stroke_and_version():
    assert "dong" in tokenize("đồng")
    assert TOKENIZER_VERSION == "vi-1"


def test_term_id_stable():
    assert term_id("casa") == term_id("casa")
    assert 0 <= term_id("casa") < 2**32


def test_bm25_saturation():
    v = encode_doc(["a"] * 10 + ["b"], avg_len=11)
    a, b = (v.values[v.indices.index(term_id(t))] for t in "ab")
    assert a > b and a < 10 * b


def test_encode_query_tf1():
    q = encode_query(["x", "x", "y"])
    assert isinstance(q, SparseVec)
    assert sorted(q.indices) == sorted([term_id("x"), term_id("y")])
    assert q.values == [1.0, 1.0]


def test_nfd_equals_nfc():
    import unicodedata

    t = "Tổng tài sản đồng"
    assert tokenize(unicodedata.normalize("NFD", t)) == tokenize(unicodedata.normalize("NFC", t))
    assert "tổng_tài" in tokenize(unicodedata.normalize("NFD", t))


def test_case_insensitive_no_acronym_special_case():
    assert tokenize("CASA tăng") == tokenize("casa tăng")
    assert tokenize("TONG TAI SAN") == tokenize("tong tai san")


def test_codes_participate_in_bigrams():
    toks = tokenize("theo B05/TCTD-HN này")
    assert "theo_b05/tctd-hn" in toks and "b05/tctd-hn_này" in toks

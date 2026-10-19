from dataclasses import dataclass, field
from typing import Any

import pytest
from factories import fact
from ircb.domain.models import RewriteResult
from ircb.retrieval.gate import passes_gate
from ircb.retrieval.glossary_expand import build_glossary, expand_query
from ircb.retrieval.hybrid import Context, FactLookup, RetrievalDeps
from ircb.retrieval.prefetch import prefetch
from ircb.retrieval.sparse_bm25 import SparseVec
from ircb.storage.vector_store import Hit


def chunk_payload(cid: str, content_type: str = "prose") -> dict[str, Any]:
    return {
        "chunk_id": cid,
        "doc_id": "tcb-ar-2025",
        "pdf_page": 1,
        "half": "L",
        "printed_pages": [1],
        "chapter": None,
        "statement": None,
        "note_no": None,
        "content_type": content_type,
        "unit": None,
        "text": cid,
        "fact_ids": [],
        "bbox": [0.0, 0.0, 1.0, 1.0],
    }


@dataclass
class FakeBackend:
    calls: list[list[str]] = field(default_factory=list)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.1, 0.2] for _ in texts]


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None, SparseVec]] = []

    def hybrid(
        self, kind: str, dense: list[float], sparse: SparseVec, flt: dict[str, Any] | None, limit: int
    ) -> list[Hit]:
        self.calls.append((kind, flt, sparse))
        if kind == "facts":
            return [
                Hit("f2024", 0.5, 0.6, 2, {"period": "2024-12-31"}),
                Hit("f2025", 0.4, 0.5, 1, {"period": "FY2025"}),
                Hit("fdup", 0.3, 0.4, 1, {"period": "FY2025"}),
            ]
        ct = (flt or {}).get("content_type", "prose")
        return [
            Hit(f"{ct}1", 0.5, 0.5, 1, chunk_payload(f"{ct}1", ct)),
            Hit("shared", 0.4, 0.4, 1, chunk_payload("shared")),
        ]


class FakeSql:
    def get_many(self, ids: list[str]) -> dict[str, Any]:
        return {i: fact(fact_id=i, label=i) for i in ids}


@pytest.fixture
def deps() -> RetrievalDeps:
    d = RetrievalDeps(
        store=FakeStore(), sql=FakeSql(), embedder=FakeBackend(), glossary={"CASA": ["tiền gửi không kỳ hạn"]}
    )
    return d


def rw(**kw: Any) -> RewriteResult:
    base: dict[str, Any] = {
        "standalone_query": "q",
        "metrics": [],
        "periods": [],
        "entity": None,
        "needs_comparison": False,
        "needs_calc": False,
        "is_forecast": False,
        "topic": None,
    }
    base.update(kw)
    return RewriteResult(**base)


def fact_calls(deps: RetrievalDeps) -> list[Any]:
    return [c for c in deps.store.calls if c[0] == "facts"]  # type: ignore[attr-defined]


def test_single_embed_request(deps: RetrievalDeps) -> None:
    prefetch(rw(metrics=["tổng tài sản", "cho vay khách hàng"], periods=["2025", "2024"]), deps)
    assert deps.embedder.calls == [["q", "tổng tài sản", "cho vay khách hàng"]]  # type: ignore[attr-defined]


def test_lookup_per_pair_capped(deps: RetrievalDeps) -> None:
    prefetch(rw(metrics=list("abcd"), periods=["2025", "2024", "2023", "2022"]), deps)
    assert len(fact_calls(deps)) == 9


def test_needs_calc_false_still_fetches_facts(deps: RetrievalDeps) -> None:
    assert prefetch(rw(needs_calc=False, metrics=["tổng tài sản"]), deps).facts


def test_glossary_branch(deps: RetrievalDeps) -> None:
    prefetch(rw(standalone_query="CASA là viết tắt của gì"), deps)
    assert {"doc_id": "tcb-ar-2025", "content_type": "glossary"} in [c[1] for c in deps.store.calls]  # type: ignore[attr-defined]


def test_no_glossary_branch_otherwise(deps: RetrievalDeps) -> None:
    prefetch(rw(standalone_query="doanh thu 2025"), deps)
    assert all((c[1] or {}).get("content_type") != "glossary" for c in deps.store.calls)  # type: ignore[attr-defined]


def test_every_filter_has_doc_id(deps: RetrievalDeps) -> None:
    prefetch(rw(metrics=["a"], periods=["2025"]), deps)
    assert all((c[1] or {}).get("doc_id") == "tcb-ar-2025" for c in deps.store.calls)  # type: ignore[attr-defined]


def test_expand_uses_glossary_extra_aliases() -> None:
    assert "tỷ lệ nợ xấu" in expand_query("NPL năm 2025", {"NPL": ["tỷ lệ nợ xấu"]})


def test_expand_whole_word_case_insensitive() -> None:
    g = {"NPL": ["nợ xấu"]}
    assert "nợ xấu" in expand_query("npl là gì", g)
    assert expand_query("NPLX", g) == "NPLX"


def test_build_glossary_merges_entries_and_extra() -> None:
    g = build_glossary(
        {"entries": [{"term": "CASA", "definition": "d"}], "extra": {"CASA": ["x"], "TM": ["y"]}}
    )
    assert g == {"CASA": ["d", "x"], "TM": ["y"]}


def test_expansion_only_in_sparse(deps: RetrievalDeps) -> None:
    from ircb.retrieval.sparse_bm25 import encode_query
    from ircb.retrieval.tokenize_vi import tokenize

    prefetch(rw(standalone_query="CASA là gì"), deps)
    plain = encode_query(tokenize("CASA là gì"))
    sparse = deps.store.calls[0][2]  # type: ignore[attr-defined]
    assert len(sparse.indices) > len(plain.indices)
    assert deps.embedder.calls == [["CASA là gì"]]  # type: ignore[attr-defined]


def test_period_post_filter_and_dedupe(deps: RetrievalDeps) -> None:
    ctx = prefetch(rw(metrics=["a"], periods=["2025"]), deps)
    assert [f.fact_id for f in ctx.facts] == ["f2025", "fdup"]
    ctx2 = prefetch(rw(metrics=["a", "b"], periods=["2025"]), deps)
    assert [f.fact_id for f in ctx2.facts] == ["f2025", "fdup"]


def test_lookup_embeds_only_without_dense(deps: RetrievalDeps) -> None:
    fl = FactLookup(deps.store, deps.sql, deps.embedder)
    fl.lookup("m", None, dense=[0.0, 0.0])
    assert deps.embedder.calls == []  # type: ignore[attr-defined]
    fl.lookup("m", None)
    assert deps.embedder.calls == [["m"]]  # type: ignore[attr-defined]


def test_lookup_statement_filter(deps: RetrievalDeps) -> None:
    FactLookup(deps.store, deps.sql, deps.embedder).lookup("m", None, statement="B02", dense=[0.0])
    assert fact_calls(deps)[0][1] == {"doc_id": "tcb-ar-2025", "statement": "B02"}


def test_chunk_order_and_dedupe(deps: RetrievalDeps) -> None:
    normal = prefetch(rw(), deps)
    assert [c.chunk_id for c in normal.chunks] == ["prose1", "shared", "table1"]
    calc = prefetch(rw(needs_calc=True), deps)
    assert [c.chunk_id for c in calc.chunks] == ["table1", "shared", "prose1"]
    assert calc.facts == []


def ctx(dense: float | None, branches: int, kind: str = "chunk") -> Context:
    h = [Hit("x", 0.1, dense, branches, {})]
    return Context(chunk_hits=h if kind == "chunk" else [], fact_hits=h if kind == "fact" else [])


def test_gate() -> None:
    assert not passes_gate(ctx(dense=0.2, branches=1), 0.45)
    assert passes_gate(ctx(dense=0.2, branches=2), 0.45)
    assert passes_gate(ctx(dense=0.5, branches=1), 0.45)
    assert passes_gate(ctx(dense=0.5, branches=1, kind="fact"), 0.45)
    assert not passes_gate(ctx(dense=None, branches=1), 0.45)
    assert not passes_gate(Context(), 0.45)


class ScoreStore(FakeStore):
    """table branch top-1 weak (0.2), general top-1 strong (0.6); fact pair b strong, pair a weak."""

    def hybrid(self, kind, dense, sparse, flt, limit):  # type: ignore[no-untyped-def]
        self.calls.append((kind, flt, sparse))
        if kind == "facts":
            weak = len([c for c in self.calls if c[0] == "facts"]) == 1
            return [Hit("fx", 0.1, 0.2 if weak else 0.6, 1, {"period": None})]
        ct = (flt or {}).get("content_type", "prose")
        d = 0.2 if ct == "table" else 0.6
        return [Hit(f"{ct}1", 0.5, d, 1, chunk_payload(f"{ct}1", ct))]


@pytest.mark.parametrize("calc", [True, False])
def test_gate_independent_of_flags(calc: bool) -> None:
    d = RetrievalDeps(store=ScoreStore(), sql=FakeSql(), embedder=FakeBackend())
    c = prefetch(rw(needs_calc=calc), d)
    assert passes_gate(c, 0.35)
    assert not passes_gate(c, 0.7)


def test_gate_best_fact_in_second_pair() -> None:
    class OnlyFacts(ScoreStore):
        def hybrid(self, kind, dense, sparse, flt, limit):  # type: ignore[no-untyped-def]
            if kind == "chunks":
                self.calls.append((kind, flt, sparse))
                return []
            return super().hybrid(kind, dense, sparse, flt, limit)

    d = RetrievalDeps(store=OnlyFacts(), sql=FakeSql(), embedder=FakeBackend())
    c = prefetch(rw(metrics=["a", "b"]), d)
    assert passes_gate(c, 0.35)

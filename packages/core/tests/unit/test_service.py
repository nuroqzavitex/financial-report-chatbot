import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from factories import fact
from ircb.answering.generator import PROMPT_VERSION
from ircb.domain.models import (
    CalcSpec,
    Chunk,
    ClaimOut,
    Conflict,
    GeneratorOutput,
    RewriteResult,
    TurnState,
)
from ircb.llm.client import LLMError, Usage
from ircb.retrieval.hybrid import FactLookup, RetrievalDeps
from ircb.service import ERROR_TEXT, AnswerService
from ircb.settings import Settings
from ircb.storage.vector_store import Hit
from pydantic import BaseModel

TTS = fact(
    fact_id="tts25",
    label="Tổng tài sản",
    label_norm="tổng tài sản",
    period="2025",
    value=Decimal("1192"),
    unit="nghìn tỷ đồng",
    printed_pages=[5],
)
CHUNK = Chunk(
    chunk_id="c1",
    doc_id="tcb-ar-2025",
    pdf_page=3,
    half="R",
    printed_pages=[7],
    chapter=None,
    statement=None,
    note_no=None,
    content_type="prose",
    unit=None,
    text="Tổng tài sản 1.192 nghìn tỷ đồng",
    fact_ids=[],
    bbox=[0.0, 0.0, 1.0, 1.0],
)


def rw(**kw: Any) -> RewriteResult:
    base: dict[str, Any] = {
        "standalone_query": "Tổng tài sản năm 2025",
        "metrics": ["tổng tài sản"],
        "periods": ["2025"],
        "entity": None,
        "needs_comparison": False,
        "needs_calc": False,
        "is_forecast": False,
        "topic": None,
    }
    base.update(kw)
    return RewriteResult(**base)


def claim(text: str) -> ClaimOut:
    return ClaimOut(text=text, sources=["fact:tts25"], evidence="")


def gen(*claims: ClaimOut, status: str = "answered", calcs: list[CalcSpec] | None = None) -> GeneratorOutput:
    return GeneratorOutput.model_validate(
        {
            "status": status,
            "claims": [c.model_dump() for c in claims],
            "calcs": [c.model_dump() for c in calcs or []],
            "conflict": Conflict(kind=None, note="").model_dump(),
            "need_fact": None,
        }
    )


class FakeClient:
    def __init__(self, rewrite: RewriteResult, generated: GeneratorOutput) -> None:
        self.rewrite_out, self.gen_out = rewrite, generated
        self.calls = 0
        self.gen_calls = 0
        self.models: list[str] = []
        self.down_on: str | None = None
        self.boom: Exception | None = None
        self.rewrite_messages: list[dict[str, Any]] = []

    def complete_json(
        self, model: str, messages: list[dict[str, Any]], schema: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        self.calls += 1
        self.models.append(model)
        if self.boom is not None:
            raise self.boom
        if self.down_on == schema.__name__:
            raise LLMError("down")
        usage = Usage(10, 5, Decimal("0.001"))
        if schema is RewriteResult:
            self.rewrite_messages = messages
            return self.rewrite_out, usage
        self.gen_calls += 1
        return self.gen_out, usage


class FakeStore:
    def __init__(self, dense_score: float, branches: int) -> None:
        self.dense_score, self.branches = dense_score, branches

    def hybrid(self, kind: str, dense: Any, sparse: Any, flt: Any, limit: int) -> list[Hit]:
        if kind == "chunks":
            return [Hit("c1", 0.5, self.dense_score, self.branches, CHUNK.model_dump())]
        return [Hit("tts25", 0.5, self.dense_score, self.branches, {"period": "2025"})]


class FakeSql:
    def get_many(self, ids: list[str]) -> dict[str, Any]:
        return {i: TTS for i in ids if i == "tts25"}


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 4 for _ in texts]


def make_service(
    tmp_path: Path,
    generated: GeneratorOutput,
    *,
    rewritten: RewriteResult | None = None,
    dense_score: float = 0.9,
    branches: int = 2,
) -> AnswerService:
    settings = Settings(llm_model="big", llm_model_small="small", refusal_threshold=0.35)
    store, sql, emb = FakeStore(dense_score, branches), FakeSql(), FakeEmbedder()
    deps = RetrievalDeps(store=store, sql=sql, embedder=emb)
    client = FakeClient(rewritten or rw(), generated)
    return AnswerService(
        settings,
        deps,
        client,  # type: ignore[arg-type]
        FactLookup(store, sql, emb),
        {"2024", "2025"},
        tmp_path / "traces",
    )


def fake(svc: AnswerService) -> FakeClient:
    return svc.client  # type: ignore[return-value]


def trace_lines(svc: AnswerService) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in svc.trace_dir.glob("*.jsonl"):
        out += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    return out


GOOD = "Tổng tài sản đạt 1.192 nghìn tỷ đồng"
BAD = "Tổng thu nhập hoạt động đạt 9.999 nghìn tỷ đồng"


@pytest.fixture
def svc(tmp_path: Path) -> AnswerService:
    return make_service(tmp_path, gen(claim(GOOD)))


def test_guard_short_circuits(svc: AnswerService) -> None:
    a = svc.ask("Dự báo LNTT năm 2027?")
    assert a.status == "refused" and fake(svc).calls == 0
    assert "2027" in a.text


def test_guard_keeps_prev_state(svc: AnswerService) -> None:
    prev = TurnState(metrics=["m"], periods=["2025"], entity=None)
    assert svc.ask("Dự báo LNTT năm 2027?", prev_state=prev).state == prev


def test_post_rewrite_guard_keeps_prev_state(tmp_path: Path) -> None:
    s = make_service(tmp_path, gen(claim(GOOD)), rewritten=rw(periods=["2030"]))
    prev = TurnState(metrics=["m"], periods=["2025"], entity=None)
    a = s.ask("còn năm sau nữa?", prev_state=prev)
    assert a.status == "refused" and a.state == prev and fake(s).gen_calls == 0


def test_gate_refuses_without_generator(tmp_path: Path) -> None:
    s = make_service(tmp_path, gen(claim(GOOD)), dense_score=0.1, branches=1)
    a = s.ask("Giá vàng hôm nay?")
    assert a.status == "refused" and fake(s).gen_calls == 0
    assert "[tr. 7]" in a.text  # suggest_pages from the top-1 chunk
    assert a.claims == [] and a.citations == []


def test_answered_flow(svc: AnswerService) -> None:
    a = svc.ask("Tổng tài sản 2025?")
    assert a.status == "answered" and a.text == GOOD + " [tr. 5]"
    assert [c.label for c in a.citations] == ["[tr. 5]"]
    assert a.cost_usd == Decimal("0.002") and "total" in a.latency_ms


def test_partial_flow(tmp_path: Path) -> None:
    s = make_service(tmp_path, gen(claim(GOOD), claim(BAD), status="partial"))
    a = s.ask("Tổng tài sản và thu nhập hoạt động?")
    assert a.status == "partial" and "Chưa xác minh được" in a.text
    assert [c.ok for c in a.claims] == [True, False]


def test_llm_error_maps_to_error_status(tmp_path: Path) -> None:
    s = make_service(tmp_path, gen(claim(GOOD)))
    fake(s).down_on = "GeneratorOutput"
    a = s.ask("Tổng tài sản?")
    assert a.status == "error" and a.claims == [] and a.text == ERROR_TEXT
    assert "error" in trace_lines(s)[0]["records"]  # trace is written even on error


def test_llm_error_in_rewrite_keeps_prev_state(tmp_path: Path) -> None:
    s = make_service(tmp_path, gen(claim(GOOD)))
    fake(s).down_on = "RewriteResult"
    prev = TurnState(metrics=["m"], periods=[], entity=None)
    a = s.ask("Tổng tài sản?", prev_state=prev)
    assert a.status == "error" and a.state == prev


def test_non_llm_exception_propagates_and_trace_written(tmp_path: Path) -> None:
    s = make_service(tmp_path, gen(claim(GOOD)))
    fake(s).boom = KeyError("bug")
    with pytest.raises(KeyError):
        s.ask("Tổng tài sản?")
    assert "KeyError" in trace_lines(s)[0]["records"]["error"]


def test_state_carried(svc: AnswerService) -> None:
    a = svc.ask("Tổng tài sản 2025?")
    assert a.state is not None and a.state.metrics == ["tổng tài sản"]


def test_history_reaches_the_rewriter_and_topic_is_kept(svc: AnswerService) -> None:
    fake(svc).rewrite_out = fake(svc).rewrite_out.model_copy(update={"topic": "Techcombank Mobile"})
    a = svc.ask("nó có tác dụng gì?", history=[("Techcombank Mobile là gì?", "Ứng dụng ngân hàng số.")])
    payload = json.loads(fake(svc).rewrite_messages[1]["content"])
    assert payload["recent_turns"] == [
        {"question": "Techcombank Mobile là gì?", "answer": "Ứng dụng ngân hàng số."}
    ]
    assert a.state is not None and a.state.topic == "Techcombank Mobile"


def test_models_split_between_rewriter_and_generator(svc: AnswerService) -> None:
    svc.ask("Tổng tài sản 2025?")
    assert fake(svc).models == ["small", "big"]


def test_trace_records(tmp_path: Path) -> None:
    s = make_service(tmp_path, gen(claim(GOOD), claim(BAD), status="partial"))
    a = s.ask("Tổng tài sản và thu nhập?")
    (line,) = trace_lines(s)
    rec = line["records"]
    assert line["trace_id"] == a.trace_id
    assert rec["prompt_version"] == PROMPT_VERSION
    assert rec["models"] == {"rewriter": "small", "generator": "big"}
    assert rec["retrieval_recovered"] is False
    assert rec["gate"]["passed"] is True
    assert [v["failed_rule"] for v in rec["verifier"]] == [None, "number_mismatch"]
    for step in ("period_guard", "rewrite", "post_rewrite_guard", "prefetch", "gate", "generate", "verify"):
        assert step in line["latency_ms"]
    assert line["usage"]["cost_usd"] == "0.002"


def test_trace_records_retrieved_pages_and_gate_hits(tmp_path: Path) -> None:
    """Eval needs printed pages (Recall@8 / MRR) and gate scores (threshold calibration) from the trace."""
    s = make_service(tmp_path, gen(claim(GOOD)), dense_score=0.42, branches=1)
    s.ask("Tổng tài sản 2025?")
    (line,) = trace_lines(s)
    rec = line["records"]
    assert rec["retrieval"]["chunk_pages"] == [[7]]
    assert rec["retrieval"]["fact_pages"] == [[5]]
    assert rec["gate"]["hits"] and all(h == {"dense_score": 0.42, "branches": 1} for h in rec["gate"]["hits"])


def test_from_settings_builds_without_network(tmp_path: Path) -> None:
    from ircb.storage import artefacts
    from test_vector_store_loader import DIM, build_index_dir

    idx = build_index_dir(tmp_path / "index", 3, "v1")
    artefacts.write_glossary(idx, {"entries": [], "extra": {"NPL": ["nợ xấu"]}})
    settings = Settings(
        llm_model="x",
        embed_dimensions=DIM,
        index_dir=idx,
        qdrant_path=str(tmp_path / "qdrant"),
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        trace_dir=tmp_path / "tr",
        embed_cache_dir=tmp_path / "ec",
    )
    s = AnswerService.from_settings(settings)
    try:
        assert s.periods_seen == {"2025"} and s.deps.glossary == {"NPL": ["nợ xấu"]}
        assert s.ask("Dự báo năm 2027?").status == "refused"
    finally:
        s.deps.store.close()  # type: ignore[attr-defined]


def test_generator_partial_with_all_claims_passing_is_partial(tmp_path: Path) -> None:
    """Regression I3: a half-answered compound question is never shown as answered."""
    s = make_service(tmp_path, gen(claim(GOOD), status="partial"))
    a = s.ask("Tổng tài sản và số nhân viên nữ năm 2025?")
    assert a.status == "partial"
    assert a.text == GOOD + " [tr. 5]\nMột phần câu hỏi không có thông tin trong Báo cáo thường niên 2025."


def test_conflict_note_from_model_is_never_output(tmp_path: Path) -> None:
    """Regression I4: only the conflict kind survives; the text is a fixed sentence."""
    g = gen(claim(GOOD)).model_copy(
        update={"conflict": Conflict(kind="genuine", note="Trang 5 ghi 1.192, trang 297 ghi 1.200")}
    )
    a = make_service(tmp_path, g).ask("Tổng tài sản 2025?")
    assert a.conflict == Conflict(kind="genuine", note="")
    assert "1.200" not in a.text and "Trang 5 ghi" not in a.text
    assert a.text.endswith("\nHai nguồn trong báo cáo cho số liệu khác nhau — cần kiểm tra.")


KPI_CHUNK = CHUNK.model_copy(
    update={
        "chunk_id": "k1",
        "content_type": "kpi",
        "text": "Điểm nhấn 2025\nTổng tài sản: 1.192 nghìn tỷ đồng, tăng 21,8% so với năm trước",
        "fact_ids": ["k1_chg"],
    }
)
K1_CHG = fact(
    fact_id="k1_chg",
    label="Tổng tài sản",
    label_norm="tong tai san",
    table_title="Điểm nhấn 2025",
    value=Decimal("21.8"),
    unit="%",
    source="kpi",
    period="FY2025",
    direction="up",
    change_basis="so với năm trước",
)


class KpiStore(FakeStore):
    def hybrid(self, kind: str, dense: Any, sparse: Any, flt: Any, limit: int) -> list[Hit]:
        if kind == "chunks":
            return [Hit("k1", 0.5, self.dense_score, self.branches, KPI_CHUNK.model_dump())]
        return []


class KpiSql:
    def __init__(self) -> None:
        self.asked: list[list[str]] = []

    def get_many(self, ids: list[str]) -> dict[str, Any]:
        self.asked.append(list(ids))
        return {i: K1_CHG for i in ids if i == "k1_chg"}


def test_cited_chunk_facts_reach_the_verifier(tmp_path: Path) -> None:
    """Real run sq-07: "tăng" on a KPI chunk is vouched by that chunk's own change fact."""
    text = "Tổng tài sản năm 2025 đạt 1.192 nghìn tỷ đồng, tăng 21,8% so với năm trước."
    ev = "Tổng tài sản: 1.192 nghìn tỷ đồng, tăng 21,8% so với năm trước"
    s = make_service(tmp_path, gen(ClaimOut(text=text, sources=["chunk:k1"], evidence=ev)))
    sql = KpiSql()
    s.deps.store, s.deps.sql = KpiStore(0.9, 2), sql
    a = s.ask("Tổng tài sản năm 2025 tăng bao nhiêu?")
    assert a.status == "answered", a.text
    assert ["k1_chg"] in sql.asked


def test_on_step_reports_pipeline_steps(tmp_path: Path) -> None:
    s = make_service(tmp_path, gen(claim(GOOD)))
    steps: list[str] = []
    s.ask("Tổng tài sản năm 2025?", on_step=steps.append)
    assert steps[:2] == ["period_guard", "rewrite"]
    assert {"prefetch", "generate", "verify", "render"} <= set(steps)

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from ircb.answering.guard import GuardRefusal, period_guard, post_rewrite_guard
from ircb.answering.rewriter import rewrite
from ircb.domain.models import RewriteResult, TurnState
from ircb.llm.client import Usage
from pydantic import BaseModel

SEEN = {str(y) for y in range(2018, 2027)} | {"2030"}
SAMPLES = Path(__file__).resolve().parents[4] / "data" / "sample_questions.json"


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
    return RewriteResult(**{**base, **kw})


class FakeClient:
    def __init__(self) -> None:
        self.reply_obj: BaseModel | None = None
        self.last_messages: list[dict[str, Any]] = []
        self.last_schema: type[BaseModel] | None = None

    def reply(self, obj: BaseModel) -> None:
        self.reply_obj = obj

    @property
    def last_messages_text(self) -> str:
        return json.dumps(self.last_messages, ensure_ascii=False)

    def complete_json(
        self, model: str, messages: list[dict[str, Any]], schema: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        self.last_messages = messages
        self.last_schema = schema
        assert self.reply_obj is not None
        return self.reply_obj, Usage(1, 1, Decimal(0))


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


def test_guard_2027() -> None:
    r = period_guard("Techcombank dự báo lợi nhuận trước thuế năm 2027 là bao nhiêu?", SEEN)
    assert isinstance(r, GuardRefusal)
    assert r.reason == "Báo cáo thường niên 2025 không có số liệu/dự báo cho năm 2027."


def test_guard_2026_passes() -> None:
    assert period_guard("Kế hoạch lợi nhuận năm 2026?", SEEN) is None


def test_guard_relative_and_fy_periods() -> None:
    assert period_guard("Tổng tài sản năm ngoái?", SEEN) is None
    assert period_guard("Tổng tài sản năm nay?", SEEN) is None
    assert period_guard("Tổng tài sản năm trước?", SEEN) is None
    assert period_guard("NPL FY24?", SEEN) is None
    assert period_guard("Dự báo FY2027?", SEEN) is not None
    refusal = period_guard("Dự báo FY 27?", SEEN)
    assert refusal is not None and "2027" in refusal.reason


def test_guard_any_missing_year_refuses_and_names_it() -> None:
    r = period_guard("So sánh 2024, 2025 và 2028", SEEN)
    assert r is not None and "2028" in r.reason


def test_guard_range_counts_both_ends() -> None:
    assert period_guard("Giai đoạn 2018–2025?", SEEN) is None
    r = period_guard("Giai đoạn 2015–2025?", SEEN)
    assert r is not None and "2015" in r.reason


def test_guard_ignores_non_years() -> None:
    assert period_guard("Vốn điều lệ 70.000 tỷ, 3.500 chi nhánh, 12345 khách", SEEN) is None


def test_post_guard_forecast() -> None:
    assert post_rewrite_guard(rw(periods=["2028"], is_forecast=True), SEEN) is not None


def test_post_guard_periods_not_seen() -> None:
    r = post_rewrite_guard(rw(periods=["2024", "2017"]), SEEN)
    assert r is not None and "2017" in r.reason


def test_post_guard_forecast_2026_passes() -> None:
    assert post_rewrite_guard(rw(periods=["2026"], is_forecast=True), SEEN) is None


def test_post_guard_forecast_year_in_query_only() -> None:
    assert post_rewrite_guard(rw(standalone_query="Dự báo năm 2027", is_forecast=True), SEEN) is not None


def test_post_guard_forecast_target_in_seen_passes() -> None:
    assert post_rewrite_guard(rw(periods=["2030"], is_forecast=True), SEEN) is None


def test_followup_uses_prev_state(fake_client: FakeClient) -> None:
    fake_client.reply(
        rw(standalone_query="Tổng tài sản năm 2024", metrics=["tổng tài sản"], periods=["2024"])
    )
    out = rewrite(
        "còn năm trước thì sao?",
        TurnState(metrics=["tổng tài sản"], periods=["2025"], entity=None),
        fake_client,  # type: ignore[arg-type]
        "m",
    )
    assert out.periods == ["2024"]
    assert "tổng tài sản" in fake_client.last_messages_text and "2025" in fake_client.last_messages_text
    assert fake_client.last_schema is RewriteResult
    assert fake_client.last_messages[0]["role"] == "system"
    assert "còn năm trước thì sao?" in fake_client.last_messages[0]["content"]
    user = json.loads(fake_client.last_messages[1]["content"])
    assert user["question"] == "còn năm trước thì sao?"
    assert user["previous_state"]["periods"] == ["2025"]


def test_rewrite_without_prev_state(fake_client: FakeClient) -> None:
    fake_client.reply(rw())
    rewrite("Tổng tài sản?", None, fake_client, "m")  # type: ignore[arg-type]
    assert json.loads(fake_client.last_messages[1]["content"])["previous_state"] is None


def test_sample_question_10_refused() -> None:
    if not SAMPLES.exists():
        pytest.skip("data/sample_questions.json not present")
    items = json.loads(SAMPLES.read_text(encoding="utf-8"))
    q = next(i for i in items if i["id"] == "sq-10")
    assert period_guard(q["question"], SEEN) is not None


@pytest.mark.parametrize(
    "q",
    [
        "Có 2000 khách hàng mới không?",
        "Lãi 1999 tỷ đồng?",
        "tăng 2023,5%",
        "tăng 2027,5%",
        "Doanh thu 2.027 tỷ",
        "Giá trị 2027,3 triệu",
        "Mã 1.2027 abc",
        "Có 2050 chi nhánh, 2010 nhân viên, 2020 thẻ, 2030 người, 2040 giao dịch?",
        "Tăng 2027 %?",
    ],
)
def test_guard_ignores_quantities(q: str) -> None:
    assert period_guard(q, SEEN) is None


def test_guard_still_refuses_years_near_text() -> None:
    assert period_guard("Dự báo năm 2027?", SEEN) is not None
    assert period_guard("Doanh thu năm 2027 là 5 tỷ", SEEN) is not None
    assert period_guard("giai đoạn 2018–2025", SEEN) is None
    r = period_guard("giai đoạn 2015–2025", SEEN)
    assert r is not None and "2015" in r.reason
    r = period_guard("giai đoạn 2018–2028", SEEN)
    assert r is not None and "2028" in r.reason


def test_post_guard_skips_non_year_periods() -> None:
    assert post_rewrite_guard(rw(periods=["Q1"]), SEEN) is None
    assert post_rewrite_guard(rw(periods=[""]), SEEN) is None
    assert post_rewrite_guard(rw(periods=["năm ngoái", "cuối kỳ"]), SEEN) is None
    r = post_rewrite_guard(rw(periods=["Q1", "2028"]), SEEN)
    assert r is not None and "2028" in r.reason


def test_rewrite_sees_recent_turns_clipped(fake_client: FakeClient) -> None:
    fake_client.reply(rw(topic="Techcombank Mobile"))
    history = [(f"Câu {i}", f"Đáp {i}") for i in range(5)] + [("Techcombank Mobile là gì?", "A " * 400)]
    out = rewrite("nó có tác dụng gì?", None, fake_client, "m", history)  # type: ignore[arg-type]
    turns = json.loads(fake_client.last_messages[1]["content"])["recent_turns"]
    assert [t["question"] for t in turns] == ["Câu 3", "Câu 4", "Techcombank Mobile là gì?"]
    assert turns[0]["answer"] == "Đáp 3"
    assert len(turns[-1]["answer"]) == 300 and turns[-1]["answer"].endswith("…")
    assert out.topic == "Techcombank Mobile"


def test_rewrite_first_turn_has_empty_recent_turns(fake_client: FakeClient) -> None:
    fake_client.reply(rw())
    rewrite("Tổng tài sản?", None, fake_client, "m")  # type: ignore[arg-type]
    assert json.loads(fake_client.last_messages[1]["content"])["recent_turns"] == []


def test_rewriter_prompt_examples_match_the_schema() -> None:
    """Every "Đầu ra" line of the prompt parses as a RewriteResult (so the examples carry topic)."""
    from pathlib import Path

    text = (Path(rewrite.__code__.co_filename).parent / "prompts" / "rewriter.md").read_text(encoding="utf-8")
    outs = [line.removeprefix("Đầu ra: ") for line in text.splitlines() if line.startswith("Đầu ra: ")]
    assert len(outs) == 6
    parsed = [RewriteResult.model_validate_json(o) for o in outs]
    assert [p.topic for p in parsed][3:] == ["Techcombank Mobile", "Khối Ngân hàng Bán lẻ (RBG)", None]


def test_stored_state_without_topic_still_loads() -> None:
    assert TurnState.model_validate_json('{"metrics": [], "periods": ["2025"], "entity": null}').topic is None

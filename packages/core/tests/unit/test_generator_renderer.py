import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from factories import fact
from ircb.answering import generator
from ircb.answering.generator import PROMPT_VERSION, build_messages, generate
from ircb.answering.renderer import REFUSED_TEXT, render
from ircb.domain.models import (
    Chunk,
    ClaimOut,
    Conflict,
    GeneratorOutput,
    NeedFact,
    VerifiedClaim,
)
from ircb.llm.client import Usage
from ircb.retrieval.hybrid import Context
from pydantic import BaseModel

PROMPT = Path(generator.__file__).with_name("prompts").joinpath("generator.md")


class FakeClient:
    def __init__(self) -> None:
        self.replies: list[BaseModel] = []
        self.calls = 0
        self.messages: list[list[dict[str, Any]]] = []

    def reply(self, *objs: BaseModel) -> None:
        self.replies = list(objs)

    def complete_json(
        self, model: str, messages: list[dict[str, Any]], schema: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        self.messages.append(messages)
        self.calls += 1
        return self.replies[min(self.calls, len(self.replies)) - 1], Usage(1, 1, Decimal(0))


class FakeLookup:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def lookup(self, metric: str, period: str | None, *a: Any, **k: Any) -> list[Any]:
        self.calls.append((metric, period))
        return [fact(fact_id="new1", label="Tổng tài sản", period="2024")]


def gen_out(need_fact: NeedFact | None = None, status: str = "answered") -> GeneratorOutput:
    return GeneratorOutput(
        status=status,  # type: ignore[arg-type]
        claims=[ClaimOut(text="a", sources=["fact:f1"], evidence="")],
        calcs=[],
        conflict=Conflict(kind=None, note=""),
        need_fact=need_fact,
    )


def nf() -> NeedFact:
    return NeedFact(metric="tổng tài sản", period="2024")


def vc(ok: bool = True, pages: list[int] | None = None, text: str = "Câu.") -> VerifiedClaim:
    return VerifiedClaim(
        text=text,
        sources=[],
        printed_pages=[5] if pages is None else pages,
        ok=ok,
        failed_rule=None if ok else "number_mismatch",
    )


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def lookup() -> FakeLookup:
    return FakeLookup()


@pytest.fixture
def ctx() -> Context:
    chunk = Chunk(
        chunk_id="c1",
        doc_id="d",
        pdf_page=1,
        half="L",
        printed_pages=[5],
        chapter=None,
        statement=None,
        note_no=None,
        content_type="prose",
        unit=None,
        text="Nội dung chunk",
        fact_ids=[],
        bbox=[0, 0, 1, 1],
    )
    return Context(chunks=[chunk], facts=[fact(fact_id="f1", label="Lãi", col_path="2025", raw="1,5")])


def test_single_call_when_no_need_fact(fake_client, ctx, lookup):
    fake_client.reply(gen_out())
    generate("q", ctx, [], fake_client, "m", lookup)
    assert fake_client.calls == 1 and lookup.calls == []


def test_need_fact_one_extra_round(fake_client, ctx, lookup):
    fake_client.reply(gen_out(need_fact=NeedFact(metric="tổng tài sản", period="2024")), gen_out())
    _, ctx2, recovered = generate("q", ctx, [], fake_client, "m", lookup)
    assert fake_client.calls == 2 and lookup.calls == [("tổng tài sản", "2024")] and recovered
    assert any(f.fact_id == "new1" for f in ctx2.facts)
    assert "[fact:new1]" in fake_client.messages[1][1]["content"]
    assert len(ctx.facts) == 1  # original context untouched


def test_need_fact_not_looped(fake_client, ctx, lookup):
    fake_client.reply(gen_out(need_fact=nf()), gen_out(need_fact=nf()))
    out, _, recovered = generate("q", ctx, [], fake_client, "m", lookup)
    assert fake_client.calls == 2 and len(lookup.calls) == 1 and recovered
    assert out.need_fact is not None


def test_build_messages_ids_and_history(ctx):
    msgs = build_messages("Câu hỏi?", ctx, [("u1", "a1"), ("u2", "a2"), ("u3", "a3"), ("u4", "a4")])
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == PROMPT.read_bytes().decode("utf-8")
    user = msgs[1]["content"]
    assert "[chunk:c1] (tr. 5) Nội dung chunk" in user
    assert "[fact:f1] Lãi | 2025 | 1,5 triệu đồng (tr. 1)" in user
    assert "Câu hỏi?" in user
    assert "u1" not in user and "u2" in user and "a4" in user


def test_prompt_version():
    assert PROMPT_VERSION == hashlib.sha256(PROMPT.read_bytes()).hexdigest()[:12]


def test_render_partial():
    status, text, cites = render([vc(ok=True, pages=[5]), vc(ok=False, pages=[5])], {}, None, "answered")
    assert status == "partial" and "Chưa xác minh được" in text and "[tr. 5]" in text
    assert [c.label for c in cites] == ["[tr. 5]"]


def test_render_failed_without_pages_skips_xem():
    _, text, _ = render([vc(), vc(ok=False, pages=[], text="x" * 100)], {}, None, "answered")
    assert text.endswith("\nChưa xác minh được một phần nội dung.")
    assert "xxx" not in text and "xem" not in text


def test_render_unverified_line_never_echoes_failed_claim():
    """Regression C2: a failed claim's text (numbers, raw placeholders) never reaches the user."""
    failed = [
        vc(ok=False, pages=[5], text="Lợi nhuận trước thuế đạt 45.000 tỷ đồng."),
        vc(ok=False, pages=[297, 5], text="Tổng tài sản {c1} so với năm 2024."),
    ]
    status, text, cites = render(
        [vc(text="Tổng tài sản đạt 1.192 nghìn tỷ đồng.", pages=[5]), *failed], {}, None, "answered"
    )
    assert status == "partial"
    assert text == (
        "Tổng tài sản đạt 1.192 nghìn tỷ đồng. [tr. 5]\n"
        "Chưa xác minh được một phần nội dung, xem [tr. 5, 297]."
    )
    assert "45" not in text and "{c1}" not in text and "2024" not in text
    assert [c.label for c in cites] == ["[tr. 5]"]


def test_render_refused():
    assert render([vc(ok=False)], {}, None, "answered")[0] == "refused"


def test_render_refused_not_found_with_suggestion():
    status, text, cites = render([vc()], {}, None, "not_found", suggest_pages=[7])
    assert status == "refused" and cites == []
    assert text == REFUSED_TEXT + " Có thể tham khảo [tr. 7]."
    assert REFUSED_TEXT == "Không tìm thấy thông tin này trong Báo cáo thường niên 2025."
    assert render([], {}, None, "answered")[1] == REFUSED_TEXT


def test_render_order_and_dedup_citations():
    claims = [vc(text="Một.", pages=[5]), vc(text="Hai.", pages=[297]), vc(text="Ba.", pages=[5])]
    status, text, cites = render(claims, {}, Conflict(kind="rounding", note=""), "answered")
    assert status == "answered"
    assert text.index("Một.") < text.index("Hai.") < text.index("Ba.")
    assert [c.label for c in cites] == ["[tr. 5]", "[tr. 297]"]


def test_prompt_has_rules():
    p = PROMPT.read_text(encoding="utf-8").lower()
    for must in [
        "{c",
        "need_fact",
        "Không tự đổi đơn vị",
        "không tự tính",
        "nghìn tỷ đồng",
        "tỉ",
        "giảm 0,5%",
        "fact:",
        "chunk:",
        "evidence",
        "một chỉ tiêu",
        "làm tròn",
        "khác định nghĩa",
        "khác thật sự",
        "convert",
        "điểm %",
    ]:
        assert must.lower() in p, must


def _prompt_examples() -> list[GeneratorOutput]:
    """Every JSON object starting with {"status" in the prompt's worked examples."""
    import json

    text = PROMPT.read_text(encoding="utf-8")
    dec = json.JSONDecoder()
    outs, pos = [], 0
    while (i := text.find('{"status"', pos)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:  # the schema sketch line is not valid JSON
            pos = i + 1
            continue
        if "claims" in obj:
            outs.append(GeneratorOutput(**obj))
        pos = end
    return outs


def test_prompt_examples_survive_verifier():
    from ircb.answering.calc import execute_calcs
    from ircb.answering.verifier import verify_claims

    def f(fid: str, label: str, period: str, value: str) -> Any:
        return fact(
            fact_id=fid, label=label, label_norm=label.lower(), period=period,
            value=Decimal(value), unit="triệu đồng", printed_pages=[5],
        )  # fmt: skip

    facts = [
        f("a1", "Tiền gửi khách hàng", "2025", "120"),
        f("a2", "Tiền gửi khách hàng", "2024", "100"),
        f("b1", "Cho vay khách hàng", "2025", "115"),
        f("b2", "Cho vay khách hàng", "2024", "100"),
        f("t25", "Tổng tài sản", "2025", "1200"),
        f("t24", "Tổng tài sản", "2024", "1000"),
    ]
    examples = _prompt_examples()
    assert len(examples) == 3  # ex.1, ex.2 first round, ex.2 second round
    checked = 0
    for out in examples:
        if not out.claims:
            continue
        context = Context(facts=facts)
        results = execute_calcs(out.calcs, {x.fact_id: x for x in facts})
        for v in verify_claims(out.claims, context, results):
            assert v.ok, (v.text, v.failed_rule)
            checked += 1
    assert checked == 4


def test_prompt_direction_words_listed():
    p = PROMPT.read_text(encoding="utf-8").lower()
    for must in ["tăng trưởng", "suy giảm", "đi lên", "đi xuống", "không hề", "chẳng", "chưa"]:
        assert must in p, must


def test_render_generator_partial_appends_fixed_note():
    status, text, _ = render([vc(text="Một.", pages=[5])], {}, None, "partial")
    assert status == "partial"
    assert text == "Một. [tr. 5]\nMột phần câu hỏi không có thông tin trong Báo cáo thường niên 2025."


@pytest.mark.parametrize(
    ("kind", "sentence"),
    [
        ("rounding", "Số liệu tổng quan đã được làm tròn từ số kiểm toán."),
        ("definition", "Hai số liệu khác nhau do khác định nghĩa chỉ tiêu."),
        ("genuine", "Hai nguồn trong báo cáo cho số liệu khác nhau — cần kiểm tra."),
    ],
)
def test_render_conflict_fixed_sentence_ignores_model_note(kind, sentence):
    conflict = Conflict(kind=kind, note="ghi chú 9.999 tỷ đồng")
    status, text, _ = render([vc(text="Một.", pages=[5])], {}, conflict, "answered")
    assert status == "answered" and text == f"Một. [tr. 5]\n{sentence}"
    assert "9.999" not in text


def test_render_no_conflict_sentence_when_kind_none():
    _, text, _ = render([vc(text="Một.", pages=[5])], {}, Conflict(kind=None, note="x 1"), "answered")
    assert text == "Một. [tr. 5]"


def test_fact_line_shows_the_direction_of_a_reported_change():
    """Real run sq-07: without the arrow direction the model re-derived a change with a bogus calc."""
    up = fact(
        fact_id="k1_chg",
        label="Dư nợ vay",
        col_path="N/N",
        value=Decimal("26.9"),
        raw="26,9% N/N",
        unit="%",
        direction="up",
        printed_pages=[59],
    )
    line = generator._fact_line(up)
    assert line == "[fact:k1_chg] Dư nợ vay | N/N | 26,9% N/N % | chiều: tăng (tr. 59)"
    assert "chiều: giảm" in generator._fact_line(up.model_copy(update={"direction": "down"}))
    assert "chiều" not in generator._fact_line(up.model_copy(update={"direction": "unknown"}))

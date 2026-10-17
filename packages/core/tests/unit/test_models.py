from decimal import Decimal

import pytest
from ircb.domain.models import (
    Answer,
    CalcResult,
    CalcSpec,
    Chunk,
    Citation,
    ClaimOut,
    Conflict,
    Fact,
    GeneratorOutput,
    NeedFact,
    PageInfo,
    RewriteResult,
    TurnState,
    VerifiedClaim,
)
from pydantic import ValidationError


def _walk_objects(node, path="$"):
    """Yield (path, schema_dict) for every object-typed schema node."""
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            yield path, node
        for key, value in node.items():
            yield from _walk_objects(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk_objects(value, f"{path}[{i}]")


def test_rewrite_caps_lists():
    r = RewriteResult(
        standalone_query="q",
        metrics=list("abcd"),
        periods=["2025", "2024", "2023", "2022"],
        entity=None,
        needs_comparison=False,
        needs_calc=False,
        is_forecast=False,
    )
    assert r.metrics == ["a", "b", "c"]
    assert r.periods == ["2025", "2024", "2023"]


def test_generator_schema_is_strict_compatible():
    schema = GeneratorOutput.model_json_schema()
    assert set(schema["required"]) >= {"status", "claims", "calcs", "conflict", "need_fact"}


@pytest.mark.parametrize("model", [GeneratorOutput, RewriteResult])
def test_llm_schemas_are_strict(model):
    schema = model.model_json_schema()
    objects = list(_walk_objects(schema))
    assert objects
    for path, obj in objects:
        assert obj.get("additionalProperties") is False, path
        assert set(obj.get("properties", {})) == set(obj.get("required", [])), path


@pytest.mark.parametrize("model", [GeneratorOutput, RewriteResult])
def test_llm_schemas_have_no_decimal(model):
    assert "Decimal" not in str(model.model_json_schema())
    assert "number" not in str(model.model_json_schema())


def test_llm_models_forbid_extra_fields():
    with pytest.raises(ValidationError):
        NeedFact(metric="m", period=None, extra_field=1)


def test_citation_label():
    assert Citation.for_pages([374, 375]).label == "[tr. 374, 375]"


def test_citation_single_page_label():
    assert Citation.for_pages([297]).label == "[tr. 297]"


def test_citation_sorts_and_dedupes_pages():
    c = Citation.for_pages([375, 374, 375])
    assert c.printed_pages == [374, 375]
    assert c.label == "[tr. 374, 375]"


def test_citation_rejects_empty_pages():
    with pytest.raises(ValueError):
        Citation.for_pages([])


def test_fact_money_fields_are_decimal():
    f = Fact(
        fact_id="p297_t02_r14_c2",
        doc_id="tcb-ar-2025",
        printed_pages=[297],
        chapter="Báo cáo tài chính",
        statement="B02/TCTD-HN",
        note_no=None,
        table_title="Bảng",
        label="Chứng khoán nợ",
        label_norm="chung khoan no",
        parent_label=None,
        row_level=0,
        is_total=False,
        col_path="31/12/2024",
        period="2024-12-31",
        value=Decimal("-415884.000000"),
        unit="triệu đồng",
        value_vnd=Decimal("-415884000000"),
        raw="(415.884)",
        source="table",
        pdf_page=149,
        bbox=[1.0, 2.0, 3.0, 4.0],
        direction=None,
        change_basis=None,
    )
    assert isinstance(f.value, Decimal)
    assert isinstance(f.value_vnd, Decimal)


def test_fact_source_is_literal():
    with pytest.raises(ValidationError):
        Fact(
            fact_id="x",
            doc_id="d",
            printed_pages=[1],
            chapter=None,
            statement=None,
            note_no=None,
            table_title=None,
            label="l",
            label_norm="l",
            parent_label=None,
            row_level=0,
            is_total=False,
            col_path=None,
            period=None,
            value=Decimal("1"),
            unit="%",
            value_vnd=None,
            raw=None,
            source="other",
            pdf_page=1,
            bbox=[],
            direction=None,
            change_basis=None,
        )


def test_chunk_and_page_info():
    c = Chunk(
        chunk_id="p149R_t02",
        doc_id="tcb-ar-2025",
        pdf_page=149,
        half="R",
        printed_pages=[297],
        chapter="Báo cáo tài chính",
        statement="B02/TCTD-HN",
        note_no=None,
        content_type="table",
        unit="triệu đồng",
        text="| a |",
        fact_ids=["p149R_t02_r05_c2"],
        bbox=[596.0, 120.0, 1150.0, 520.0],
    )
    assert c.half == "R"
    p = PageInfo(pdf_page=1, half="S", printed_page=1, chapter=None, is_divider=True)
    assert p.is_divider is True


def test_generator_output_round_trip():
    g = GeneratorOutput(
        status="answered",
        claims=[ClaimOut(text="t", sources=["fact:p297_t02_r14_c2"], evidence="e")],
        calcs=[CalcSpec(id="c1", op="growth", a="fact:x", b="fact:y", to_unit=None)],
        conflict=Conflict(kind=None, note=""),
        need_fact=None,
    )
    assert g.claims[0].sources == ["fact:p297_t02_r14_c2"]


def test_answer_model_holds_decimal_cost():
    a = Answer(
        status="answered",
        text="t",
        claims=[VerifiedClaim(text="t", sources=[], printed_pages=[], ok=True, failed_rule=None)],
        calcs=[
            CalcResult(
                id="c1",
                ok=True,
                value=Decimal("0.1"),
                unit="%",
                rendered="10%",
                formula="a/b",
                operand_fact_ids=["x"],
                error=None,
            )
        ],
        citations=[Citation.for_pages([297])],
        conflict=None,
        state=TurnState(metrics=["m"], periods=["2025"], entity=None),
        trace_id="t1",
        latency_ms={"total": 10},
        cost_usd=Decimal("0.0012"),
    )
    assert isinstance(a.cost_usd, Decimal)
    assert a.citations[0].label == "[tr. 297]"

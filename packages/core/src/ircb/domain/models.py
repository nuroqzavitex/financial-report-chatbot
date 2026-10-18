"""Pydantic v2 domain models for ircb.

Models under the "LLM-facing" banner are sent to OpenAI structured outputs in
strict mode: every field is required (no defaults), nullable fields are
``X | None`` without a default, and ``extra="forbid"`` yields
``additionalProperties: false`` in the JSON schema. They must not contain Decimal.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

_MAX_LIST_ITEMS = 3


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Storage / index models -------------------------------------------------


class Fact(BaseModel):
    """One table cell or KPI value (spec §5.5)."""

    fact_id: str
    doc_id: str
    printed_pages: list[int]
    chapter: str | None
    statement: str | None
    note_no: str | None
    table_title: str | None
    label: str
    label_norm: str
    parent_label: str | None
    row_level: int
    is_total: bool
    col_path: str | None
    period: str | None
    value: Decimal
    unit: str
    value_vnd: Decimal | None
    raw: str | None
    source: Literal["table", "kpi"]
    pdf_page: int
    bbox: list[float]
    direction: Literal["up", "down", "unknown"] | None
    change_basis: str | None


class Chunk(BaseModel):
    """One retrievable text chunk (spec §5.6)."""

    chunk_id: str
    doc_id: str
    pdf_page: int
    half: Literal["L", "R", "S"]
    printed_pages: list[int]
    chapter: str | None
    statement: str | None
    note_no: str | None
    content_type: Literal["prose", "table", "kpi", "glossary", "figure"]
    unit: str | None
    text: str
    fact_ids: list[str]
    bbox: list[float]


class PageInfo(BaseModel):
    pdf_page: int
    half: Literal["L", "R", "S"]
    printed_page: int
    chapter: str | None
    is_divider: bool


# --- Query rewriting -------------------------------------------------------


class RewriteResult(_Strict):
    """Query rewriter output; sent to OpenAI strict mode."""

    standalone_query: str
    metrics: list[str]
    periods: list[str]
    entity: str | None
    needs_comparison: bool
    needs_calc: bool
    is_forecast: bool

    @field_validator("metrics", "periods", mode="after")
    @classmethod
    def _cap_list(cls, v: list[str]) -> list[str]:
        return v[:_MAX_LIST_ITEMS]


class TurnState(BaseModel):
    metrics: list[str]
    periods: list[str]
    entity: str | None


# --- Generator output (LLM-facing, strict) ----------------------------------


class ClaimOut(_Strict):
    text: str
    sources: list[str]
    evidence: str


class CalcSpec(_Strict):
    id: str
    op: Literal["growth", "diff", "ratio", "convert"]
    a: str
    b: str | None
    to_unit: str | None


class Conflict(_Strict):
    kind: Literal["rounding", "definition", "genuine"] | None
    note: str


class NeedFact(_Strict):
    metric: str
    period: str | None


class GeneratorOutput(_Strict):
    """Generator output; sent to OpenAI strict mode."""

    status: Literal["answered", "partial", "not_found"]
    claims: list[ClaimOut]
    calcs: list[CalcSpec]
    conflict: Conflict
    need_fact: NeedFact | None


# --- Calc / verify / answer -------------------------------------------------


class CalcResult(BaseModel):
    id: str
    ok: bool
    value: Decimal | None
    unit: str | None
    rendered: str | None
    formula: str | None
    operand_fact_ids: list[str]
    error: str | None


class VerifiedClaim(BaseModel):
    text: str
    sources: list[str]
    printed_pages: list[int]
    ok: bool
    failed_rule: str | None
    evidence: str = ""
    calc_ids: list[str] = []  # the {cN} placeholders of the claim's original text


class Citation(BaseModel):
    printed_pages: list[int]
    label: str

    @classmethod
    def for_pages(cls, pages: list[int]) -> "Citation":
        if not pages:
            raise ValueError("Citation requires at least one page")
        uniq = sorted(set(pages))
        body = ", ".join(str(p) for p in uniq)
        return cls(printed_pages=uniq, label=f"[tr. {body}]")


class Answer(BaseModel):
    status: Literal["answered", "partial", "refused", "error"]
    text: str
    claims: list[VerifiedClaim]
    calcs: list[CalcResult]
    citations: list[Citation]
    conflict: Conflict | None
    state: TurnState | None
    trace_id: str
    latency_ms: dict[str, int]
    cost_usd: Decimal

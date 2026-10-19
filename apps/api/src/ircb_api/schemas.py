"""Wire DTOs of the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints


class HealthOut(BaseModel):
    status: Literal["ok"]
    index_version: str
    doc_id: str
    n_chunks: int
    n_facts: int
    llm_model: str
    embed_model: str
    pdf_available: bool


SessionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ChatIn(BaseModel):
    session_id: SessionId | None = None
    message: Message


class SourceOut(BaseModel):
    kind: Literal["fact", "chunk"]
    id: str
    printed_pages: list[int]
    evidence: str


class ClaimOutDTO(BaseModel):
    text: str
    printed_pages: list[int]
    citation: str
    sources: list[SourceOut]


class OperandOut(BaseModel):
    fact_id: str
    label: str
    period: str | None
    raw: str | None
    value: str
    unit: str
    printed_pages: list[int]


class CalcOut(BaseModel):
    id: str
    rendered: str | None
    formula: str | None
    value: str | None
    unit: str | None
    operands: list[OperandOut]


class ChatAnswerOut(BaseModel):
    session_id: str
    status: Literal["answered", "partial", "refused", "error"]
    text: str
    claims: list[ClaimOutDTO]
    notes: list[str]
    calcs: list[CalcOut]
    conflict_kind: str | None
    trace_id: str
    latency_ms: dict[str, int]
    cost_usd: str


class StatusOut(BaseModel):
    step: str
    label: str


class MessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime
    # the answer exactly as it was sent (assistant turns stored since history was added), else None
    answer: ChatAnswerOut | None = None


class SessionOut(BaseModel):
    id: str
    title: str
    messages: list[MessageOut]


class SessionSummaryOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    n_messages: int


class SessionListOut(BaseModel):
    sessions: list[SessionSummaryOut]


class FactOut(BaseModel):
    fact_id: str
    label: str
    parent_label: str | None
    period: str | None
    value: str
    unit: str
    raw: str | None
    printed_pages: list[int]
    table_title: str | None
    statement: str | None


class ErrorOut(BaseModel):
    code: str
    message: str

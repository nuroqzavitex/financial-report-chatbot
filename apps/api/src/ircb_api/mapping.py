"""Answer -> wire DTOs. Zero leak: nothing of a claim with ``ok == False`` is ever mapped."""

from __future__ import annotations

from decimal import Decimal

from ircb.domain.models import Answer, Chunk, Citation, Fact, VerifiedClaim
from ircb.storage.fact_repo import SqlFactStore

from ircb_api.schemas import CalcOut, ChatAnswerOut, ClaimOutDTO, FactOut, OperandOut, SourceOut


def decimal_str(v: Decimal) -> str:
    """Plain positional notation, never an exponent (str(Decimal('1.1E+12')) would be '1.1E+12')."""
    return format(v, "f")


_FACT = "fact:"
_CHUNK = "chunk:"


def _sources(c: VerifiedClaim, facts: dict[str, Fact], chunks: dict[str, Chunk]) -> list[SourceOut]:
    out: list[SourceOut] = []
    for sid in c.sources:
        if sid.startswith(_FACT):
            raw_id = sid.removeprefix(_FACT)
            f = facts.get(raw_id)
            out.append(
                SourceOut(kind="fact", id=raw_id, printed_pages=f.printed_pages if f else [], evidence="")
            )
        elif sid.startswith(_CHUNK):
            raw_id = sid.removeprefix(_CHUNK)
            ch = chunks.get(raw_id)
            out.append(
                SourceOut(
                    kind="chunk", id=raw_id, printed_pages=ch.printed_pages if ch else [], evidence=c.evidence
                )
            )
    return out


def _operand(f: Fact) -> OperandOut:
    return OperandOut(
        fact_id=f.fact_id,
        label=f.label,
        period=f.period,
        raw=f.raw,
        value=decimal_str(f.value),
        unit=f.unit,
        printed_pages=f.printed_pages,
    )


def to_chat_answer(
    answer: Answer, session_id: str, facts: SqlFactStore, chunks: dict[str, Chunk]
) -> ChatAnswerOut:
    """Map an Answer for the wire.

    Relies on the renderer contract: for answered/partial, ``text`` is one line per passed claim
    (in claim order) followed by the note lines; for refused (and error) it is one fixed text.
    """
    lines = answer.text.split("\n")
    passed = [c for c in answer.claims if c.ok]
    shown = answer.status in ("answered", "partial")
    passed = passed if shown else []
    notes = lines[len(passed) :] if shown else [answer.text]
    # a calc ships only with a passed claim that used it: a failed claim's calc (its rendered
    # value and operand facts) would leak the failed claim's sources
    used = {cid for c in passed for cid in c.calc_ids}
    ok_calcs = [c for c in answer.calcs if c.ok and c.id in used]

    fact_ids = [s.removeprefix(_FACT) for c in passed for s in c.sources if s.startswith(_FACT)]
    fact_ids += [fid for calc in ok_calcs for fid in calc.operand_fact_ids]
    by_id = facts.get_many(fact_ids)

    claims = [
        ClaimOutDTO(
            text=c.text.rstrip(),
            printed_pages=c.printed_pages,
            citation=Citation.for_pages(c.printed_pages).label if c.printed_pages else "",
            sources=_sources(c, by_id, chunks),
        )
        for c in passed
    ]
    calcs = [
        CalcOut(
            id=calc.id,
            rendered=calc.rendered,
            formula=calc.formula,
            value=decimal_str(calc.value) if calc.value is not None else None,
            unit=calc.unit,
            operands=[_operand(by_id[fid]) for fid in calc.operand_fact_ids if fid in by_id],
        )
        for calc in ok_calcs
    ]
    return ChatAnswerOut(
        session_id=session_id,
        status=answer.status,
        text=answer.text,
        claims=claims,
        notes=notes,
        calcs=calcs,
        conflict_kind=answer.conflict.kind if shown and answer.conflict is not None else None,
        trace_id=answer.trace_id,
        latency_ms=answer.latency_ms,
        cost_usd=decimal_str(answer.cost_usd),
    )


def to_fact_out(f: Fact) -> FactOut:
    return FactOut(
        fact_id=f.fact_id,
        label=f.label,
        parent_label=f.parent_label,
        period=f.period,
        value=decimal_str(f.value),
        unit=f.unit,
        raw=f.raw,
        printed_pages=f.printed_pages,
        table_title=f.table_title,
        statement=f.statement,
    )

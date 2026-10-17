"""Single-call generator with one bounded ``need_fact`` recovery round (spec §5.11)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

from ircb.domain.models import Chunk, Fact, GeneratorOutput
from ircb.llm.client import LLMClient
from ircb.retrieval.hybrid import Context, FactLookup

_PROMPT_BYTES = Path(__file__).parent.joinpath("prompts", "generator.md").read_bytes()
_PROMPT = _PROMPT_BYTES.decode("utf-8")
PROMPT_VERSION = hashlib.sha256(_PROMPT_BYTES).hexdigest()[:12]
HISTORY_TURNS = 3


def _pages(pages: list[int]) -> str:
    return ", ".join(str(p) for p in pages)


def _chunk_line(c: Chunk) -> str:
    return f"[chunk:{c.chunk_id}] (tr. {_pages(c.printed_pages)}) {c.text}"


def _fact_line(f: Fact) -> str:
    shown = f.raw if f.raw is not None else str(f.value)
    head = f"[fact:{f.fact_id}] {f.label} | {f.col_path or ''}"
    # a KPI arrow is the only source of a reported change's direction; "unknown" stays unshown
    way = {"up": " | chiều: tăng", "down": " | chiều: giảm"}.get(f.direction or "", "")
    return f"{head} | {shown} {f.unit}{way} (tr. {_pages(f.printed_pages)})"


def build_messages(question: str, ctx: Context, history: list[tuple[str, str]]) -> list[dict[str, Any]]:
    parts: list[str] = []
    turns = history[-HISTORY_TURNS:]
    if turns:
        parts.append("Lịch sử hội thoại:")
        for q, a in turns:
            parts.append(f"Người dùng: {q}\nTrợ lý: {a}")
    parts.append(f"Câu hỏi: {question}")
    parts.append("Context:")
    parts.extend(_chunk_line(c) for c in ctx.chunks)
    parts.extend(_fact_line(f) for f in ctx.facts)
    return [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


def _call(
    question: str, ctx: Context, history: list[tuple[str, str]], client: LLMClient, model: str
) -> GeneratorOutput:
    out, _usage = client.complete_json(model, build_messages(question, ctx, history), GeneratorOutput)
    if not isinstance(out, GeneratorOutput):
        raise TypeError(f"expected GeneratorOutput, got {type(out).__name__}")
    return out


def generate(
    question: str,
    ctx: Context,
    history: list[tuple[str, str]],
    client: LLMClient,
    model: str,
    lookup: FactLookup,
) -> tuple[GeneratorOutput, Context, bool]:
    """One call; if ``need_fact`` is set, exactly one structured lookup and one more call."""
    out = _call(question, ctx, history, client, model)
    if out.need_fact is None:
        return out, ctx, False
    found = lookup.lookup(out.need_fact.metric, out.need_fact.period)
    have = {f.fact_id for f in ctx.facts}
    extra = [f for f in found if f.fact_id not in have]
    ctx2 = replace(ctx, facts=[*ctx.facts, *extra])
    return _call(question, ctx2, history, client, model), ctx2, True

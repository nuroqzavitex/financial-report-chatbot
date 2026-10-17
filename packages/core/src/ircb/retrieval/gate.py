"""Refusal score gate (spec §5.10)."""

from __future__ import annotations

from ircb.retrieval.hybrid import Context
from ircb.storage.vector_store import Hit


def gate_inputs(ctx: Context) -> list[Hit]:
    """The hits the gate decides on: every branch's top-1, else the first chunk and fact hit."""
    return ctx.gate_hits or [*ctx.chunk_hits[:1], *ctx.fact_hits[:1]]


def passes_gate(ctx: Context, threshold: float) -> bool:
    """True if any branch's top-1 hit has dense_score >= threshold or was found by both branches.

    Evaluated over every branch's top-1 (``gate_hits``), so display order / rewriter flags never
    change the decision. Hand-built contexts fall back to the first chunk and fact hit.
    """
    return any(
        h.branches == 2 or (h.dense_score is not None and h.dense_score >= threshold)
        for h in gate_inputs(ctx)
    )

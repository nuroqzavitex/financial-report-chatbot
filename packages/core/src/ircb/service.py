"""AnswerService: the single stateless entry point wiring guard -> rewrite -> retrieval -> answer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel

from ircb.answering.calc import execute_calcs
from ircb.answering.generator import PROMPT_VERSION, generate
from ircb.answering.guard import GuardRefusal, period_guard, post_rewrite_guard
from ircb.answering.renderer import render
from ircb.answering.rewriter import rewrite
from ircb.answering.verifier import verify_claims
from ircb.domain.models import (
    Answer,
    CalcResult,
    Citation,
    ClaimOut,
    Conflict,
    Fact,
    RewriteResult,
    TurnState,
    VerifiedClaim,
)
from ircb.llm.client import LLMClient, LLMError, Usage
from ircb.observability.tracing import Trace
from ircb.retrieval.embed import Embedder, LiteLLMEmbedBackend
from ircb.retrieval.gate import gate_inputs, passes_gate
from ircb.retrieval.glossary_expand import build_glossary
from ircb.retrieval.hybrid import Context, FactLookup, RetrievalDeps
from ircb.retrieval.prefetch import prefetch
from ircb.settings import Settings
from ircb.storage import artefacts
from ircb.storage.db import make_engine, upgrade_db
from ircb.storage.fact_repo import SqlFactStore
from ircb.storage.loader import ensure_loaded
from ircb.storage.vector_store import QdrantStore

ERROR_TEXT = "Lỗi khi gọi mô hình, vui lòng thử lại."

Status = Literal["answered", "partial", "refused", "error"]


class _Metered:
    """Wraps the LLM client for one request: usage and cost go into the trace."""

    def __init__(self, inner: LLMClient, trace: Trace) -> None:
        self._inner, self._trace = inner, trace
        self.cost = Decimal(0)

    def complete_json(
        self, model: str, messages: list[dict[str, Any]], schema: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        out, usage = self._inner.complete_json(model, messages, schema)
        self._trace.add_usage(usage)
        self.cost += usage.cost_usd
        return out, usage


@dataclass
class _Outcome:
    status: Status
    text: str
    state: TurnState | None
    claims: list[VerifiedClaim] = field(default_factory=list)
    calcs: list[CalcResult] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    conflict: Conflict | None = None


def _state_of(rw: RewriteResult) -> TurnState:
    return TurnState(metrics=list(rw.metrics), periods=list(rw.periods), entity=rw.entity)


class AnswerService:
    def __init__(
        self,
        settings: Settings,
        deps: RetrievalDeps,
        client: LLMClient,
        lookup: FactLookup,
        periods_seen: set[str],
        trace_dir: Path,
    ) -> None:
        self.settings = settings
        self.deps = deps
        self.client = client
        self.lookup = lookup
        self.periods_seen = periods_seen
        self.trace_dir = Path(trace_dir)

    @classmethod
    def from_settings(cls, settings: Settings) -> AnswerService:
        settings.ensure_dirs()
        if settings.auto_load_index:
            ensure_loaded(settings)
        manifest = artefacts.read_manifest(settings.index_dir)
        glossary = build_glossary(artefacts.read_glossary(settings.index_dir))
        engine = make_engine(settings.database_url)
        upgrade_db(engine)
        store = QdrantStore(settings)
        sql = SqlFactStore(engine)
        embedder = Embedder(
            LiteLLMEmbedBackend(settings),
            settings.embed_cache_dir,
            settings.embed_model,
            settings.embed_dimensions,
        )
        deps = RetrievalDeps(
            store=store,
            sql=sql,
            embedder=embedder,
            glossary=glossary,
            doc_id=manifest.doc_id,
            top_k=settings.top_k,
        )
        lookup = FactLookup(store, sql, embedder, glossary, manifest.doc_id)
        return cls(
            settings, deps, LLMClient(settings), lookup, set(manifest.periods_seen), settings.trace_dir
        )

    def ask(
        self,
        message: str,
        prev_state: TurnState | None = None,
        history: list[tuple[str, str]] | None = None,
    ) -> Answer:
        """Answer one question.

        Only ``LLMError`` becomes status "error"; any other exception propagates to the caller
        after the trace has been written.
        """
        started = time.perf_counter()
        trace = Trace(self.trace_dir)
        meter = _Metered(self.client, trace)
        trace.record("question", message)
        trace.record("prompt_version", PROMPT_VERSION)
        trace.record(
            "models", {"rewriter": self.settings.llm_model_small, "generator": self.settings.llm_model}
        )
        try:
            try:
                out = self._run(message, prev_state, history or [], trace, cast(LLMClient, meter))
            except LLMError as exc:
                trace.record("error", f"{type(exc).__name__}: {exc}")
                out = _Outcome("error", ERROR_TEXT, prev_state)
            trace.record("status", out.status)
        except Exception as exc:
            trace.record("error", f"{type(exc).__name__}: {exc}")
            trace.latency_ms["total"] = (time.perf_counter() - started) * 1000
            trace.write()
            raise
        trace.latency_ms["total"] = (time.perf_counter() - started) * 1000
        trace.write()
        return Answer(
            status=out.status,
            text=out.text,
            claims=out.claims,
            calcs=out.calcs,
            citations=out.citations,
            conflict=out.conflict,
            state=out.state,
            trace_id=trace.trace_id,
            latency_ms={k: int(v) for k, v in trace.latency_ms.items()},
            cost_usd=meter.cost,
        )

    @staticmethod
    def _guarded(refusal: GuardRefusal, state: TurnState | None, trace: Trace) -> _Outcome:
        trace.record("guard", refusal.reason)
        return _Outcome("refused", refusal.reason, state)

    def _cited_chunk_facts(self, claims: list[ClaimOut], ctx: Context) -> list[Fact]:
        """SQL facts of the chunks the claims cite, so the verifier can read them as part of the chunk."""
        cited = {s.partition(":")[2] for c in claims for s in c.sources if s.startswith("chunk:")}
        ids = list(dict.fromkeys(fid for ch in ctx.chunks if ch.chunk_id in cited for fid in ch.fact_ids))
        return list(self.deps.sql.get_many(ids).values()) if ids else []

    def _run(
        self,
        message: str,
        prev_state: TurnState | None,
        history: list[tuple[str, str]],
        trace: Trace,
        client: LLMClient,
    ) -> _Outcome:
        s = self.settings
        with trace.step("period_guard"):
            refusal = period_guard(message, self.periods_seen)
        if refusal is not None:
            return self._guarded(refusal, prev_state, trace)

        with trace.step("rewrite"):
            rw = rewrite(message, prev_state, client, s.llm_model_small)
        trace.record("rewrite", rw.model_dump())
        state = _state_of(rw)

        with trace.step("post_rewrite_guard"):
            refusal = post_rewrite_guard(rw, self.periods_seen)
        if refusal is not None:
            return self._guarded(refusal, prev_state, trace)

        with trace.step("prefetch"):
            ctx: Context = prefetch(rw, self.deps)
        trace.record(
            "retrieval",
            {
                "chunks": [c.chunk_id for c in ctx.chunks],
                "facts": [f.fact_id for f in ctx.facts],
                # printed pages in rank order: eval Recall@K / MRR against gold_printed_pages
                "chunk_pages": [list(c.printed_pages) for c in ctx.chunks],
                "fact_pages": [list(f.printed_pages) for f in ctx.facts],
            },
        )

        with trace.step("gate"):
            passed = passes_gate(ctx, s.refusal_threshold)
        trace.record(
            "gate",
            {
                "passed": passed,
                "threshold": s.refusal_threshold,
                # the inputs of the gate decision, so eval can re-decide it at another threshold
                "hits": [{"dense_score": h.dense_score, "branches": h.branches} for h in gate_inputs(ctx)],
            },
        )
        if not passed:
            suggest = ctx.chunks[0].printed_pages if ctx.chunks else None
            _status, text, _cits = render([], {}, None, "not_found", suggest)
            return _Outcome("refused", text, state)

        with trace.step("generate"):
            gen, ctx, recovered = generate(
                rw.standalone_query, ctx, history, client, s.llm_model, self.lookup
            )
        trace.record("retrieval_recovered", recovered)

        with trace.step("calc"):
            calcs = execute_calcs(gen.calcs, {f.fact_id: f for f in ctx.facts})
        trace.record("calcs", {cid: {"ok": c.ok, "error": c.error} for cid, c in calcs.items()})

        with trace.step("verify"):
            ctx.chunk_facts = self._cited_chunk_facts(gen.claims, ctx)
            verified = verify_claims(gen.claims, ctx, calcs)
        trace.record("verifier", [{"ok": v.ok, "failed_rule": v.failed_rule} for v in verified])

        with trace.step("render"):
            suggest = ctx.chunks[0].printed_pages if ctx.chunks else None
            status, text, citations = render(verified, calcs, gen.conflict, gen.status, suggest)
        # the model's free-text note is unverified: only the kind leaves the service
        conflict = Conflict(kind=gen.conflict.kind, note="") if gen.conflict.kind is not None else None
        return _Outcome(status, text, state, verified, list(calcs.values()), citations, conflict)

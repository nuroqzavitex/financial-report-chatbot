"""Parallel prefetch: one embed request, then chunk / table / glossary / fact branches (spec §5.10)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ircb.domain.models import Fact, RewriteResult
from ircb.retrieval.hybrid import Context, FactLookup, RetrievalDeps, chunk_from_hit, search_chunks
from ircb.storage.vector_store import Hit

MAX_METRICS = 3
MAX_PERIODS = 3
GLOSSARY_TRIGGERS = ("viết tắt", "là gì", "thuật ngữ")


def _dedupe(hits: list[Hit]) -> list[Hit]:
    seen: dict[str, Hit] = {}
    for h in hits:
        seen.setdefault(h.id, h)
    return list(seen.values())


def prefetch(rw: RewriteResult, deps: RetrievalDeps) -> Context:
    """Run all retrieval branches. needs_calc / needs_comparison only reorder chunks (tables first)."""
    query = rw.standalone_query
    metrics = rw.metrics[:MAX_METRICS]
    periods: list[str | None] = list(rw.periods[:MAX_PERIODS]) or [None]
    vecs = deps.embedder.embed([query, *metrics])  # the only embed request
    qvec, mvecs = vecs[0], vecs[1:]
    lookup = FactLookup(deps.store, deps.sql, deps.embedder, deps.glossary, deps.doc_id)
    want_glossary = any(t in query.lower() for t in GLOSSARY_TRIGGERS)

    with ThreadPoolExecutor(max_workers=8) as pool:
        general = pool.submit(search_chunks, deps, qvec, query)
        table = pool.submit(search_chunks, deps, qvec, query, {"content_type": "table"})
        gloss = (
            pool.submit(search_chunks, deps, qvec, query, {"content_type": "glossary"})
            if want_glossary
            else None
        )
        fact_jobs = [
            pool.submit(lookup.lookup_hits, m, p, None, 3, mvecs[i])
            for i, m in enumerate(metrics)
            for p in periods
        ]
        general_hits = general.result()
        table_hits = table.result()
        gloss_hits = gloss.result() if gloss else []
        fact_results = [j.result() for j in fact_jobs]

    tables_first = rw.needs_calc or rw.needs_comparison
    first, second = (table_hits, general_hits) if tables_first else (general_hits, table_hits)
    chunk_hits = _dedupe([*first, *second, *gloss_hits])

    fact_hits: list[Hit] = []
    facts: dict[str, Fact] = {}
    for hits, found in fact_results:
        fact_hits.extend(hits)
        for f in found:
            facts.setdefault(f.fact_id, f)
    tops = [b[0] for b in (general_hits, table_hits, gloss_hits) if b]
    tops += [hits[0] for hits, _ in fact_results if hits]
    return Context(
        chunks=[chunk_from_hit(h) for h in chunk_hits],
        facts=list(facts.values()),
        chunk_hits=chunk_hits,
        fact_hits=_dedupe(fact_hits),
        gate_hits=tops,
    )

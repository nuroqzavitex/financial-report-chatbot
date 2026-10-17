# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`ircb` is a Vietnamese multi-turn Q&A chatbot over the Techcombank 2025 annual report (197-page PDF of A3 spreads). Every answer cites `[tr. N]` by **printed page number**. The guiding rule is "the LLM writes sentences, code verifies them": numbers, pages, units and arithmetic are all checked in code; unsupported claims are dropped, and the answer becomes `partial` or `refused`.

The design is `docs/DESIGN.md` (a more detailed spec and the implementation plan live untracked in `docs/superpowers/`, gitignored); architecture decisions are in `docs/adr/`. Read them before changing pipeline behaviour.

## Commands

Windows host without `make`; use the `uv run` equivalents (the `Makefile` just aliases them).

```bash
uv sync                                   # install workspace (Python 3.11, single uv.lock at root)
uv run pytest                             # default suite: no API key, no Docker; PDF tests self-skip
uv run pytest packages/core/tests/unit/test_verifier.py::test_name   # single test
uv run pytest -m integration              # real Qdrant server + Postgres (docker compose up -d --wait first)
uv run ruff check .
uv run ruff format packages apps eval     # NEVER `ruff format .` at root: it rewrites code blocks in docs/*.md
uv run mypy                               # strict, covers packages/core/src/ircb
uv run lint-imports                       # ircb must not import fastapi / ircb_cli / ircb_api
```

CLI (`ircb`, typer, `apps/cli/src/ircb_cli/`): `ingest <pdf> [--out index]`, `index load [--force]`, `index reembed`, `chat`, `batch <in> --out <out.jsonl> [--concurrency N]`, `eval --split dev|test (--run | --batch-out <file>)`, `profile <pdf>`. RAGAS lives in the optional `eval` dependency group (`uv sync --group eval`).

## Hard constraints

- `data/` (the PDF and `sample_questions.json`) is confidential and gitignored. Never `git add` anything under it. Tests that need the PDF use the `requires_pdf` marker and skip when it is missing.
- `index/` (chunks, facts, vectors, `manifest.json`) is a committed artefact; `index/build/` and `var/` are not.
- All financial arithmetic uses `decimal.Decimal`; no floats in facts, calcs or the verifier. `ExactNumeric` in `storage/orm.py` stores Decimals as strings on SQLite and `NUMERIC` on Postgres.
- Page map: PDF page 1 → printed [1]; PDF page p ≥ 2 → left half 2p−2, right half 2p−1. Any mismatch fails the build.
- Fact numeric values live only in SQL. Qdrant `facts` payload holds only `fact_id, doc_id, label, period, statement, unit, text`. Point IDs are UUIDv5 of `chunk_id`/`fact_id`.
- Every Qdrant query uses `SearchParams(exact=True)` so embedded and server modes return identical top-k.
- The LLM never sees calculation results; calcs reference only `fact:<id>` or `calc:<id>`. Generator source ids are prefixed (`fact:`, `chunk:`); `Context` holds raw ids.
- No LangChain/LlamaIndex in the core. LLM and embedding calls go through LiteLLM (OpenAI strict structured outputs, `temperature=0` or `LLM_SEED`).
- Commits and PRs carry no Claude/Anthropic attribution (no `Co-Authored-By` trailer).

## Architecture

uv workspace: `packages/core` (library `ircb`), `apps/cli` (`ircb_cli`), and `eval/` (datasets plus runners, imported as a plain package via `pythonpath = ["."]`).

**Ingestion (`ircb/ingestion/`, entry `pipeline.build_index`).** PyMuPDF splits each spread into half-pages (`spread`, `layout`). Separate extractors then handle tables with row hierarchy (`tables`), KPI tiles with arrow direction read from vector graphics (`kpi`), prose, glossary and images (driven by `config/images.json`). `facts` normalizes values to Decimal plus unit (`domain/units.py`, `domain/numbers_vn.py`), and `chunking` builds chunks. The build is staged in `index/.tmp`, gated by quality checks (page map, table coverage QA in `table_qa`, every fact has a unit), and only then promoted atomically. Embeddings are cached under `var/embed_cache` keyed by sha256(text) + model + dimensions. `config/sections.json` defines the chapters and default units.

**Storage (`ircb/storage/`).** The two runtime modes run the same code and are selected by environment variables:
- grading mode: embedded Qdrant (`QDRANT_PATH`) with SQLite;
- production-local mode: Qdrant server (`QDRANT_URL`) with Postgres (`docker-compose.yml`).

`loader.ensure_loaded` loads `index/` into both stores on first run (`AUTO_LOAD_INDEX`), and reloads when either SQL or the Qdrant counts disagree with the manifest. Alembic migrations live in `storage/migrations`.

**Retrieval (`ircb/retrieval/`).** Hybrid Qdrant search: a named dense vector `dense` plus a sparse `bm25` vector (`modifier=IDF`, Vietnamese tokenizer in `tokenize_vi`), fused with RRF. `prefetch` issues one batched embed request and passes the vectors down. `FactLookup.lookup` embeds only when `dense is None`. `glossary_expand` adds glossary terms to the query. `gate.passes_gate` checks the top-1 hit of every branch against `REFUSAL_THRESHOLD`.

**Answering (`ircb/service.py` → `ircb/answering/`).** `AnswerService` is the single stateless entry point. Its pipeline runs in order:

```
period_guard → rewrite (LLM: metrics/periods/entity) → post_rewrite_guard → prefetch → passes_gate
→ generate (LLM, one call + at most one need_fact round; calcs declared in JSON as {cN} placeholders)
→ execute_calcs (Decimal) → verify_claims (fail-closed) → render
```

The verifier drops claims that fail and downgrades the answer to `partial`. The renderer never echoes the text of a failed claim and appends fixed Vietnamese sentences for partial answers and conflicts. Prompts live in `answering/prompts/*.md`. Traces are written as JSONL to `TRACE_DIR` only.

**Tests.** `packages/core/tests/` has three suites:
- `unit/`: uses the fakes in `factories.py` and in-file `Fake*` classes, never real OpenAI. `test_end_to_end.py` runs load, retrieval and answer on embedded Qdrant + SQLite.
- `golden/`: runs against the real PDF.
- `integration/`: needs real services and is deselected by default.

The verifier's adversarial set, `eval/datasets/adversarial.jsonl`, also runs as unit tests.

"""ircb command line: ingest, index load / reembed, chat, batch, eval, profile."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from ircb.ingestion.pipeline import GateError, build_index, reembed_index
from ircb.retrieval.embed import Embedder, LiteLLMEmbedBackend
from ircb.retrieval.hybrid import StalePayloadError
from ircb.service import AnswerService
from ircb.settings import Settings
from ircb.storage.artefacts import MANIFEST
from ircb.storage.loader import ManifestMismatchError, ensure_loaded, reload_index
from pydantic import ValidationError

from ircb_cli.batch import BatchInputError, run_batch
from ircb_cli.repl import run_repl

app = typer.Typer(help="ircb - annual-report Q&A", no_args_is_help=True)
index_app = typer.Typer(help="Manage the shipped index.", no_args_is_help=True)
app.add_typer(index_app, name="index")

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILE_SCRIPT = REPO_ROOT / "scripts" / "profile_pdf.py"


class Split(StrEnum):
    dev = "dev"
    test = "test"
    all = "all"


def _settings(require_llm: bool = True) -> Settings:
    """Settings from the environment; ingestion / index commands never call the LLM."""
    try:
        return Settings()
    except ValidationError as exc:
        if not require_llm:
            return Settings(llm_model="unused")
        fields = ", ".join(sorted({str(e["loc"][0]).upper() for e in exc.errors() if e["loc"]})) or "?"
        typer.echo(
            f"Invalid configuration ({fields}): set LLM_MODEL (and OPENAI_API_KEY) in .env or the "
            "environment, see .env.example.",
            err=True,
        )
        raise typer.Exit(2) from None


def _service_factory(settings: Settings) -> Any:
    return AnswerService.from_settings(settings)


def _fail(message: str, code: int = 1) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code)


def _missing_index(settings: Settings) -> typer.Exit:
    return _fail(
        f"No index at {settings.index_dir} ({MANIFEST} missing): build it with "
        f"`ircb ingest <pdf> --out {settings.index_dir}` (see README)."
    )


def _service_or_exit(settings: Settings) -> Any:
    """Build the service; known start-up failures become one line and a non-zero exit."""
    try:
        return _service_factory(settings)
    except FileNotFoundError as exc:
        if not (settings.index_dir / MANIFEST).is_file():
            raise _missing_index(settings) from None
        raise _fail(
            f"Index at {settings.index_dir} is incomplete ({exc.filename} missing): rebuild it with "
            f"`ircb ingest <pdf> --out {settings.index_dir}`."
        ) from None
    except ManifestMismatchError as exc:
        raise _fail(str(exc)) from None
    except StalePayloadError as exc:
        raise _fail(str(exc)) from None
    except RuntimeError as exc:  # e.g. embedded Qdrant folder locked by another ircb process
        raise _fail(f"Cannot open storage: {exc}") from None


def _embedder_factory(settings: Settings) -> Embedder:
    return Embedder(
        LiteLLMEmbedBackend(settings),
        settings.embed_cache_dir,
        settings.embed_model,
        settings.embed_dimensions,
    )


@app.callback()
def _root() -> None:
    """ircb - annual-report Q&A."""


@app.command()
def ingest(
    pdf: Annotated[Path, typer.Argument(help="Annual report PDF.")],
    out: Annotated[Path, typer.Option("--out", help="Output index directory.")] = Path("index"),
) -> None:
    """Build the index (extract, normalize, gates, embed) from the PDF."""
    settings = _settings(require_llm=False)
    try:
        m = build_index(pdf, out, settings)
    except GateError as exc:
        report = out / ".tmp" / "ingest_report.json"
        typer.echo(f"Build gate failed: {exc}", err=True)
        typer.echo(f"Failed report: {report}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"index {m.index_version}: {m.n_chunks} chunks, {m.n_facts} facts -> {out}")


@index_app.command("load")
def index_load(
    force: Annotated[bool, typer.Option("--force", help="Reload even if this version is loaded.")] = False,
) -> None:
    """Load index/ into SQL and Qdrant (skipped when this index version is already loaded)."""
    settings = _settings(require_llm=False)
    if not (settings.index_dir / MANIFEST).is_file():
        raise _missing_index(settings)
    try:
        r = ensure_loaded(settings, force=force)
    except ManifestMismatchError as exc:
        raise _fail(str(exc)) from None
    if r.loaded:
        typer.echo(f"loaded {r.n_chunks} chunks, {r.n_facts} facts")
    else:
        typer.echo("index already loaded (use --force to reload)")


@index_app.command("reembed")
def index_reembed() -> None:
    """Re-run only the embed stage with the current embedding settings, then fully reload."""
    settings = _settings(require_llm=False)
    if not (settings.index_dir / MANIFEST).is_file():
        raise _missing_index(settings)
    m = reembed_index(settings.index_dir, _embedder_factory(settings))
    r = reload_index(settings)  # drops and recreates both collections (dimension may have changed)
    typer.echo(
        f"re-embedded with {m.embed_model}/{m.embed_dimensions}; index {m.index_version}: "
        f"{r.n_chunks} chunks, {r.n_facts} facts loaded"
    )


@app.command()
def chat() -> None:
    """Interactive Q&A session."""
    run_repl(_service_or_exit(_settings()))


@app.command()
def batch(
    file: Annotated[Path, typer.Argument(help="JSON array or JSONL of questions.")],
    out: Annotated[Path, typer.Option("--out", help="Output JSONL.")],
    concurrency: Annotated[int, typer.Option("--concurrency", min=1)] = 1,
) -> None:
    """Answer every question of a file and write one JSON line per answer."""
    service = _service_or_exit(_settings())
    try:
        path = run_batch(file, out, service, concurrency)
    except BatchInputError as exc:
        raise _fail(str(exc), 2) from None
    except FileNotFoundError as exc:
        raise _fail(f"Input file not found: {exc.filename}", 2) from None
    typer.echo(f"wrote {path}")


def _eval_module() -> Any:
    """eval/ lives at the repo root, outside the installed packages: import it from there."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    return importlib.import_module("eval.runners.run_eval")


@app.command("eval")
def eval_cmd(
    split: Annotated[Split, typer.Option("--split", help="Dataset split to score.")] = Split.dev,
    run: Annotated[bool, typer.Option("--run", help="Answer the split with AnswerService first.")] = False,
    batch_out: Annotated[
        Path, typer.Option("--batch-out", help="Batch output JSONL (written with --run, read otherwise).")
    ] = Path("eval/reports/batch_out.jsonl"),
    dataset: Annotated[Path, typer.Option("--dataset", help="Eval dataset JSONL.")] = Path(
        "eval/datasets/own_questions.jsonl"
    ),
    out_dir: Annotated[Path, typer.Option("--out-dir", help="Writes reports/ and scoring/ here.")] = Path(
        "eval"
    ),
    concurrency: Annotated[int, typer.Option("--concurrency", min=1)] = 1,
) -> None:
    """Score a batch output against the eval set (Recall@8, refusal, unit, ops metrics)."""
    ev = _eval_module()
    if run:
        settings = _settings()
        rows = ev.select_split(ev.load_jsonl(dataset), split.value)
        questions = batch_out.with_name(batch_out.stem + ".input.jsonl")
        questions.parent.mkdir(parents=True, exist_ok=True)
        questions.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n"
        )
        run_batch(questions, batch_out, _service_or_exit(settings), concurrency)
    else:
        settings = _settings(require_llm=False)
        if not batch_out.exists():
            typer.echo(
                f"batch output not found: {batch_out} (pass --run to answer the split first)", err=True
            )
            raise typer.Exit(2)
    rep = ev.run_eval(
        dataset,
        split.value,
        out_dir,
        batch_out=batch_out,
        trace_dir=settings.trace_dir,
        index_dir=settings.index_dir,
    )
    o, r = rep.overall, rep.retrieval
    typer.echo(
        f"{o['n']} rows | citation_hit {o['citation_hit']} | refusal_ok {o['refusal_ok']} | "
        f"unit_ok {o['unit_ok']} | recall@8 {r['recall_at_8']} | mrr {r['mrr']}"
    )
    typer.echo(f"report: {rep.report_path}")
    typer.echo(f"score sheet: {rep.score_sheet_path}")


@app.command()
def profile(pdf: Annotated[Path, typer.Argument(help="Annual report PDF.")]) -> None:
    """Profile the PDF structure (scripts/profile_pdf.py)."""
    if not PROFILE_SCRIPT.exists():
        typer.echo(f"profile script not found: {PROFILE_SCRIPT}", err=True)
        raise typer.Exit(1)
    raise typer.Exit(subprocess.call([sys.executable, str(PROFILE_SCRIPT), str(pdf)]))

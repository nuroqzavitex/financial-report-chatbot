"""Batch runner: JSON array / JSONL of questions -> JSONL of answers; a bad row never aborts the run."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from ircb.domain.models import Answer, TurnState, VerifiedClaim

HISTORY_TURNS = 3


class ServiceLike(Protocol):
    def ask(
        self, message: str, prev_state: TurnState | None = None, history: list[tuple[str, str]] | None = None
    ) -> Answer: ...


def _error(row_id: Any, reason: str, turn_index: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": row_id, "status": "error", "error": reason}
    if turn_index is not None:
        out["turn_index"] = turn_index
    return out


def _claim_row(c: VerifiedClaim) -> dict[str, Any]:
    """A failed claim's text is unverified (it may hold a wrong number): never written out."""
    return c.model_dump(mode="json", exclude=None if c.ok else {"text"})


def _answer_row(row_id: Any, a: Answer, turn_index: int | None) -> dict[str, Any]:
    refused = a.status == "refused"  # nothing behind a refusal is shown, verified or not
    out: dict[str, Any] = {
        "id": row_id,
        "status": a.status,
        "answer": a.text,
        "citations": [c.model_dump(mode="json") for c in a.citations],
        "claims": [] if refused else [_claim_row(c) for c in a.claims],
        "calcs": [] if refused else [c.model_dump(mode="json") for c in a.calcs],
        "latency_ms": dict(a.latency_ms),
        "cost_usd": str(a.cost_usd),
        "trace_id": a.trace_id,
    }
    if turn_index is not None:
        out["turn_index"] = turn_index
    return out


class BatchInputError(ValueError):
    """The input file as a whole is unusable (a broken JSON array); nothing is answered."""


def _load_rows(path: Path) -> list[Any]:
    """JSON array, or JSONL where an unparsable line becomes an error marker."""
    text = path.read_text(encoding="utf-8-sig")
    if text.lstrip().startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BatchInputError(
                f"{path}: invalid JSON array (line {exc.lineno}, column {exc.colno}: {exc.msg})"
            ) from exc
        return list(data)
    rows: list[Any] = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            rows.append(_ParseError(f"line {n}: invalid JSON ({exc.msg})"))
    return rows


class _ParseError:
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _questions(row: dict[str, Any]) -> tuple[list[str], bool]:
    """Questions of a row and whether it is multi-turn; ValueError when the row is unusable."""
    if "turns" in row:
        turns = row["turns"]
        if not isinstance(turns, list) or not turns:
            raise ValueError("'turns' must be a non-empty list")
        if not all(isinstance(t, str) and t.strip() for t in turns):
            raise ValueError("every turn must be a non-empty string")
        return [t.strip() for t in turns], True
    q = row.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("missing or empty 'question'")
    return [q.strip()], False


def _run_row(row: Any, service: ServiceLike) -> list[dict[str, Any]]:
    if isinstance(row, _ParseError):
        return [_error(None, row.reason)]
    if not isinstance(row, dict):
        return [_error(None, f"row must be an object, got {type(row).__name__}")]
    row_id = row.get("id")
    if row_id is None:
        return [_error(None, "missing 'id'")]
    try:
        questions, multi = _questions(row)
    except ValueError as exc:
        return [_error(row_id, str(exc))]
    out: list[dict[str, Any]] = []
    state: TurnState | None = None
    history: list[tuple[str, str]] = []
    for i, q in enumerate(questions):
        idx = i if multi else None
        try:
            a = service.ask(q, state, history[-HISTORY_TURNS:])
        except Exception as exc:  # a batch row must never abort the run
            out.append(_error(row_id, f"{type(exc).__name__}: {exc}", idx))
            continue
        out.append(_answer_row(row_id, a, idx))
        if a.state is not None:
            state = a.state
        if a.status != "error":
            history.append((q, a.text))
    return out


def run_batch(input_path: Path, out_path: Path, service: ServiceLike, concurrency: int = 1) -> Path:
    rows = _load_rows(Path(input_path))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(lambda r: _run_row(r, service), rows))
    else:
        results = [_run_row(r, service) for r in rows]
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        for group in results:
            for line in group:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return out_path

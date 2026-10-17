"""Eval runner (spec §10.0.1, §10.4): score a batch output against the own eval set.

Reads the batch JSONL written by ``ircb batch`` / ``run_batch`` plus the trace JSONL files; it never
calls the model itself (``ircb eval --run`` produces the batch output first). Writes
``<out_dir>/reports/<ts>_<commit>.json`` and ``<out_dir>/scoring/score_sheet.csv`` for manual scoring.

Scoring rules (automatic parts of §10.0.1):
- citation_hit: every page of ``gold_printed_pages`` appears in some citation (vacuously true for
  rows without gold pages; rates are reported only over rows that have gold pages).
- refusal_ok: unanswerable -> status "refused"; answerable -> "answered" or "partial".
- unit_ok: every ``gold_values`` entry is found in the answer with a compatible number + unit; money
  units are compared in đồng at the coarser of the two precisions (1.192 nghìn tỷ == 1.192.344.137
  triệu, but != 1.192 tỷ). ``None`` when the row has no gold values.
- suggested_correct: a hint for the human scorer, never a final label.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from ircb.answering.generator import PROMPT_VERSION
from ircb.domain.numbers_vn import find_numbers, parse_vn
from ircb.domain.units import UNIT_SCALE

Suggested = Literal["yes", "partial", "no", "?"]

SCORE_SHEET_COLUMNS = [
    "id",
    "split",
    "category",
    "question",
    "gold_answer",
    "system_answer",
    "status",
    "citations",
    "citation_hit",
    "refusal_ok",
    "unit_ok",
    "suggested_correct",
    "manual_label",
    "notes",
]

RECALL_K = 8
REFUSAL_RECALL_TARGET = 0.9
FALSE_REFUSAL_MAX = 0.15

_MONEY_UNITS = sorted(UNIT_SCALE, key=len, reverse=True)  # "nghìn tỷ đồng" before "tỷ đồng" before "đồng"
_MISSING: dict[str, Any] = {"status": "missing", "answer": "", "citations": []}


@dataclass(frozen=True)
class RowScore:
    citation_hit: bool
    refusal_ok: bool
    unit_ok: bool | None
    suggested_correct: Suggested


@dataclass
class EvalReport:
    meta: dict[str, Any]
    overall: dict[str, Any]
    by_category: dict[str, dict[str, Any]]
    retrieval: dict[str, Any]
    ops: dict[str, Any]
    rows: list[dict[str, Any]] = field(default_factory=list)
    report_path: Path = Path()
    score_sheet_path: Path = Path()


# ----------------------------------------------------------------------------- io


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def load_traces(trace_dir: Path) -> dict[str, dict[str, Any]]:
    """trace_id -> trace line, from every ``*.jsonl`` file of the trace directory."""
    out: dict[str, dict[str, Any]] = {}
    d = Path(trace_dir)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.jsonl")):
        for t in load_jsonl(p):
            if isinstance(t.get("trace_id"), str):
                out[t["trace_id"]] = t
    return out


def select_split(rows: Iterable[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    if split == "all":
        return list(rows)
    return [r for r in rows if r.get("split") == split]


def final_outputs(batch: Iterable[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    """id -> the output of the last turn (multi-turn rows are scored on their final answer)."""
    best: dict[Any, dict[str, Any]] = {}
    for r in batch:
        rid = r.get("id")
        if rid is None:
            continue
        cur = best.get(rid)
        if cur is None or (r.get("turn_index") or 0) >= (cur.get("turn_index") or 0):
            best[rid] = r
    return best


# ----------------------------------------------------------------------------- scoring


def _cited_pages(out: dict[str, Any]) -> set[int]:
    pages: set[int] = set()
    for c in out.get("citations") or []:
        if isinstance(c, dict):
            pages.update(int(p) for p in c.get("printed_pages", []))
        elif isinstance(c, list | tuple):
            pages.update(int(p) for p in c)
    return pages


def _decimals(raw: str) -> int:
    num = re.sub(r"[^\d.,]", "", raw)
    return len(num.split(",", 1)[1]) if "," in num else 0


def _norm(s: str) -> str:
    return " ".join(s.replace("\xa0", " ").lower().split())


def _money_unit_at(text: str) -> str | None:
    for u in _MONEY_UNITS:
        if text.startswith(u):
            return u
    return None


def _close(a: Decimal, b: Decimal, quantum: Decimal) -> bool:
    return abs(a - b) <= quantum / 2


def value_in_answer(value: str, unit: str, answer: str) -> bool:
    """True if ``value unit`` (Vietnamese format) is stated in the answer, scale-aware for money."""
    g = abs(parse_vn(value).value)
    gd = _decimals(value)
    gu = _norm(unit)
    text = answer.replace("\xa0", " ")
    for m in find_numbers(text):
        a = abs(m.value)
        ad = _decimals(m.raw)
        after = _norm(text[m.span[1] : m.span[1] + 40])
        if gu in UNIT_SCALE:
            au = _money_unit_at(after)
            if au is None:
                continue
            gs, as_ = Decimal(UNIT_SCALE[gu]), Decimal(UNIT_SCALE[au])
            quantum = max(Decimal(1).scaleb(-gd) * gs, Decimal(1).scaleb(-ad) * as_)
            if _close(g * gs, a * as_, quantum):
                return True
            continue
        if gu == "%":
            unit_ok = m.is_percent or after.startswith("%")
        elif gu == "điểm %":
            unit_ok = after.startswith(("điểm %", "điểm phần trăm"))
        else:
            unit_ok = after.startswith(gu)
        if unit_ok and _close(g, a, max(Decimal(1).scaleb(-gd), Decimal(1).scaleb(-ad))):
            return True
    return False


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) is not None


def score_row(gold: dict[str, Any], out: dict[str, Any]) -> RowScore:
    status = str(out.get("status", "missing"))
    answer = str(out.get("answer") or "")
    answerable = bool(gold.get("answerable", True))

    gold_pages = {int(p) for p in gold.get("gold_printed_pages") or []}
    citation_hit = gold_pages <= _cited_pages(out)

    refusal_ok = status == "refused" if not answerable else status in ("answered", "partial")

    values = gold.get("gold_values") or []
    matched = [value_in_answer(v["value"], v["unit"], answer) for v in values]
    unit_ok: bool | None = all(matched) if values else None

    suggested: Suggested
    if not answerable:
        suggested = "yes" if status == "refused" else "no"
    elif status not in ("answered", "partial"):
        suggested = "no"
    elif not values:
        suggested = "?"
    else:
        direction = gold.get("direction")
        dir_ok = not direction or _has_word(answer, str(direction))
        if not any(matched):
            suggested = "no"
        elif all(matched) and dir_ok:
            suggested = "yes"
        else:
            suggested = "partial"
    return RowScore(citation_hit, refusal_ok, unit_ok, suggested)


# ----------------------------------------------------------------------------- retrieval


def retrieval_metrics(
    gold_pages: Sequence[int], trace: dict[str, Any] | None, k: int = RECALL_K
) -> tuple[float, float]:
    """(recall@k, reciprocal rank) of gold printed pages among the top-k chunks and top-k facts.

    Chunks and facts are ranked separately by the retriever; a gold page counts as retrieved when it is
    on any of the first k chunks or facts, and the rank of the first hit is the better of the two lists.
    """
    rec = (trace or {}).get("records", {}).get("retrieval") or {}
    gold = set(gold_pages)
    lists = [rec.get("chunk_pages") or [], rec.get("fact_pages") or []]
    found: set[int] = set()
    best_rank: int | None = None
    for ranked in lists:
        for i, pages in enumerate(ranked[:k], start=1):
            hit = gold & {int(p) for p in pages}
            if hit:
                found |= hit
                best_rank = i if best_rank is None else min(best_rank, i)
    recall = len(found) / len(gold) if gold else 0.0
    return recall, (1.0 / best_rank if best_rank else 0.0)


# ----------------------------------------------------------------------------- ops metrics


def _percentile(values: list[float], q: float) -> float:
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def ops_metrics(outputs: list[dict[str, Any]], traces: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ts = [traces[o["trace_id"]] for o in outputs if o.get("trace_id") in traces]
    n = len(ts)
    statuses = Counter(str(o.get("status")) for o in outputs)
    blocked: Counter[str] = Counter()
    n_claims = 0
    calc_fail: Counter[str] = Counter()
    n_calcs = 0
    steps: dict[str, list[float]] = defaultdict(list)
    cost = Decimal(0)
    recovered = 0
    for t in ts:
        rec = t.get("records", {})
        if rec.get("retrieval_recovered"):
            recovered += 1
        for v in rec.get("verifier") or []:
            n_claims += 1
            if not v.get("ok"):
                blocked[str(v.get("failed_rule"))] += 1
        for c in (rec.get("calcs") or {}).values():
            n_calcs += 1
            if not c.get("ok"):
                calc_fail[str(c.get("error"))] += 1
        for step, ms in (t.get("latency_ms") or {}).items():
            steps[step].append(float(ms))
        cost += Decimal(str((t.get("usage") or {}).get("cost_usd", "0")))
    return {
        "n_outputs": len(outputs),
        "n_traces": n,
        "status_counts": dict(statuses),
        "partial_rate": statuses["partial"] / len(outputs) if outputs else None,
        "retrieval_recovered_rate": recovered / n if n else None,
        "n_claims": n_claims,
        "blocked_claim_rate": sum(blocked.values()) / n_claims if n_claims else None,
        "blocked_claims_by_rule": dict(blocked),
        "n_calcs": n_calcs,
        "calc_fail_rate": sum(calc_fail.values()) / n_calcs if n_calcs else None,
        "calc_fail_by_error": dict(calc_fail),
        "latency_ms": {
            s: {"p50": _percentile(v, 0.5), "p95": _percentile(v, 0.95)} for s, v in sorted(steps.items())
        },
        "usd_per_query": str(cost / n) if n else None,
        "usd_total": str(cost),
    }


# ----------------------------------------------------------------------------- calibration


def calibration_rows(
    golds: list[dict[str, Any]], batch: list[dict[str, Any]], traces: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Inputs of ``calibrate_threshold``: per row, the gate's scores and what the system finally did."""
    finals = final_outputs(batch)
    rows: list[dict[str, Any]] = []
    for g in golds:
        o = finals.get(g["id"])
        if o is None:
            continue
        rec = traces.get(str(o.get("trace_id")), {}).get("records", {})
        gate = rec.get("gate")
        rows.append(
            {
                "id": g["id"],
                "answerable": bool(g.get("answerable", True)),
                "status": o.get("status"),
                "gate_passed": gate.get("passed") if gate else None,
                "gate_hits": list(gate.get("hits", [])) if gate else [],
            }
        )
    return rows


def _refused_at(row: dict[str, Any], t: float) -> bool:
    """Would the system refuse this row at threshold t?

    No gate record -> refused before the gate (period guard), independent of t. Gate fails at t ->
    refused. Gate passes at t and passed in the run -> the observed outcome (the generator may still
    refuse). Gate passes at t but failed in the run -> the generator outcome is unknown; assumed answered.
    """
    if row.get("gate_passed") is None:
        return row.get("status") == "refused"
    passes = any(
        h.get("branches") == 2 or (h.get("dense_score") is not None and h["dense_score"] >= t)
        for h in row.get("gate_hits", [])
    )
    if not passes:
        return True
    return bool(row["gate_passed"]) and row.get("status") == "refused"


def refusal_rates(rows: list[dict[str, Any]], t: float) -> tuple[float, float]:
    """(refusal recall on unanswerable rows, false refusal rate on answerable rows) at threshold t."""
    un = [r for r in rows if not r.get("answerable", True)]
    ans = [r for r in rows if r.get("answerable", True)]
    recall = sum(_refused_at(r, t) for r in un) / len(un) if un else 1.0
    false = sum(_refused_at(r, t) for r in ans) / len(ans) if ans else 0.0
    return recall, false


def calibrate_threshold(
    dev_rows: list[dict[str, Any]],
    recall_target: float = REFUSAL_RECALL_TARGET,
    max_false_refusal: float = FALSE_REFUSAL_MAX,
) -> float:
    """REFUSAL_THRESHOLD balancing refusal recall >= target and false refusal <= max on the dev set.

    Among thresholds meeting both targets (else among all), maximise recall - false refusal and take the
    middle of the best plateau for margin. Always returns a value in [0.01, 0.99].
    """
    scores = sorted(
        {
            float(h["dense_score"])
            for r in dev_rows
            for h in r.get("gate_hits", [])
            if h.get("dense_score") is not None and 0 < float(h["dense_score"]) < 1
        }
    )
    cands = {round(x / 100, 2) for x in range(1, 100)}
    cands |= set(scores)
    cands |= {(a + b) / 2 for a, b in zip(scores, scores[1:], strict=False)}
    ordered = sorted(c for c in cands if 0.01 <= c <= 0.99)
    evaluated = [(c, *refusal_rates(dev_rows, c)) for c in ordered]
    feasible = [e for e in evaluated if e[1] >= recall_target and e[2] <= max_false_refusal]
    pool = feasible or evaluated
    best = max(rec - fr for _, rec, fr in pool)
    plateau = [c for c, rec, fr in pool if rec - fr == best]
    return float(plateau[len(plateau) // 2])


# ----------------------------------------------------------------------------- report


def _git_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return r.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _index_version(index_dir: Path | None) -> str | None:
    if index_dir is None:
        return None
    p = Path(index_dir) / "manifest.json"
    if not p.exists():
        return None
    try:
        v = json.loads(p.read_text(encoding="utf-8")).get("index_version")
    except (OSError, json.JSONDecodeError):
        return None
    return str(v) if v is not None else None


def _unique(items: list[Any]) -> list[Any]:
    """Distinct JSON values in a stable (sorted) order."""
    seen = {json.dumps(i, sort_keys=True, ensure_ascii=False): i for i in items}
    return [seen[k] for k in sorted(seen)]


def _one_or_all(items: list[Any]) -> Any:
    return items[0] if len(items) == 1 else items


def _rate(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _summary(scored: list[dict[str, Any]]) -> dict[str, Any]:
    with_pages = [s for s in scored if s["gold_printed_pages"]]
    units = [s["unit_ok"] for s in scored if s["unit_ok"] is not None]
    return {
        "n": len(scored),
        "citation_hit": _rate([s["citation_hit"] for s in with_pages]),
        "refusal_ok": _rate([s["refusal_ok"] for s in scored]),
        "unit_ok": _rate(units),
        "suggested_correct": dict(Counter(s["suggested_correct"] for s in scored)),
        "missing": sum(1 for s in scored if s["status"] == "missing"),
    }


def _write_score_sheet(path: Path, scored: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SCORE_SHEET_COLUMNS)
        w.writeheader()
        for s in scored:
            w.writerow(
                {
                    "id": s["id"],
                    "split": s["split"],
                    "category": s["category"],
                    "question": s["question"],
                    "gold_answer": s["gold_answer"],
                    "system_answer": s["system_answer"],
                    "status": s["status"],
                    "citations": " ".join(s["citations"]),
                    "citation_hit": s["citation_hit"],
                    "refusal_ok": s["refusal_ok"],
                    "unit_ok": "" if s["unit_ok"] is None else s["unit_ok"],
                    "suggested_correct": s["suggested_correct"],
                    "manual_label": "",
                    "notes": s["notes"],
                }
            )


def run_eval(
    dataset: Path,
    split: str,
    out_dir: Path,
    *,
    batch_out: Path,
    trace_dir: Path,
    index_dir: Path | None = Path("index"),
    commit: str | None = None,
) -> EvalReport:
    golds = select_split(load_jsonl(dataset), split)
    ids = {g["id"] for g in golds}
    batch = [r for r in load_jsonl(batch_out) if r.get("id") in ids]
    finals = final_outputs(batch)
    traces = load_traces(trace_dir)

    scored: list[dict[str, Any]] = []
    recalls: list[float] = []
    rrs: list[float] = []
    for g in golds:
        o = finals.get(g["id"], _MISSING)
        s = score_row(g, o)
        trace = traces.get(str(o.get("trace_id")))
        pages = list(g.get("gold_printed_pages") or [])
        if pages and trace is not None:
            rc, rr = retrieval_metrics(pages, trace)
            recalls.append(rc)
            rrs.append(rr)
        notes = "missing output" if o is _MISSING else str(o.get("error") or "")
        scored.append(
            {
                "id": g["id"],
                "split": g.get("split", ""),
                "category": g.get("category", ""),
                "question": " → ".join(g["turns"]) if g.get("turns") else g.get("question", ""),
                "gold_answer": g.get("gold_answer", ""),
                "gold_printed_pages": pages,
                "system_answer": o.get("answer") or "",
                "status": o.get("status", "missing"),
                "citations": [
                    c.get("label", "") if isinstance(c, dict) else str(c) for c in o.get("citations") or []
                ],
                "trace_id": o.get("trace_id"),
                "notes": notes,
                **asdict(s),
            }
        )

    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in scored:
        by_cat[s["category"]].append(s)

    run_recs = [traces[o["trace_id"]].get("records", {}) for o in batch if o.get("trace_id") in traces]
    prompt_versions = sorted({str(r["prompt_version"]) for r in run_recs if r.get("prompt_version")})
    models = _unique([r["models"] for r in run_recs if r.get("models")])
    gate_thresholds = {
        traces[o["trace_id"]]["records"]["gate"]["threshold"]
        for o in batch
        if o.get("trace_id") in traces and "gate" in traces[o["trace_id"]].get("records", {})
    }
    dev_cal = calibration_rows([g for g in golds if g.get("split") == "dev"], batch, traces)
    suggested_threshold = calibrate_threshold(dev_cal) if any(r["gate_hits"] for r in dev_cal) else None

    commit = commit or _git_commit()
    now = datetime.now(UTC)
    meta = {
        "created_at": now.isoformat(),
        "commit": commit,
        # from the traces of the outputs being scored only (trace files also hold chats / older runs);
        # a list when the batch mixes versions, the code's PROMPT_VERSION when no trace is available
        "prompt_version": _one_or_all(prompt_versions) if prompt_versions else PROMPT_VERSION,
        "prompt_version_source": "traces" if prompt_versions else "code",
        "model": _one_or_all(models) if models else None,
        "index_version": _index_version(index_dir),
        "split": split,
        "dataset": str(dataset),
        "batch_out": str(batch_out),
        "n_rows": len(golds),
        "refusal_threshold_used": sorted(gate_thresholds),
        "suggested_refusal_threshold": suggested_threshold,
    }
    report = EvalReport(
        meta=meta,
        overall=_summary(scored),
        by_category={c: _summary(v) for c, v in sorted(by_cat.items())},
        retrieval={
            "k": RECALL_K,
            "n": len(recalls),
            "recall_at_8": sum(recalls) / len(recalls) if recalls else None,
            "mrr": sum(rrs) / len(rrs) if rrs else None,
        },
        ops=ops_metrics(batch, traces),
        rows=scored,
    )
    out_dir = Path(out_dir)
    report.report_path = out_dir / "reports" / f"{now:%Y%m%dT%H%M%SZ}_{commit}.json"
    report.score_sheet_path = out_dir / "scoring" / "score_sheet.csv"
    report.report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": report.meta,
        "overall": report.overall,
        "by_category": report.by_category,
        "retrieval": report.retrieval,
        "ops": report.ops,
        "rows": report.rows,
    }
    report.report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    _write_score_sheet(report.score_sheet_path, scored)
    return report

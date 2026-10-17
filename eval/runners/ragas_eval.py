"""RAGAS signals over an eval batch output (spec §10.1-§10.2), judged by JUDGE_MODEL.

Optional dependency group (not in core deps): ``uv sync --group eval``. ragas is imported lazily so the
rest of the eval package (and the test suite) works without it. ragas 0.2.15 is pinned because 0.3+ needs
``instructor``, whose ``rich<15`` cap conflicts with ircb-cli; ragas pulls LangChain transitively, but
this script never uses LangChain directly (``llm_factory`` builds the judge client).

Normal mode scores every answerable row of the split (refusal rows are scored separately, §10.2.5):
faithfulness, context precision / recall (with reference) and factual correctness; the per-row
``label`` ("yes"/"no") is factual correctness thresholded at ``--threshold`` and is what
``judge_agreement.py`` compares with the human score sheet.

Adversarial mode (``--adversarial eval/datasets/adversarial.jsonl``) scores each deliberately wrong claim
against its evidence with faithfulness and counts the claims the judge lets through (score >= threshold).

Usage:
    uv run python eval/runners/ragas_eval.py --judge $JUDGE_MODEL [--split dev] [--batch-out PATH]
    uv run python eval/runners/ragas_eval.py --judge $JUDGE_MODEL --adversarial PATH
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INSTALL_HINT = "ragas is not installed: run `uv sync --group eval` (pinned in the 'eval' dependency group)."


def label_for(score: float | None, threshold: float) -> str:
    if score is None:
        return ""
    return "yes" if score >= threshold else "no"


def _openai_model(judge: str) -> str:
    """LiteLLM-style ``openai/gpt-4o-mini`` -> ``gpt-4o-mini`` for the OpenAI client."""
    return judge.split("/", 1)[1] if judge.startswith("openai/") else judge


def _contexts(trace: dict[str, Any] | None, chunks: dict[str, str], facts: dict[str, str]) -> list[str]:
    rec = (trace or {}).get("records", {}).get("retrieval") or {}
    out = [chunks[c] for c in rec.get("chunks", []) if c in chunks]
    out += [facts[f] for f in rec.get("facts", []) if f in facts]
    return out


def _index_texts(index_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    chunks: dict[str, str] = {}
    facts: dict[str, str] = {}
    cp, fp = index_dir / "chunks.jsonl", index_dir / "facts.jsonl"
    if cp.exists():
        for line in cp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                c = json.loads(line)
                chunks[c["chunk_id"]] = c["text"]
    if fp.exists():
        for line in fp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                f = json.loads(line)
                facts[f["fact_id"]] = f"{f['label']} ({f.get('period')}): {f['value']} {f['unit']}"
    return chunks, facts


async def _safe(coro: Any) -> float | None:
    try:
        res = await coro
    except Exception as exc:  # one failed judge call must not lose the whole run
        print(f"judge call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    return None if res is None or res != res else float(res)  # NaN -> None


async def _score_rows(samples: list[dict[str, Any]], llm: Any, threshold: float) -> list[dict[str, Any]]:
    from ragas import SingleTurnSample
    from ragas.metrics import (
        FactualCorrectness,
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
    )

    metrics = {
        "faithfulness": Faithfulness(llm=llm),
        "context_precision": LLMContextPrecisionWithReference(llm=llm),
        "context_recall": LLMContextRecall(llm=llm),
        "factual_correctness": FactualCorrectness(llm=llm),
    }
    rows: list[dict[str, Any]] = []
    for s in samples:
        sample = SingleTurnSample(
            user_input=s["question"],
            response=s["answer"],
            retrieved_contexts=s["contexts"] or [""],
            reference=s["reference"],
        )
        scores = {name: await _safe(m.single_turn_ascore(sample)) for name, m in metrics.items()}
        rows.append(
            {"id": s["id"], "scores": scores, "label": label_for(scores["factual_correctness"], threshold)}
        )
    return rows


async def _score_adversarial(
    claims: list[dict[str, Any]], llm: Any, threshold: float
) -> list[dict[str, Any]]:
    from ragas import SingleTurnSample
    from ragas.metrics import Faithfulness

    faith = Faithfulness(llm=llm)
    rows: list[dict[str, Any]] = []
    for row in claims:
        c = row["claim"]
        sample = SingleTurnSample(
            user_input=c["text"], response=c["text"], retrieved_contexts=[c["evidence"]]
        )
        score = await _safe(faith.single_turn_ascore(sample))
        rows.append(
            {"id": row["id"], "faithfulness": score, "missed": score is not None and score >= threshold}
        )
    return rows


def _mean(xs: list[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RAGAS judge over an ircb eval batch output.")
    ap.add_argument(
        "--judge", default=os.environ.get("JUDGE_MODEL"), help="judge model (default: $JUDGE_MODEL)"
    )
    ap.add_argument("--dataset", type=Path, default=ROOT / "eval" / "datasets" / "own_questions.jsonl")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--batch-out", type=Path, default=ROOT / "eval" / "reports" / "batch_out.jsonl")
    ap.add_argument("--trace-dir", type=Path, default=Path(os.environ.get("TRACE_DIR", "./traces")))
    ap.add_argument("--index-dir", type=Path, default=Path(os.environ.get("INDEX_DIR", "./index")))
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--adversarial", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if not args.judge:
        print(
            "JUDGE_MODEL is not set: pass --judge or set JUDGE_MODEL (an OpenAI model other than LLM_MODEL).",
            file=sys.stderr,
        )
        return 2
    if args.judge == os.environ.get("LLM_MODEL"):
        print("JUDGE_MODEL must differ from LLM_MODEL (spec §10.2).", file=sys.stderr)
        return 2
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set: the RAGAS judge needs an OpenAI key.", file=sys.stderr)
        return 2
    try:
        from ragas.llms import llm_factory
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 2

    if str(ROOT) not in sys.path:  # run as a script: make the `eval` package importable
        sys.path.insert(0, str(ROOT))
    from eval.runners.run_eval import final_outputs, load_jsonl, load_traces, select_split

    llm = llm_factory(_openai_model(args.judge))
    now = datetime.now(UTC)
    out_path = args.out or ROOT / "eval" / "reports" / f"ragas_{now:%Y%m%dT%H%M%SZ}.json"
    meta = {"created_at": now.isoformat(), "judge_model": args.judge, "threshold": args.threshold}

    if args.adversarial is not None:
        rows = asyncio.run(_score_adversarial(load_jsonl(args.adversarial), llm, args.threshold))
        result: dict[str, Any] = {
            "meta": {**meta, "mode": "adversarial", "source": str(args.adversarial)},
            "n": len(rows),
            "missed": sum(r["missed"] for r in rows),
            "rows": rows,
        }
    else:
        golds = [g for g in select_split(load_jsonl(args.dataset), args.split) if g.get("answerable", True)]
        finals = final_outputs(load_jsonl(args.batch_out))
        traces = load_traces(args.trace_dir)
        chunks, facts = _index_texts(args.index_dir)
        samples = []
        for g in golds:
            o = finals.get(g["id"])
            if o is None or o.get("status") not in ("answered", "partial"):
                continue
            samples.append(
                {
                    "id": g["id"],
                    "question": " → ".join(g["turns"]) if g.get("turns") else g["question"],
                    "answer": o.get("answer", ""),
                    "reference": g["gold_answer"],
                    "contexts": _contexts(traces.get(str(o.get("trace_id"))), chunks, facts),
                }
            )
        rows = asyncio.run(_score_rows(samples, llm, args.threshold))
        result = {
            "meta": {**meta, "mode": "answers", "split": args.split, "batch_out": str(args.batch_out)},
            "aggregate": {
                k: _mean([r["scores"][k] for r in rows])
                for k in ("faithfulness", "context_precision", "context_recall", "factual_correctness")
            },
            "rows": rows,
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

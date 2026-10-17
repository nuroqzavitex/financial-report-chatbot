"""Agreement % and Cohen's kappa between the human score sheet and the thresholded RAGAS judge (§10.2).

Labels are binarised: "yes" -> correct, "partial" / "no" -> not correct. Rows without a label on either
side ("" or "?") are skipped.

Usage: python eval/runners/judge_agreement.py eval/scoring/score_sheet.csv eval/reports/ragas_<ts>.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

_YES = {"yes", "đúng", "correct"}
_NO = {"no", "partial", "sai", "một phần", "incorrect"}


def _binary(label: Any) -> bool | None:
    s = str(label or "").strip().lower()
    if s in _YES:
        return True
    if s in _NO:
        return False
    return None


def _manual(src: Path | str | list[dict[str, Any]]) -> dict[str, bool]:
    if isinstance(src, list):
        rows = src
    else:
        with Path(src).open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    out: dict[str, bool] = {}
    for r in rows:
        b = _binary(r.get("manual_label"))
        if b is not None and r.get("id"):
            out[str(r["id"])] = b
    return out


def _judge(src: Path | str | dict[str, Any] | list[dict[str, Any]]) -> dict[str, bool]:
    data: Any = json.loads(Path(src).read_text(encoding="utf-8")) if isinstance(src, Path | str) else src
    rows = data.get("rows", []) if isinstance(data, dict) else data
    out: dict[str, bool] = {}
    for r in rows:
        b = _binary(r.get("label"))
        if b is not None and r.get("id"):
            out[str(r["id"])] = b
    return out


def judge_agreement(
    manual_csv: Path | str | list[dict[str, Any]],
    ragas_json: Path | str | dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    manual, judge = _manual(manual_csv), _judge(ragas_json)
    ids = sorted(manual.keys() & judge.keys())
    n = len(ids)
    if n == 0:
        return {"agreement": 0.0, "kappa": 0.0, "n": 0}
    po = sum(manual[i] == judge[i] for i in ids) / n
    pm = sum(manual[i] for i in ids) / n
    pj = sum(judge[i] for i in ids) / n
    pe = pm * pj + (1 - pm) * (1 - pj)
    kappa = (1.0 if po == 1.0 else 0.0) if pe == 1.0 else (po - pe) / (1 - pe)
    return {"agreement": po, "kappa": kappa, "n": n}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manual_csv", type=Path)
    ap.add_argument("ragas_json", type=Path)
    args = ap.parse_args(argv)
    print(json.dumps(judge_agreement(args.manual_csv, args.ragas_json), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

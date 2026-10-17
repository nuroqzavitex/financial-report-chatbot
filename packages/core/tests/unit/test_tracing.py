import json
from decimal import Decimal
from pathlib import Path

from ircb.llm.client import Usage
from ircb.observability.logging import configure_logging
from ircb.observability.tracing import Trace


def test_trace_writes_jsonl(tmp_path: Path) -> None:
    t = Trace(tmp_path)
    with t.step("rewrite"):
        pass
    t.record("retrieval_recovered", False)
    line = json.loads(t.write().read_text().splitlines()[-1])
    assert line["trace_id"] == t.trace_id and "rewrite" in line["latency_ms"]
    assert line["records"]["retrieval_recovered"] is False


def test_trace_usage_totals_and_append(tmp_path: Path) -> None:
    t = Trace(tmp_path / "sub")
    t.add_usage(Usage(10, 5, Decimal("0.001")))
    t.add_usage(Usage(1, 2, Decimal("0.002")))
    p = t.write()
    t.write()
    lines = p.read_text().splitlines()
    assert len(lines) == 2 and p.suffix == ".jsonl"
    u = json.loads(lines[0])["usage"]
    assert u == {"prompt_tokens": 11, "completion_tokens": 7, "cost_usd": "0.003"}


def test_step_records_on_exception(tmp_path: Path) -> None:
    t = Trace(tmp_path)
    try:
        with t.step("x"):
            raise ValueError
    except ValueError:
        pass
    assert "x" in t.latency_ms


def test_configure_logging_smoke() -> None:
    configure_logging("INFO")

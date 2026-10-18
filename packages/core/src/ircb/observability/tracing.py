"""Per-request trace written as one JSONL line per day file."""

import json
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ircb.llm.client import Usage


class Trace:
    def __init__(self, trace_dir: Path, on_step: Callable[[str], None] | None = None) -> None:
        self.trace_dir = Path(trace_dir)
        self._on_step = on_step
        self.trace_id = uuid.uuid4().hex
        self.created_at = datetime.now(UTC)
        self.latency_ms: dict[str, float] = {}
        self.records: dict[str, Any] = {}
        self._prompt = 0
        self._completion = 0
        self._cost = Decimal(0)

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        if self._on_step is not None:
            try:
                self._on_step(name)
            except Exception:  # a broken listener must never break an answer
                pass
        start = time.perf_counter()
        try:
            yield
        finally:
            self.latency_ms[name] = (time.perf_counter() - start) * 1000

    def record(self, key: str, value: Any) -> None:
        self.records[key] = value

    def add_usage(self, usage: Usage) -> None:
        self._prompt += usage.prompt_tokens
        self._completion += usage.completion_tokens
        self._cost += usage.cost_usd

    def write(self) -> Path:
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        path = self.trace_dir / f"{self.created_at:%Y-%m-%d}.jsonl"
        line = {
            "trace_id": self.trace_id,
            "created_at": self.created_at.isoformat(),
            "latency_ms": self.latency_ms,
            "records": self.records,
            "usage": {
                "prompt_tokens": self._prompt,
                "completion_tokens": self._completion,
                "cost_usd": str(self._cost),
            },
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        return path

"""Structured query rewriter: standalone query + extracted slots, using previous-turn state."""

import json
from pathlib import Path
from typing import Any

from ircb.domain.models import RewriteResult, TurnState
from ircb.llm.client import LLMClient

_PROMPT_PATH = Path(__file__).parent / "prompts" / "rewriter.md"


def rewrite(question: str, prev: TurnState | None, client: LLMClient, model: str) -> RewriteResult:
    payload: dict[str, Any] = {
        "question": question,
        "previous_state": prev.model_dump() if prev is not None else None,
    }
    messages = [
        {"role": "system", "content": _PROMPT_PATH.read_text(encoding="utf-8")},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    out, _usage = client.complete_json(model, messages, RewriteResult)
    if not isinstance(out, RewriteResult):
        raise TypeError(f"expected RewriteResult, got {type(out).__name__}")
    return out

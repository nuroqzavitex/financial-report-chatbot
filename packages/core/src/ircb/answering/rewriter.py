"""Structured query rewriter: standalone query + extracted slots, using the recent turns."""

import json
from pathlib import Path
from typing import Any

from ircb.domain.models import RewriteResult, TurnState
from ircb.llm.client import LLMClient

_PROMPT_PATH = Path(__file__).parent / "prompts" / "rewriter.md"
REWRITE_TURNS = 3  # recent (question, answer) pairs the rewriter sees
ANSWER_CHARS = 300  # an answer is context for "nó" / "khối đó", not something to restate


def _clip(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= ANSWER_CHARS else one_line[: ANSWER_CHARS - 1].rstrip() + "…"


def rewrite(
    question: str,
    prev: TurnState | None,
    client: LLMClient,
    model: str,
    history: list[tuple[str, str]] | None = None,
) -> RewriteResult:
    """``history`` holds (question, answer) pairs, oldest first; the answers are the verified text
    the user was shown, so nothing a failed claim said reaches the rewriter."""
    turns = (history or [])[-REWRITE_TURNS:]
    payload: dict[str, Any] = {
        "question": question,
        "previous_state": prev.model_dump() if prev is not None else None,
        "recent_turns": [{"question": q, "answer": _clip(a)} for q, a in turns],
    }
    messages = [
        {"role": "system", "content": _PROMPT_PATH.read_text(encoding="utf-8")},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    out, _usage = client.complete_json(model, messages, RewriteResult)
    if not isinstance(out, RewriteResult):
        raise TypeError(f"expected RewriteResult, got {type(out).__name__}")
    return out

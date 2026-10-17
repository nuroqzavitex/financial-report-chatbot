"""Interactive chat REPL (prompt_toolkit input, rich output). State lives only in memory."""

from __future__ import annotations

from collections.abc import Callable

from ircb.domain.models import TurnState
from rich.console import Console
from rich.text import Text

from ircb_cli.batch import HISTORY_TURNS, ServiceLike

BANNER = "ircb chat - /reset xóa ngữ cảnh, Ctrl-D thoát."


def run_repl(
    service: ServiceLike,
    read: Callable[[], str] | None = None,
    console: Console | None = None,
) -> None:
    """Read questions until EOF. ``read`` is a test seam; by default a prompt_toolkit session."""
    console = console or Console()
    if read is None:
        from prompt_toolkit import PromptSession

        session: PromptSession[str] = PromptSession()

        def read() -> str:
            return session.prompt("ircb> ")

    console.print(Text(BANNER, style="dim"))
    state: TurnState | None = None
    history: list[tuple[str, str]] = []
    while True:
        try:
            line = read().strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            continue
        if not line:
            continue
        if line == "/reset":
            state, history = None, []
            console.print(Text("Đã xóa ngữ cảnh.", style="dim"))
            continue
        try:
            answer = service.ask(line, state, history[-HISTORY_TURNS:])
        except Exception as exc:  # keep the session alive on unexpected failures
            console.print(Text(f"Lỗi: {type(exc).__name__}: {exc}", style="red"))
            continue
        if answer.state is not None:
            state = answer.state
        if answer.status != "error":
            history = [*history, (line, answer.text)][-HISTORY_TURNS:]
        console.print(Text(answer.text))
        meta = f"[{answer.status}] {answer.latency_ms.get('total', 0)} ms, ${answer.cost_usd}"
        console.print(Text(meta, style="dim"))

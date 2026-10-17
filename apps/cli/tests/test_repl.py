import io
from collections.abc import Callable

import pytest
from cli_helpers import FakeService
from ircb_cli.repl import run_repl
from rich.console import Console


@pytest.fixture
def fake_service() -> FakeService:
    return FakeService()


def scripted(*lines: str) -> Callable[[], str]:
    it = iter(lines)

    def read() -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return read


def test_repl_keeps_state_and_reset(fake_service: FakeService) -> None:
    out = io.StringIO()
    run_repl(
        fake_service,
        read=scripted("Tổng tài sản 2025?", "", "còn năm trước?", "/reset", "lại từ đầu"),
        console=Console(file=out, width=100),
    )
    assert fake_service.questions == ["Tổng tài sản 2025?", "còn năm trước?", "lại từ đầu"]
    assert fake_service.prev_states[0] is None and fake_service.prev_states[1] is not None
    assert fake_service.prev_states[2] is None and fake_service.histories[2] == []
    assert len(fake_service.histories[1]) == 1
    assert "[tr. 5]" in out.getvalue()  # printed literally, not eaten as rich markup


def test_repl_history_capped_at_three(fake_service: FakeService) -> None:
    lines = [f"q{i}" for i in range(6)]
    run_repl(fake_service, read=scripted(*lines), console=Console(file=io.StringIO()))
    assert len(fake_service.histories[5]) == 3 and fake_service.histories[5][-1][0] == "q4"


def test_repl_survives_service_exception() -> None:
    svc = FakeService(boom=RuntimeError("x"))
    out = io.StringIO()
    run_repl(svc, read=scripted("boom", "fine"), console=Console(file=out))
    assert svc.questions == ["fine"] and "RuntimeError" in out.getvalue()

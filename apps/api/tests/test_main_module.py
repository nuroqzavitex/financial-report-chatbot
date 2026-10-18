from typing import Any

from ircb_api import __main__ as entry
from ircb_api.errors import DEFAULT_ORIGINS


def test_main_runs_uvicorn_on_settings_host_and_port(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "x")
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setenv("API_PORT", "8123")
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    entry.main()
    assert calls == [(("ircb_api.main:app",), {"host": "0.0.0.0", "port": 8123})]


def test_default_origin_before_startup_matches_settings_default():
    assert DEFAULT_ORIGINS == "http://localhost:3000,http://127.0.0.1:3000"

"""ragas_eval.py must fail fast and clearly without ragas / judge / key; no real calls in tests."""

import builtins
from typing import Any

import pytest

from eval.runners import ragas_eval


@pytest.fixture
def no_ragas(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "ragas" or name.startswith("ragas."):
            raise ImportError("No module named 'ragas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_module_does_not_import_ragas_at_top_level() -> None:
    src = (ragas_eval.__file__ and open(ragas_eval.__file__, encoding="utf-8").read()) or ""
    top = [ln for ln in src.splitlines() if ln.startswith(("import ragas", "from ragas"))]
    assert top == []


def test_missing_ragas_exits_with_message(
    no_ragas: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LLM_MODEL", "ollama_chat/gemma4:31b")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    rc = ragas_eval.main(["--judge", "openai/gpt-4o-mini"])
    assert rc == 2
    assert "uv sync --group eval" in capsys.readouterr().err


def test_missing_judge_exits_with_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LLM_MODEL", "ollama_chat/gemma4:31b")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert ragas_eval.main([]) == 2
    assert "JUDGE_MODEL" in capsys.readouterr().err


def test_missing_api_key_exits_with_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LLM_MODEL", "ollama_chat/gemma4:31b")
    assert ragas_eval.main(["--judge", "openai/gpt-4o-mini"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_label_from_score_thresholds() -> None:
    assert ragas_eval.label_for(0.8, 0.5) == "yes"
    assert ragas_eval.label_for(0.2, 0.5) == "no"
    assert ragas_eval.label_for(None, 0.5) == ""


def test_judge_equal_to_llm_model_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LLM_MODEL", "ollama_chat/gemma4:31b")
    assert ragas_eval.main(["--judge", "ollama_chat/gemma4:31b"]) == 2
    assert "differ" in capsys.readouterr().err


def test_ollama_judge_uses_the_openai_compatible_endpoint_of_ollama() -> None:
    cloud = ragas_eval.judge_client("ollama_chat/nemotron-3-ultra", "https://ollama.com/", "k", "sk")
    assert cloud == ("nemotron-3-ultra", "https://ollama.com/v1", "k")
    local = ragas_eval.judge_client("ollama_chat/gemma4:31b-cloud", "http://localhost:11434", None, None)
    assert local == ("gemma4:31b-cloud", "http://localhost:11434/v1", "ollama")
    assert ragas_eval.judge_client("openai/gpt-4o-mini", "x", "k", "sk") == ("gpt-4o-mini", None, "sk")

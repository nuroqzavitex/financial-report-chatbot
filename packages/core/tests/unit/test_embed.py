import sys
import types

from ircb.retrieval.embed import Embedder, LiteLLMEmbedBackend
from ircb.settings import Settings


class CountingBackend:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(len(t)), 1.0] for t in texts]


def test_cache_hits(tmp_path):
    be = CountingBackend()
    e = Embedder(be, tmp_path, "m", 1024)
    e.embed(["x", "y"])
    out = e.embed(["x", "z"])
    assert be.calls == [["x", "y"], ["z"]]
    assert out == [[1.0, 1.0], [1.0, 1.0]]


def test_cache_persists_and_keys_on_model(tmp_path):
    be = CountingBackend()
    Embedder(be, tmp_path, "m", 1024).embed(["x"])
    Embedder(be, tmp_path, "m", 1024).embed(["x"])
    Embedder(be, tmp_path, "m2", 1024).embed(["x"])
    assert be.calls == [["x"], ["x"]]


def test_duplicates_in_one_call(tmp_path):
    be = CountingBackend()
    out = Embedder(be, tmp_path, "m", 8).embed(["a", "a"])
    assert be.calls == [["a"]] and out[0] == out[1]


def test_litellm_backend_batches(monkeypatch):
    calls = []

    def fake_embedding(**kw):
        calls.append(kw)
        return {"data": [{"embedding": [0.5]} for _ in kw["input"]]}

    mod = types.ModuleType("litellm")
    mod.embedding = fake_embedding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", mod)
    s = Settings(llm_model="x")
    out = LiteLLMEmbedBackend(s).embed([str(i) for i in range(300)])
    assert len(out) == 300
    assert [len(c["input"]) for c in calls] == [256, 44]
    assert calls[0]["model"] == "openai/text-embedding-3-large"
    assert calls[0]["dimensions"] == 1024


def _install(monkeypatch, seq):
    calls = []

    def fake_embedding(**kw):
        calls.append(kw)
        r = seq[min(len(calls) - 1, len(seq) - 1)]
        if isinstance(r, Exception):
            raise r
        return {"data": [{"embedding": [0.5]} for _ in kw["input"]]}

    mod = types.ModuleType("litellm")
    mod.embedding = fake_embedding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", mod)
    monkeypatch.setattr("ircb.retrieval.embed.time.sleep", lambda s: None)
    return calls


class _Err(Exception):
    def __init__(self, code):
        self.status_code = code


class Timeout(_Err):
    def __init__(self):
        super().__init__(408)


def test_retry_429_then_ok(monkeypatch):
    calls = _install(monkeypatch, [_Err(429), "ok"])
    assert LiteLLMEmbedBackend(Settings(llm_model="x")).embed(["a"]) == [[0.5]]
    assert len(calls) == 2


def test_retry_timeout_408(monkeypatch):
    calls = _install(monkeypatch, [Timeout(), "ok"])
    LiteLLMEmbedBackend(Settings(llm_model="x")).embed(["a"])
    assert len(calls) == 2


def test_400_not_retried(monkeypatch):
    import pytest

    calls = _install(monkeypatch, [_Err(400), "ok"])
    with pytest.raises(_Err):
        LiteLLMEmbedBackend(Settings(llm_model="x")).embed(["a"])
    assert len(calls) == 1


def test_retries_stop(monkeypatch):
    import pytest

    calls = _install(monkeypatch, [_Err(503)])
    with pytest.raises(_Err):
        LiteLLMEmbedBackend(Settings(llm_model="x")).embed(["a"])
    assert len(calls) == 3

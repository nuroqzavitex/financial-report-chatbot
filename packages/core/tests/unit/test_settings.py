from ircb.settings import Settings


def test_defaults(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-x")
    for k in ("QDRANT_URL", "LLM_MODEL_SMALL", "TOP_K"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.embed_model == "openai/text-embedding-3-large"
    assert s.embed_dimensions == 1024
    assert s.top_k == 8
    assert s.database_url == "sqlite:///./var/app.db"
    assert s.qdrant_path == "./var/qdrant"
    assert s.qdrant_collection_prefix == "ircb_"
    assert s.llm_seed == 42
    assert s.auto_load_index is True
    assert s.llm_model_small == "openai/gpt-x"
    assert s.qdrant_mode == "embedded"


def test_server_mode(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "x")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    assert Settings(_env_file=None).qdrant_mode == "server"


def test_cors_default_allows_localhost_and_loopback(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "x")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings(_env_file=None).cors_origins.split(",") == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

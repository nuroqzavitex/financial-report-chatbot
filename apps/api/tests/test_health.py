import pytest
from fastapi.testclient import TestClient
from ircb_api.main import create_app


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["n_chunks"] == 1 and body["pdf_available"] is True
    assert body["index_version"] == "v-test"


def test_unknown_route_is_json_404(client):
    r = client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_cors_allows_web_origin(client):
    r = client.options(
        "/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_missing_index_fails_startup_with_clear_message(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "no-index"))
    monkeypatch.setenv("LLM_MODEL", "x")
    with pytest.raises(RuntimeError, match="ircb ingest"):
        with TestClient(create_app()):
            pass


def test_create_app_needs_no_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("LLM_MODEL", raising=False)
    import importlib

    import ircb_api.main as main

    importlib.reload(main)
    assert "/v1/health" in main.create_app().openapi()["paths"]

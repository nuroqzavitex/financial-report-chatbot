from fastapi.testclient import TestClient
from ircb_api.main import create_app


def test_500_from_allowed_origin_has_cors(state):
    app = create_app(state)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("x")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom", headers={"Origin": "http://localhost:3000"})
        assert r.status_code == 500 and r.json()["code"] == "internal"
        assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
        other = c.get("/boom", headers={"Origin": "http://evil.example"})
        assert other.status_code == 500 and "access-control-allow-origin" not in other.headers

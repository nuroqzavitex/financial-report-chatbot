from fastapi.testclient import TestClient
from ircb_api.main import create_app

from tests.conftest import sse_events


def test_session_history_endpoint(client):
    sid = sse_events(client.post("/v1/chat", json={"message": "Câu 1"}))[-1][1]["session_id"]
    body = client.get(f"/v1/sessions/{sid}").json()
    assert body["id"] == sid
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "Câu 1"
    assert body["messages"][1]["content"] == "Tổng tài sản đạt 1.192 nghìn tỷ đồng [tr. 5]"
    assert client.get("/v1/sessions/unknown").json()["code"] == "session_not_found"


def test_assistant_turn_never_stores_failed_claim_text(client_with_failed_claim):
    sid = sse_events(client_with_failed_claim.post("/v1/chat", json={"message": "x"}))[-1][1]["session_id"]
    raw = client_with_failed_claim.get(f"/v1/sessions/{sid}").text
    assert "SECRET" not in raw


def test_unhandled_exception_is_generic_json_500(state):
    app = create_app(state)

    @app.get("/v1/boom")
    def boom() -> None:
        raise RuntimeError("secret detail")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/v1/boom")
    assert r.status_code == 500
    assert r.json() == {"code": "internal", "message": "Lỗi máy chủ, vui lòng thử lại."}

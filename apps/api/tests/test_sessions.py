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


def _ask(client, message, session_id=None):
    body = {"message": message, **({"session_id": session_id} if session_id else {})}
    return sse_events(client.post("/v1/chat", json=body))[-1][1]["session_id"]


def test_list_shows_the_sessions_newest_first(client):
    first = _ask(client, "Câu đầu")
    second = _ask(client, "Câu thứ hai")
    body = client.get("/v1/sessions").json()
    assert [s["id"] for s in body["sessions"]] == [second, first]
    assert body["sessions"][0]["title"] == "Câu thứ hai"
    assert body["sessions"][0]["n_messages"] == 2


def test_reopened_session_carries_the_answer_as_sent(client):
    sid = _ask(client, "Tổng tài sản 2025?")
    body = client.get(f"/v1/sessions/{sid}").json()
    assert body["title"] == "Tổng tài sản 2025?"
    user, assistant = body["messages"]
    assert user["answer"] is None
    assert assistant["answer"]["status"] == "answered"
    assert assistant["answer"]["claims"][0]["citation"] == "[tr. 5]"
    assert assistant["answer"]["session_id"] == sid


def test_continuing_a_session_appends_to_it(client):
    sid = _ask(client, "Câu đầu")
    assert _ask(client, "Còn năm trước thì sao?", session_id=sid) == sid
    assert client.get("/v1/sessions").json()["sessions"][0]["n_messages"] == 4


def test_delete_removes_the_session(client):
    sid = _ask(client, "Câu sẽ xoá")
    assert client.delete(f"/v1/sessions/{sid}").status_code == 204
    assert client.get(f"/v1/sessions/{sid}").status_code == 404
    assert client.delete(f"/v1/sessions/{sid}").status_code == 404
    assert client.get("/v1/sessions").json()["sessions"] == []

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


ALICE = {"X-Client-Id": "alice-browser-0001"}
BOB = {"X-Client-Id": "bob-browser-000002"}


def _ask(client, message, headers, session_id=None):
    body = {"message": message, **({"session_id": session_id} if session_id else {})}
    return sse_events(client.post("/v1/chat", json=body, headers=headers))[-1][1]["session_id"]


def test_list_shows_only_the_callers_sessions_newest_first(client):
    first = _ask(client, "Câu đầu của Alice", ALICE)
    second = _ask(client, "Câu thứ hai của Alice", ALICE)
    _ask(client, "Câu của Bob", BOB)
    body = client.get("/v1/sessions", headers=ALICE).json()
    assert [s["id"] for s in body["sessions"]] == [second, first]
    assert body["sessions"][0]["title"] == "Câu thứ hai của Alice"
    assert body["sessions"][0]["n_messages"] == 2
    assert [s["title"] for s in client.get("/v1/sessions", headers=BOB).json()["sessions"]] == ["Câu của Bob"]


def test_reopened_session_carries_the_answer_as_sent(client):
    sid = _ask(client, "Tổng tài sản 2025?", ALICE)
    body = client.get(f"/v1/sessions/{sid}", headers=ALICE).json()
    assert body["title"] == "Tổng tài sản 2025?"
    user, assistant = body["messages"]
    assert user["answer"] is None
    assert assistant["answer"]["status"] == "answered"
    assert assistant["answer"]["claims"][0]["citation"] == "[tr. 5]"
    assert assistant["answer"]["session_id"] == sid


def test_someone_elses_session_is_not_found_everywhere(client, fake_service):
    sid = _ask(client, "Bí mật của Alice", ALICE)
    assert client.get(f"/v1/sessions/{sid}", headers=BOB).status_code == 404
    assert client.delete(f"/v1/sessions/{sid}", headers=BOB).status_code == 404
    r = client.post("/v1/chat", json={"session_id": sid, "message": "đọc trộm"}, headers=BOB)
    assert r.status_code == 404 and r.json()["code"] == "session_not_found"
    assert [c[0] for c in fake_service.calls] == ["Bí mật của Alice"]
    assert client.get(f"/v1/sessions/{sid}", headers=ALICE).status_code == 200


def test_delete_removes_the_session(client):
    sid = _ask(client, "Câu sẽ xoá", ALICE)
    assert client.delete(f"/v1/sessions/{sid}", headers=ALICE).status_code == 204
    assert client.get(f"/v1/sessions/{sid}", headers=ALICE).status_code == 404
    assert client.get("/v1/sessions", headers=ALICE).json()["sessions"] == []


def test_without_client_id_sessions_share_the_public_bucket(client):
    sid = _ask(client, "Câu công khai", {})
    assert [s["id"] for s in client.get("/v1/sessions").json()["sessions"]] == [sid]
    assert client.get("/v1/sessions", headers=ALICE).json()["sessions"] == []


def test_malformed_client_id_is_rejected(client):
    r = client.get("/v1/sessions", headers={"X-Client-Id": "short"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_client_id"

import json
import time
from concurrent.futures import ThreadPoolExecutor

import anyio
from ircb_api.main import create_app

from tests.conftest import sse_events, wait_until


def test_chat_streams_status_then_answer_then_done(client):
    events = sse_events(client.post("/v1/chat", json={"message": "Tổng tài sản 2025?"}))
    kinds = [e for e, _ in events]
    assert kinds[-2:] == ["answer", "done"] and "status" in kinds[:-2]
    ans = events[-2][1]
    assert ans["status"] == "answered" and ans["claims"][0]["citation"] == "[tr. 5]"
    assert ans["cost_usd"] == "0.0012" and isinstance(ans["session_id"], str)


def test_status_events_are_the_four_labelled_steps_in_order(client):
    events = sse_events(client.post("/v1/chat", json={"message": "Tổng tài sản 2025?"}))
    statuses = [d for e, d in events if e == "status"]
    assert statuses == [
        {"step": "rewrite", "label": "Đang hiểu câu hỏi…"},
        {"step": "prefetch", "label": "Đang tìm trong báo cáo…"},
        {"step": "generate", "label": "Đang soạn câu trả lời…"},
        {"step": "verify", "label": "Đang kiểm tra số liệu…"},
    ]
    done = events[-1][1]
    assert done == {"session_id": events[-2][1]["session_id"], "trace_id": "t-1"}


def test_failed_claim_never_leaves_the_api(client_with_failed_claim):
    # answer has one ok claim + one ok=False claim whose text is "SECRET 9.999 nghìn tỷ"
    events = sse_events(client_with_failed_claim.post("/v1/chat", json={"message": "x"}))
    raw = json.dumps(events, ensure_ascii=False)
    assert "SECRET" not in raw and "9.999" not in raw
    ans = events[-2][1]
    assert ans["status"] == "partial" and len(ans["claims"]) == 1
    assert ans["notes"] == ["Chưa xác minh được một phần nội dung, xem [tr. 7]."]


def test_follow_up_uses_session_history_and_state(client, fake_service):
    sid = sse_events(client.post("/v1/chat", json={"message": "Câu 1"}))[-1][1]["session_id"]
    sse_events(client.post("/v1/chat", json={"session_id": sid, "message": "Câu 2"}))
    _, prev_state, history = fake_service.calls[-1]
    assert history == [("Câu 1", fake_service.answers[0].text)] and prev_state is not None


def test_first_turn_has_no_history_or_state(client, fake_service):
    sse_events(client.post("/v1/chat", json={"session_id": "fresh", "message": "Câu 1"}))
    assert fake_service.calls[-1] == ("Câu 1", None, [])


def test_history_is_capped_at_history_turns(client, fake_service):
    for i in range(5):
        sse_events(client.post("/v1/chat", json={"session_id": "long", "message": f"Câu {i}"}))
    _, _, history = fake_service.calls[-1]
    assert [q for q, _ in history] == ["Câu 1", "Câu 2", "Câu 3"]


def test_error_answer_not_persisted(client_error):
    sid = "s-err"
    ev = sse_events(client_error.post("/v1/chat", json={"session_id": sid, "message": "x"}))
    assert ev[-2][1]["status"] == "error"
    assert client_error.get(f"/v1/sessions/{sid}").status_code == 404  # nothing was appended


def test_worker_exception_becomes_error_event_and_releases_lock(client_raising, fake_service, state):
    ev = sse_events(client_raising.post("/v1/chat", json={"session_id": "s-x", "message": "x"}))
    assert ev[-1] == ("error", {"code": "internal", "message": "Lỗi máy chủ, vui lòng thử lại."})
    assert "answer" not in [e for e, _ in ev]
    assert not state.sessions.exists("s-x") and not state.lock.locked()
    fake_service.exc = None
    ev = sse_events(client_raising.post("/v1/chat", json={"session_id": "s-x", "message": "y"}))
    assert [e for e, _ in ev][-2:] == ["answer", "done"]


def test_invalid_input(client):
    assert client.post("/v1/chat", json={"message": "   "}).status_code == 422
    assert client.post("/v1/chat", json={"message": "x" * 2001}).status_code == 422
    assert client.post("/v1/chat", json={"session_id": "../x", "message": "a"}).status_code == 422


def test_concurrent_chats_are_serialized(slow_client, fake_service):
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(lambda m: sse_events(slow_client.post("/v1/chat", json={"message": m})), ["a", "b"]))
    assert fake_service.max_concurrent == 1 and len(fake_service.calls) == 2


def test_client_disconnect_still_persists(slow_client, state):
    with slow_client.stream("POST", "/v1/chat", json={"session_id": "s-dc", "message": "a"}) as r:
        next(r.iter_lines())  # read the first frame, then drop the connection
    wait_until(lambda: len(state.sessions.messages("s-dc")) == 2)
    wait_until(lambda: not state.lock.locked())


def test_real_disconnect_mid_stream_persists_and_frees_lock(state, fake_service):
    """TestClient buffers whole responses: drive the ASGI app and disconnect after the first frame."""
    fake_service.delay = 0.3
    app = create_app(state)
    app.state.ircb = state  # no lifespan here
    sent: list[dict] = []
    body = json.dumps({"session_id": "s-raw", "message": "a"}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat",
        "raw_path": b"/v1/chat",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"host", b"test")],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }

    async def main() -> float:
        first_frame = anyio.Event()
        pending = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive() -> dict:
            if pending:
                return pending.pop(0)
            await first_frame.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            sent.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                first_frame.set()

        start = time.monotonic()
        with anyio.fail_after(5):
            await app(scope, receive, send)
        return time.monotonic() - start

    elapsed = anyio.run(main)
    frames = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b"event: status" in frames and b"event: answer" not in frames  # really cut mid-stream
    assert elapsed < 0.3  # the response ended on disconnect, without waiting for the worker
    wait_until(lambda: len(state.sessions.messages("s-raw")) == 2)
    wait_until(lambda: not state.lock.locked())

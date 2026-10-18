"""POST /v1/chat: Server-Sent Events with step status, then the verified answer once."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

import anyio.to_thread
from fastapi import APIRouter, Depends
from ircb.answering.generator import HISTORY_TURNS
from ircb.storage.session_repo import StoredMessage
from pydantic import BaseModel
from sse_starlette import EventSourceResponse, ServerSentEvent

from ircb_api.errors import INTERNAL_MESSAGE
from ircb_api.mapping import to_chat_answer
from ircb_api.schemas import ChatAnswerOut, ChatIn, StatusOut
from ircb_api.state import AppState, get_state

log = logging.getLogger(__name__)
router = APIRouter()

STEP_LABELS = {
    "rewrite": "Đang hiểu câu hỏi…",
    "prefetch": "Đang tìm trong báo cáo…",
    "generate": "Đang soạn câu trả lời…",
    "verify": "Đang kiểm tra số liệu…",
}

# Workers outlive a disconnected stream; keep a reference so they are not garbage collected.
_workers: set[asyncio.Task[None]] = set()


def _history(messages: list[StoredMessage]) -> list[tuple[str, str]]:
    """The last HISTORY_TURNS (user, assistant) pairs, oldest first."""
    pairs: list[tuple[str, str]] = []
    for prev, cur in zip(messages, messages[1:], strict=False):
        if prev.role == "user" and cur.role == "assistant":
            pairs.append((prev.content, cur.content))
    return pairs[-HISTORY_TURNS:]


def _event(name: str, data: BaseModel | dict[str, str]) -> ServerSentEvent:
    body = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data, ensure_ascii=False)
    return ServerSentEvent(event=name, data=body)


_Item = tuple[str, BaseModel | None]


class _Emit:
    """Thread-safe push onto the stream's queue; a no-op once the event loop is gone."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[_Item]) -> None:
        self._loop = loop
        self._queue = queue

    def __call__(self, item: _Item) -> None:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except RuntimeError:  # loop closed: the client is long gone
            pass


def _run_turn(st: AppState, sid: str, message: str, emit: _Emit) -> ChatAnswerOut:
    """Worker thread: one turn under the global lock. Persistence happens here, after ``ask``,
    so a client disconnect cannot skip it; an error answer is not persisted."""
    with st.lock:
        history = _history(st.sessions.messages(sid))
        prev_state = st.sessions.last_state(sid)

        def on_step(name: str) -> None:
            label = STEP_LABELS.get(name)
            if label is not None:
                emit(("status", StatusOut(step=name, label=label)))

        answer = st.service.ask(message, prev_state=prev_state, history=history, on_step=on_step)
        if answer.status != "error":
            st.sessions.append(sid, "user", message, None)
            st.sessions.append(sid, "assistant", answer.text, answer.state)
        return to_chat_answer(answer, sid, st.facts, st.chunks)


async def _stream(st: AppState, sid: str, message: str) -> AsyncIterator[ServerSentEvent]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[_Item] = asyncio.Queue()
    emit = _Emit(loop, queue)

    async def worker() -> None:
        try:
            out = await anyio.to_thread.run_sync(_run_turn, st, sid, message, emit)
        except Exception:
            log.exception("chat turn failed (session %s)", sid)
            queue.put_nowait(("error", None))
        else:
            queue.put_nowait(("answer", out))

    task = asyncio.create_task(worker())
    _workers.add(task)
    task.add_done_callback(_workers.discard)

    while True:
        kind, data = await queue.get()
        if kind == "status" and data is not None:
            yield _event("status", data)
        elif kind == "answer" and isinstance(data, ChatAnswerOut):
            yield _event("answer", data)
            yield _event("done", {"session_id": sid, "trace_id": data.trace_id})
            return
        else:
            yield _event("error", {"code": "internal", "message": INTERNAL_MESSAGE})
            return


@router.post(
    "/chat",
    response_class=EventSourceResponse,
    responses={200: {"model": ChatAnswerOut, "content": {"text/event-stream": {}}}},
)
async def chat(body: ChatIn, st: Annotated[AppState, Depends(get_state)]) -> EventSourceResponse:
    sid = body.session_id or uuid4().hex
    return EventSourceResponse(_stream(st, sid, body.message))

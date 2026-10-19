"""/v1/sessions: the caller's conversations (list, open, delete); someone else's is a 404."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from ircb.storage.session_repo import StoredMessage

from ircb_api.errors import ApiError
from ircb_api.owner import get_owner
from ircb_api.schemas import ChatAnswerOut, MessageOut, SessionListOut, SessionOut, SessionSummaryOut
from ircb_api.state import AppState, get_state

router = APIRouter()


def _not_found() -> ApiError:
    return ApiError(404, "session_not_found", "Không tìm thấy phiên hội thoại.")


def _message(m: StoredMessage) -> MessageOut:
    answer = ChatAnswerOut.model_validate_json(m.payload) if m.payload else None
    return MessageOut(role=m.role, content=m.content, created_at=m.created_at, answer=answer)


@router.get("/sessions", response_model=SessionListOut)
def list_sessions(
    st: Annotated[AppState, Depends(get_state)],
    owner: Annotated[str, Depends(get_owner)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SessionListOut:
    rows = st.sessions.list_sessions(owner, limit)
    return SessionListOut(sessions=[SessionSummaryOut(**r.model_dump()) for r in rows])


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    st: Annotated[AppState, Depends(get_state)],
    owner: Annotated[str, Depends(get_owner)],
) -> SessionOut:
    summary = st.sessions.get(session_id, owner)
    if summary is None:
        raise _not_found()
    msgs = [_message(m) for m in st.sessions.messages(session_id)]
    return SessionOut(id=session_id, title=summary.title, messages=msgs)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    st: Annotated[AppState, Depends(get_state)],
    owner: Annotated[str, Depends(get_owner)],
) -> Response:
    with st.lock:  # never delete under a turn that is still writing to the session
        if not st.sessions.owned_by(session_id, owner):
            raise _not_found()
        st.sessions.delete(session_id)
    return Response(status_code=204)

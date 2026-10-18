"""GET /v1/sessions/{id}: the stored conversation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ircb_api.errors import ApiError
from ircb_api.schemas import MessageOut, SessionOut
from ircb_api.state import AppState, get_state

router = APIRouter()


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, st: Annotated[AppState, Depends(get_state)]) -> SessionOut:
    if not st.sessions.exists(session_id):
        raise ApiError(404, "session_not_found", "Không tìm thấy phiên hội thoại.")
    msgs = [
        MessageOut(role=m.role, content=m.content, created_at=m.created_at)
        for m in st.sessions.messages(session_id)
    ]
    return SessionOut(id=session_id, messages=msgs)

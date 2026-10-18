"""Conversation persistence: sessions and messages with structured turn state."""

from datetime import datetime

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy import Engine

from ircb.domain.models import TurnState
from ircb.storage.db import session_scope
from ircb.storage.orm import ChatSession, Message


class StoredMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class SessionRepo:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, session_id: str, role: str, content: str, state: TurnState | None) -> None:
        with session_scope(self._engine) as s:
            if s.get(ChatSession, session_id) is None:
                s.add(ChatSession(id=session_id))
                s.flush()
            s.add(
                Message(
                    session_id=session_id,
                    role=role,
                    content=content,
                    state_json=state.model_dump_json() if state is not None else None,
                )
            )

    def last_state(self, session_id: str) -> TurnState | None:
        with session_scope(self._engine) as s:
            raw = s.execute(
                sa.select(Message.state_json)
                .where(Message.session_id == session_id, Message.state_json.is_not(None))
                .order_by(Message.id.desc())
                .limit(1)
            ).scalar_one_or_none()
        return TurnState.model_validate_json(raw) if raw else None

    def messages(self, session_id: str) -> list[StoredMessage]:
        with session_scope(self._engine) as s:
            rows = s.execute(
                sa.select(Message.role, Message.content, Message.created_at)
                .where(Message.session_id == session_id)
                .order_by(Message.id)
            ).all()
        return [StoredMessage(role=r, content=c, created_at=t) for r, c, t in rows]

    def exists(self, session_id: str) -> bool:
        with session_scope(self._engine) as s:
            return s.get(ChatSession, session_id) is not None

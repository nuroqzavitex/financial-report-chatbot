"""Conversation persistence: sessions and messages with structured turn state."""

import sqlalchemy as sa
from sqlalchemy import Engine

from ircb.domain.models import TurnState
from ircb.storage.db import session_scope
from ircb.storage.orm import ChatSession, Message


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

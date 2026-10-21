"""Conversation persistence: sessions and messages with structured turn state.

Single user: every session is listed to whoever runs the app (no sign-in, no owners).
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy import Engine

from ircb.domain.models import TurnState
from ircb.storage.db import session_scope
from ircb.storage.orm import ChatSession, Message

TITLE_CHARS = 80


class StoredMessage(BaseModel):
    role: str
    content: str
    created_at: datetime
    payload: str | None = None


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    n_messages: int


def _title(question: str) -> str:
    one_line = " ".join(question.split())
    return one_line if len(one_line) <= TITLE_CHARS else one_line[: TITLE_CHARS - 1].rstrip() + "…"


def _utc(t: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything stored is UTC."""
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


class SessionRepo:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        state: TurnState | None,
        payload: str | None = None,
    ) -> None:
        """Add a message; the first one creates the session, the first question titles it."""
        now = datetime.now(UTC)
        with session_scope(self._engine) as s:
            chat = s.get(ChatSession, session_id)
            if chat is None:
                chat = ChatSession(id=session_id, created_at=now)
                s.add(chat)
                s.flush()
            if chat.title is None and role == "user":
                chat.title = _title(content)
            chat.updated_at = now
            s.add(
                Message(
                    session_id=session_id,
                    role=role,
                    content=content,
                    state_json=state.model_dump_json() if state is not None else None,
                    payload_json=payload,
                    created_at=now,
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
                sa.select(Message.role, Message.content, Message.created_at, Message.payload_json)
                .where(Message.session_id == session_id)
                .order_by(Message.id)
            ).all()
        return [StoredMessage(role=r, content=c, created_at=_utc(t), payload=p) for r, c, t, p in rows]

    def exists(self, session_id: str) -> bool:
        with session_scope(self._engine) as s:
            return s.get(ChatSession, session_id) is not None

    def get(self, session_id: str) -> SessionSummary | None:
        """The summary of session ``session_id``; None if missing."""
        found = self._summaries(session_id=session_id, limit=1)
        return found[0] if found else None

    def list_sessions(self, limit: int = 50) -> list[SessionSummary]:
        """All sessions, most recently updated first."""
        return self._summaries(session_id=None, limit=limit)

    def _summaries(self, session_id: str | None, limit: int) -> list[SessionSummary]:
        n = sa.select(sa.func.count(Message.id)).where(Message.session_id == ChatSession.id).scalar_subquery()
        last = sa.func.coalesce(ChatSession.updated_at, ChatSession.created_at)
        q = sa.select(ChatSession.id, ChatSession.title, ChatSession.created_at, last, n)
        if session_id is not None:
            q = q.where(ChatSession.id == session_id)
        with session_scope(self._engine) as s:
            rows = s.execute(q.order_by(last.desc(), ChatSession.id).limit(limit)).all()
        return [
            SessionSummary(id=i, title=t or "", created_at=_utc(c), updated_at=_utc(u), n_messages=k)
            for i, t, c, u, k in rows
        ]

    def delete(self, session_id: str) -> None:
        with session_scope(self._engine) as s:
            s.execute(sa.delete(Message).where(Message.session_id == session_id))
            s.execute(sa.delete(ChatSession).where(ChatSession.id == session_id))

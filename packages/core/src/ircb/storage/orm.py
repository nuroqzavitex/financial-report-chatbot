"""SQLAlchemy 2.0 ORM declarations (spec 5.5, 4.3). Portable: no Postgres-only features."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, TypeEngine


class ExactNumeric(TypeDecorator[Decimal]):
    """NUMERIC(p, s) that stays exact on SQLite (stored as TEXT) and is native NUMERIC elsewhere."""

    impl = sa.Numeric
    cache_ok = True

    def __init__(self, precision: int, scale: int) -> None:
        super().__init__(precision=precision, scale=scale, asdecimal=True)
        self._precision = precision
        self._scale = scale

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(sa.String(64))
        return dialect.type_descriptor(sa.Numeric(self._precision, self._scale, asdecimal=True))

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        value = Decimal(value)
        return str(value) if dialect.name == "sqlite" else value

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    title: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class IndexVersion(Base):
    __tablename__ = "index_versions"

    index_version: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    loaded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)


class FactRow(Base):
    __tablename__ = "facts"
    __table_args__ = (sa.Index("ix_facts_lookup", "doc_id", "statement", "note_no", "period"),)

    fact_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    doc_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    printed_pages: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    chapter: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    statement: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    note_no: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    table_title: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    label: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    label_norm: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    parent_label: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    row_level: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    is_total: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    col_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    period: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    value: Mapped[Decimal | None] = mapped_column(ExactNumeric(38, 6), nullable=True)
    unit: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    value_vnd: Mapped[Decimal | None] = mapped_column(ExactNumeric(38, 0), nullable=True)
    raw: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    pdf_page: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    bbox: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    direction: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    change_basis: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class ChatSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)
    title: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(sa.ForeignKey("sessions.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    state_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # opaque JSON the caller stores with the message (the API keeps the answer it sent)
    payload_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)

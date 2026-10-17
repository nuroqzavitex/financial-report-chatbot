"""SQL-backed fact store: converts between the ``Fact`` domain model and ``FactRow``."""

import json
from collections.abc import Iterator, Sequence
from typing import Any, TypeVar

import sqlalchemy as sa
from sqlalchemy import Engine

from ircb.domain.models import Fact
from ircb.storage.db import session_scope
from ircb.storage.orm import FactRow

_BATCH = 500
_T = TypeVar("_T")


def _batches(items: Sequence[_T]) -> Iterator[Sequence[_T]]:
    for i in range(0, len(items), _BATCH):
        yield items[i : i + _BATCH]


def _to_columns(f: Fact) -> dict[str, Any]:
    d = f.model_dump()
    d["printed_pages"] = ",".join(str(p) for p in f.printed_pages)
    d["bbox"] = json.dumps(f.bbox)
    return d


def _to_fact(r: FactRow) -> Fact:
    pages = [int(p) for p in r.printed_pages.split(",") if p] if r.printed_pages else []
    return Fact.model_validate(
        {
            **{c.name: getattr(r, c.name) for c in FactRow.__table__.columns},
            "printed_pages": pages,
            "bbox": json.loads(r.bbox) if r.bbox else [],
        }
    )


class SqlFactStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_many(self, ids: list[str]) -> dict[str, Fact]:
        out: dict[str, Fact] = {}
        if not ids:
            return out
        with session_scope(self._engine) as s:
            for batch in _batches(list(dict.fromkeys(ids))):
                rows = s.execute(sa.select(FactRow).where(FactRow.fact_id.in_(batch))).scalars()
                for r in rows:
                    out[r.fact_id] = _to_fact(r)
        return out

    def upsert(self, facts: list[Fact]) -> None:
        """Idempotent merge by ``fact_id`` (last write wins), in batches of 500."""
        with session_scope(self._engine) as s:
            for batch in _batches(list({f.fact_id: f for f in facts}.values())):
                ids = [f.fact_id for f in batch]
                existing = {
                    r.fact_id: r
                    for r in s.execute(sa.select(FactRow).where(FactRow.fact_id.in_(ids))).scalars()
                }
                for f in batch:
                    cols = _to_columns(f)
                    row = existing.get(f.fact_id)
                    if row is None:
                        s.add(FactRow(**cols))
                    else:
                        for k, v in cols.items():
                            setattr(row, k, v)
                s.flush()

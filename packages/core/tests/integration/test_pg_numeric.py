"""ExactNumeric on PostgreSQL: NUMERIC(38,6) / NUMERIC(38,0) round-trip Decimals exactly."""

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
import sqlalchemy as sa
from factories import fact
from ircb.storage.db import make_engine, upgrade_db
from ircb.storage.fact_repo import SqlFactStore
from sqlalchemy import Engine

pytestmark = pytest.mark.integration

DOC = "it-numeric-doc"


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_engine(pg_db)
    upgrade_db(eng)
    yield eng
    eng.dispose()


def test_decimal_roundtrip_exact(engine: Engine) -> None:
    u = uuid.uuid4().hex[:8]
    big_frac = Decimal("1192344137.123456")
    big_int = Decimal("1192344137000000")
    store = SqlFactStore(engine)
    store.upsert(
        [
            fact(fact_id=f"{u}-a", doc_id=DOC, value=big_frac, value_vnd=Decimal("1192344137")),
            fact(fact_id=f"{u}-b", doc_id=DOC, value=Decimal("1192.344137"), value_vnd=big_int),
        ]
    )
    got = store.get_many([f"{u}-a", f"{u}-b"])
    assert got[f"{u}-a"].value == big_frac and str(got[f"{u}-a"].value) == "1192344137.123456"
    assert got[f"{u}-b"].value_vnd == big_int
    with engine.connect() as c:
        types = dict(
            c.execute(
                sa.text(
                    "select column_name, data_type || ':' || numeric_precision || ',' || numeric_scale "
                    "from information_schema.columns where table_name='facts' "
                    "and column_name in ('value','value_vnd')"
                )
            ).all()
        )
    assert types == {"value": "numeric:38,6", "value_vnd": "numeric:38,0"}

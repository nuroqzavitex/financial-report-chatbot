from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from factories import fact
from ircb.domain.models import TurnState
from ircb.storage.db import make_engine, session_scope, upgrade_db
from ircb.storage.fact_repo import SqlFactStore
from ircb.storage.orm import Base
from ircb.storage.session_repo import SessionRepo
from sqlalchemy.engine import Engine


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    upgrade_db(eng)
    return eng


def count_rows(engine: Engine, table: str) -> int:
    with session_scope(engine) as s:
        return int(s.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def test_fact_decimal_roundtrip(engine: Engine) -> None:
    s = SqlFactStore(engine)
    s.upsert([fact(fact_id="f1", value=Decimal("1192344137"), unit="triệu đồng")])
    assert s.get_many(["f1"])["f1"].value == Decimal("1192344137")


def test_decimal_exact_beyond_float(engine: Engine) -> None:
    s = SqlFactStore(engine)
    v, vnd = Decimal("1192344137.123456"), Decimal("1192344137000000")
    s.upsert([fact(fact_id="f1", value=v, value_vnd=vnd), fact(fact_id="f2", value_vnd=None)])
    got = s.get_many(["f1", "f2"])
    assert got["f1"].value == v and got["f1"].value_vnd == vnd
    assert got["f2"].value_vnd is None


def test_fact_full_roundtrip(engine: Engine) -> None:
    f = fact(
        fact_id="f1",
        printed_pages=[374, 375],
        bbox=[1.5, 2.25, 3.0, 4.0],
        is_total=True,
        direction="up",
        change_basis="N/N",
        label="Cho vay",
        raw="(415.884)",
    )
    SqlFactStore(engine).upsert([f])
    assert SqlFactStore(engine).get_many(["f1"])["f1"] == f


def test_upsert_idempotent_and_updates(engine: Engine) -> None:
    s = SqlFactStore(engine)
    s.upsert([fact(fact_id="f1")])
    s.upsert([fact(fact_id="f1", value=Decimal(7))])
    assert count_rows(engine, "facts") == 1
    assert s.get_many(["f1"])["f1"].value == Decimal(7)


def test_upsert_batches_and_missing_ids(engine: Engine) -> None:
    s = SqlFactStore(engine)
    s.upsert([fact(fact_id=f"f{i}") for i in range(1200)])
    assert count_rows(engine, "facts") == 1200
    assert s.get_many(["f5", "nope"]).keys() == {"f5"}
    assert s.get_many([]) == {}
    assert len(s.get_many([f"f{i}" for i in range(1200)])) == 1200


def test_last_state(engine: Engine) -> None:
    r = SessionRepo(engine)
    r.append("s", "user", "q", TurnState(metrics=["tổng tài sản"], periods=["2025"], entity=None))
    assert r.last_state("s") is not None
    assert r.last_state("s").periods == ["2025"]  # type: ignore[union-attr]


def test_last_state_latest_with_state(engine: Engine) -> None:
    r = SessionRepo(engine)
    assert r.last_state("s") is None
    r.append("s", "user", "q1", TurnState(metrics=["a"], periods=["2024"], entity="x"))
    r.append("s", "assistant", "a1", TurnState(metrics=["b"], periods=["2025"], entity=None))
    r.append("s", "user", "q2", None)
    st = r.last_state("s")
    assert st == TurnState(metrics=["b"], periods=["2025"], entity=None)
    assert r.last_state("other") is None
    assert count_rows(engine, "sessions") == 1
    assert count_rows(engine, "messages") == 3


def test_migration_matches_orm(engine: Engine) -> None:
    insp = sa.inspect(engine)
    names = set(insp.get_table_names()) - {"alembic_version"}
    assert names == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in insp.get_columns(name)} == {c.name for c in table.columns}
        assert {i["name"] for i in insp.get_indexes(name)} == {i.name for i in table.indexes}
    assert "ix_facts_lookup" in {i["name"] for i in insp.get_indexes("facts")}


def test_upgrade_idempotent(engine: Engine) -> None:
    upgrade_db(engine)
    assert count_rows(engine, "facts") == 0

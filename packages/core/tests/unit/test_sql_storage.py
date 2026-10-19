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


def test_session_messages_in_order(engine: Engine) -> None:
    repo = SessionRepo(engine)
    repo.append("s1", "user", "Câu 1", None)
    repo.append("s1", "assistant", "Đáp 1", TurnState(metrics=[], periods=["2025"], entity=None))
    msgs = repo.messages("s1")
    assert [(m.role, m.content) for m in msgs] == [("user", "Câu 1"), ("assistant", "Đáp 1")]
    assert repo.exists("s1") and not repo.exists("nope") and repo.messages("nope") == []


def test_fact_search_by_label_and_period(engine: Engine) -> None:
    store = SqlFactStore(engine)
    store.upsert(
        [
            fact(fact_id="a", label="Tổng tài sản", label_norm="tong tai san", period="FY2025"),
            fact(fact_id="b", label="Tổng tài sản", label_norm="tong tai san", period="FY2024"),
            fact(fact_id="c", label="Cho vay", label_norm="cho vay", period="FY2025"),
        ]
    )
    assert {f.fact_id for f in store.search("tổng tài sản")} == {"a", "b"}
    assert [f.fact_id for f in store.search("Tổng Tài Sản", period="FY2025")] == ["a"]
    assert store.search("", limit=2) and len(store.search("", limit=2)) == 2


def test_session_owner_title_and_listing(engine: Engine) -> None:
    repo = SessionRepo(engine)
    long_q = "Tổng tài sản " + "rất " * 40 + "năm 2025?"
    repo.append("a", "user", long_q, None, owner="alice")
    repo.append("a", "assistant", "Đáp", None, payload='{"status": "answered"}', owner="alice")
    repo.append("b", "user", "  RBG\nlà gì?  ", None, owner="alice")
    repo.append("c", "user", "Câu của Bob", None, owner="bob")

    mine = repo.list_sessions("alice")
    assert [s.id for s in mine] == ["b", "a"]  # most recently updated first
    assert mine[0].title == "RBG là gì?"
    assert len(mine[1].title) == 80 and mine[1].title.endswith("…")
    assert [s.n_messages for s in mine] == [1, 2]
    assert [s.id for s in repo.list_sessions("bob")] == ["c"]
    assert repo.list_sessions(None) == []

    assert repo.owned_by("a", "alice") and not repo.owned_by("a", "bob") and not repo.owned_by("x", "alice")
    assert [m.payload for m in repo.messages("a")] == [None, '{"status": "answered"}']


def test_session_without_owner_is_only_visible_without_owner(engine: Engine) -> None:
    repo = SessionRepo(engine)
    repo.append("cli", "user", "q", None)
    assert repo.owned_by("cli", None) and not repo.owned_by("cli", "alice")
    assert [s.id for s in repo.list_sessions(None)] == ["cli"]


def test_session_delete_removes_messages(engine: Engine) -> None:
    repo = SessionRepo(engine)
    repo.append("a", "user", "q", None, owner="alice")
    repo.append("a", "assistant", "đáp", None, owner="alice")
    repo.delete("a")
    assert not repo.exists("a") and repo.messages("a") == []
    assert count_rows(engine, "messages") == 0


def test_migration_0002_backfills_titles(tmp_path: Path) -> None:
    eng = make_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    upgrade_db(eng, "0001")
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO sessions (id, created_at) VALUES ('s', '2026-01-01 00:00:00')"))
        c.execute(
            sa.text(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES "
                "('s', 'user', 'Câu đầu', '2026-01-01 00:00:01'), "
                "('s', 'assistant', 'Đáp', '2026-01-01 00:00:02')"
            )
        )
    upgrade_db(eng)
    [summary] = SessionRepo(eng).list_sessions(None)
    assert summary.title == "Câu đầu" and summary.n_messages == 2
    assert summary.updated_at.isoformat() == "2026-01-01T00:00:02+00:00"

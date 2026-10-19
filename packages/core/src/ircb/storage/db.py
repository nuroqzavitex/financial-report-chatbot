"""Engine factory, session scope and programmatic Alembic upgrade."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, make_url
from sqlalchemy.orm import Session

_MIGRATIONS = Path(__file__).parent / "migrations"


def make_engine(url: str) -> Engine:
    """Create the engine; a file-based SQLite URL gets its parent directory (``./var``) created.

    Every pooled connection is pinged before use (cloud Postgres such as Neon or Supabase drops idle
    connections), and psycopg never prepares statements, so a transaction-mode pooler (PgBouncer,
    Supavisor) can hand each statement to a different server connection.
    """
    u = make_url(url)
    db = u.database
    if u.get_backend_name() == "sqlite" and db and db != ":memory:" and not db.startswith("file:"):
        Path(db).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"prepare_threshold": None} if u.get_driver_name() == "psycopg" else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error."""
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def upgrade_db(engine: Engine, revision: str = "head") -> None:
    """Run ``alembic upgrade <revision>`` against ``engine``."""
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS))
    url = engine.url.render_as_string(hide_password=False).replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", url)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)

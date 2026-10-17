"""Shared fixtures for the local-production integration tests (Qdrant server + PostgreSQL).

Both services come from ``docker-compose.yml`` (``make up``). When they are unreachable the tests
skip with a clear reason; the probes use short timeouts so nothing hangs.
"""

import os
import sys
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# the unit-test helpers (factories, mini-index builders) live next to these tests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

QDRANT_URL = os.environ.get("QDRANT_URL") or "http://localhost:6333"
_ENV_DB = os.environ.get("DATABASE_URL", "")
PG_URL = _ENV_DB if _ENV_DB.startswith("postgresql") else "postgresql+psycopg://ircb:ircb@localhost:5432/ircb"
PROBE_TIMEOUT_S = 2


@pytest.fixture(scope="session")
def qdrant_url() -> str:
    try:
        with urllib.request.urlopen(f"{QDRANT_URL}/readyz", timeout=PROBE_TIMEOUT_S) as r:
            if r.status != 200:
                raise OSError(f"HTTP {r.status}")
    except Exception as e:
        pytest.skip(f"Qdrant server not reachable at {QDRANT_URL} ({e}); run `docker compose up -d`")
    return QDRANT_URL


@pytest.fixture(scope="session")
def pg_url() -> str:
    try:
        import psycopg
        from sqlalchemy.engine import make_url

        u = make_url(PG_URL)
        with psycopg.connect(
            host=u.host,
            port=u.port,
            user=u.username,
            password=u.password,
            dbname=u.database,
            connect_timeout=PROBE_TIMEOUT_S,
        ):
            pass
    except Exception as e:
        pytest.skip(f"PostgreSQL not reachable at {PG_URL} ({e}); run `docker compose up -d`")
    return PG_URL


@pytest.fixture
def pg_db(pg_url: str) -> Iterator[str]:
    """URL of a throwaway database ``ircb_it_<run>`` (dropped afterwards): tests never write to ``ircb``."""
    import psycopg
    from sqlalchemy.engine import make_url

    u = make_url(pg_url)
    name = f"ircb_it_{uuid.uuid4().hex[:10]}"
    admin: dict[str, Any] = {
        "host": u.host,
        "port": u.port,
        "user": u.username,
        "password": u.password,
        "dbname": u.database,
        "connect_timeout": PROBE_TIMEOUT_S,
        "autocommit": True,
    }
    with psycopg.connect(**admin) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    try:
        yield u.set(database=name).render_as_string(hide_password=False)
    finally:
        with psycopg.connect(**admin) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

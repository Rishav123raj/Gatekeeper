"""The SQLite database: one file, shared by the worker (writes) and the dashboard (reads).

WAL mode lets the dashboard read while the worker writes, and a busy timeout makes a
writer wait for another instead of failing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from gatekeeper import tables  # noqa: F401  (registers the tables)

SQLITE = "sqlite:///"


def resolve_url(url: str) -> str:
    """A relative SQLite path is taken from the project folder, and its folder is created."""
    from gatekeeper.settings import ROOT

    if not url.startswith(SQLITE) or url == SQLITE + ":memory:":
        return url
    path = Path(url[len(SQLITE) :])
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return SQLITE + path.as_posix()


def make_engine(url: str) -> Engine:
    url = resolve_url(url)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # every new connection
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    return engine


def init_db(engine: Engine) -> Engine:
    SQLModel.metadata.create_all(engine)
    return engine


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    """The application's engine (from DB_URL), with the tables created."""
    from gatekeeper.settings import get_settings

    return init_db(make_engine(url or get_settings().db_url))


@contextmanager
def session(engine: Engine | None = None) -> Iterator[Session]:
    """A session that commits on success and rolls back on error."""
    with Session(engine or get_engine(), expire_on_commit=False) as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise

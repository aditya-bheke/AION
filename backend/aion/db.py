"""Database engine and session management (SQLAlchemy 2.0 + SQLite)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(database_url: str) -> Engine:
    """Create the engine and tables. Called once at startup (and per test)."""
    global _engine, _SessionLocal
    connect_args = {}
    if database_url.startswith("sqlite"):
        # The API, the log collector and the pipeline worker run on different
        # threads; each uses its own Session, so sharing the connection pool
        # across threads is safe.
        connect_args = {"check_same_thread": False, "timeout": 30}
        if ":///" in database_url and not database_url.endswith(":memory:"):
            from pathlib import Path

            Path(database_url.split(":///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(database_url, connect_args=connect_args)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            # WAL lets readers (dashboard) proceed while a writer (pipeline) commits.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    from aion import models  # noqa: F401  (register tables on Base.metadata)

    Base.metadata.create_all(engine)
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialised; call init_engine() first")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background code: commit on success, rollback on error."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised; call init_engine() first")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one Session per HTTP request."""
    with session_scope() as session:
        yield session

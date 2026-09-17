"""Engine/session management.

DATABASE_URL examples
  postgresql+psycopg2://clgnn:clgnn@db:5432/clgnn   (docker-compose, TimescaleDB image)
  sqlite:///cache/app.db                             (local default)

On PostgreSQL `init_db` additionally enables the timescaledb extension and
turns the time-series tables into hypertables. Timescale requires every unique
index to contain the partitioning column, so the single-column primary key is
replaced by (id, ts) first. NOTE: this Postgres/Timescale path could not be
executed on the development machine (no Docker/Postgres available); it is
written against the documented TimescaleDB API and flagged as untested in the
README.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from src.db.models import HYPERTABLES, Base
from src.utils.config import REPO_ROOT
from src.utils.logging import get_logger

log = get_logger(__name__)


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    path = REPO_ROOT / "cache" / "app.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _wal(dbapi_conn, _):  # concurrent reads while the demo thread writes
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
        return engine
    return create_engine(url, pool_pre_ping=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        except Exception as exc:  # plain Postgres without Timescale still works
            log.warning("TimescaleDB extension unavailable (%s); using plain tables", exc)
            return
    for table, tcol in HYPERTABLES.items():
        with engine.begin() as conn:
            is_hyper = conn.execute(text(
                "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = :t"), {"t": table}).first()
            if is_hyper:
                continue
            conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"))
            conn.execute(text(f"ALTER TABLE {table} ADD PRIMARY KEY (id, {tcol})"))
            conn.execute(text(f"SELECT create_hypertable('{table}', '{tcol}', migrate_data => true, "
                              f"if_not_exists => true)"))
            log.info("hypertable created: %s(%s)", table, tcol)


_engine: Engine | None = None
_Session = None


def get_sessionmaker(url: str | None = None):
    global _engine, _Session
    if _Session is None or url is not None:
        _engine = make_engine(url)
        init_db(_engine)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _Session


def reset_for_tests(url: str):
    global _engine, _Session
    _engine, _Session = None, None
    return get_sessionmaker(url)

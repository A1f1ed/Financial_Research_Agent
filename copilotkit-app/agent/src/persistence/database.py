"""Bounded, process-local SQLAlchemy pools; explicit transactions and no fallback."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
from threading import RLock

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from src.infrastructure.config import Infrastructure


_engines = {}
_lock = RLock()
_pid = os.getpid()
database_override = ContextVar("research_database_override", default=None)


def engine_for(url: str):
    global _pid
    if make_url(url).drivername != "postgresql+psycopg":
        raise ValueError("The research database requires postgresql+psycopg")
    with _lock:
        if _pid != os.getpid():
            for previous in _engines.values():
                previous.dispose(close=False)
            _engines.clear()
            _pid = os.getpid()
        if url not in _engines:
            _engines[url] = create_engine(url, pool_size=5, max_overflow=5, pool_timeout=10, pool_pre_ping=True,
                                         pool_recycle=1800, hide_parameters=True,
                                         connect_args={"connect_timeout": 5,
                                                       "options": "-c statement_timeout=15000 -c idle_in_transaction_session_timeout=30000"})
        return _engines[url]


def engine():
    override = database_override.get()
    return override if override is not None else engine_for(Infrastructure.read().database_url)


@contextmanager
def transaction(bind=None):
    with Session(bind or engine(), expire_on_commit=False) as session, session.begin():
        yield session


def dispose_engines():
    with _lock:
        for previous in _engines.values():
            previous.dispose()
        _engines.clear()

"""An isolated real PostgreSQL database for existing business/API tests."""
from contextlib import contextmanager
from uuid import uuid4

from psycopg import connect, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy.engine import make_url

from src.infrastructure.config import Infrastructure
from src.persistence.database import database_override, engine_for
from src.persistence.migrate_legacy import upgrade


@contextmanager
def postgres_fixture():
    settings = Infrastructure.read()
    name = "aperture_test_" + uuid4().hex
    conninfo = make_conninfo(**conninfo_to_dict(settings.checkpoint_url))
    with connect(conninfo, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    bind = engine_for(make_url(settings.database_url).set(database=name).render_as_string(hide_password=False))
    token = None
    try:
        upgrade(bind)
        token = database_override.set(bind)
        yield bind
    finally:
        if token is not None:
            database_override.reset(token)
        from src.infrastructure.cache import MarketCache
        MarketCache(bind).clear_test_namespace()
        bind.dispose()
        if not name.startswith("aperture_test_"):
            raise AssertionError("Refusing to delete non-test database")
        with connect(conninfo, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))

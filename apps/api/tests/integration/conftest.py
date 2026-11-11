import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from sinegor.core.config import Settings
from sinegor.db.session import create_db_engine


@pytest.fixture
def database_settings(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end with _test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("SINEGOR_ENV_FILE", "/dev/null")
    return Settings(_env_file=None)


@pytest.fixture
def alembic_config(database_settings):
    return Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


@pytest.fixture(autouse=True)
def isolate_destruction_evidence(database_settings):
    """External CLI/concurrent sessions commit outside db_session's savepoint.

    Keep their documentary side effects as isolated as their existing source fixtures.
    Never remove rows that predate this test, or weaken production downgrade guards.
    """
    engine = create_db_engine(database_settings)
    try:
        with engine.connect() as connection:
            previous = (
                set(connection.scalars(text("SELECT id FROM destruction_operations")))
                if inspect(connection).has_table("destruction_operations")
                else set()
            )
        yield
    finally:
        with engine.begin() as connection:
            if inspect(connection).has_table("destruction_operations"):
                current = set(connection.scalars(text("SELECT id FROM destruction_operations")))
                for identifier in current - previous:
                    connection.execute(
                        text("DELETE FROM destruction_operations WHERE id=:id"), {"id": identifier}
                    )
        engine.dispose()


@pytest.fixture
def db_session(database_settings, alembic_config):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                try:
                    yield session
                finally:
                    session.close()
                    transaction.rollback()
    finally:
        engine.dispose()

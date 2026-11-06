from typing import Annotated
from uuid import uuid4

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from sinegor.db.base import Base
from sinegor.db.session import create_db_engine, get_session
from sinegor.main import create_app

pytestmark = pytest.mark.integration


def test_postgres_readiness_and_request_session(database_settings):
    app = create_app(database_settings)

    @app.get("/test/session")
    def session_check(session: Annotated[Session, Depends(get_session)]):
        return {"value": session.scalar(text("SELECT 1"))}

    with TestClient(app) as client:
        assert client.get("/api/health/ready").json() == {"status": "ok", "database": "ok"}
        assert client.get("/test/session").json() == {"value": 1}


def test_migration_upgrade_downgrade_and_schema_drift(database_settings, alembic_config):
    config = alembic_config
    engine = create_db_engine(database_settings)
    tables = {table.name for table in Base.metadata.sorted_tables}
    try:
        # This destructive test is restricted to a dedicated, empty test database.
        with engine.connect() as connection:
            existing = set(inspect(connection).get_table_names())
            assert existing <= tables | {"alembic_version"}, "Unexpected test database tables"
            for table in tables & existing:
                assert connection.scalar(text(f'SELECT count(*) FROM "{table}"')) == 0
        command.downgrade(config, "base")
        command.upgrade(config, "0001_backend_baseline")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "0002_domain_models")
        admin_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO admin_users (id, email, password_hash) "
                    "VALUES (:id, 'migration@example.ru', 'legacy_hash')"
                ),
                {"id": admin_id},
            )
        command.upgrade(config, "head")
        with engine.begin() as connection:
            admin = connection.execute(
                text("SELECT email, last_totp_step FROM admin_users WHERE id=:id"), {"id": admin_id}
            ).one()
            assert admin.email == "migration@example.ru" and admin.last_totp_step is None
            connection.execute(text("DELETE FROM admin_users WHERE id=:id"), {"id": admin_id})
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision()
                == ScriptDirectory.from_config(config).get_current_head()
            )
            assert set(inspect(connection).get_table_names()) == tables | {"alembic_version"}
        command.check(config)
        command.downgrade(config, "0001_backend_baseline")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() is None
        command.upgrade(config, "head")
    finally:
        engine.dispose()

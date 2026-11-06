import pytest
from alembic import command
from sqlalchemy import text

from sinegor.db.session import create_db_engine

pytestmark = pytest.mark.integration


def test_customer_blocking_migration_preserves_customer_and_roundtrips(
    database_settings, alembic_config
):
    engine = create_db_engine(database_settings)
    identifier = "10000000-0000-4000-8000-000000000020"
    try:
        command.upgrade(alembic_config, "head")
        command.downgrade(alembic_config, "0012_security_events")
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO customers (id, email) VALUES (:id, 'migration20@example.ru')"),
                {"id": identifier},
            )
        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT email, blocked_at, block_reason, block_comment, access_revision "
                    "FROM customers WHERE id=:id"
                ),
                {"id": identifier},
            ).one()
            assert tuple(row) == ("migration20@example.ru", None, None, None, 0)
        command.check(alembic_config)
        command.downgrade(alembic_config, "0012_security_events")
        command.upgrade(alembic_config, "head")
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM customers WHERE id=:id"), {"id": identifier})
        engine.dispose()

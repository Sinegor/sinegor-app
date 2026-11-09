from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from sinegor.db.session import create_db_engine

pytestmark = pytest.mark.integration


def test_cancellation_migration_preserves_history_and_prevents_data_loss(
    database_settings, alembic_config
):
    engine = create_db_engine(database_settings)
    customer_id, order_id = uuid4(), uuid4()
    try:
        command.upgrade(alembic_config, "head")
        command.downgrade(alembic_config, "0013_customer_blocking")
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO customers (id, email) VALUES (:id, 'migration23@example.ru')"),
                {"id": customer_id},
            )
            connection.execute(
                text(
                    "INSERT INTO orders (id, customer_id, service_type, status, closed_at) "
                    "VALUES (:id, :customer, 'analysis', 'cancelled', now())"
                ),
                {"id": order_id, "customer": customer_id},
            )
        command.upgrade(alembic_config, "head")
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT status, cancellation_internal_reason, cancellation_customer_reason "
                    "FROM orders WHERE id=:id"
                ),
                {"id": order_id},
            ).one()
            assert tuple(row) == ("cancelled", None, None)
            connection.execute(
                text(
                    "UPDATE orders SET cancellation_internal_reason='Internal', "
                    "cancellation_customer_reason='Customer' WHERE id=:id"
                ),
                {"id": order_id},
            )
        command.check(alembic_config)
        with pytest.raises(RuntimeError, match="decisions must be retained"):
            command.downgrade(alembic_config, "0013_customer_blocking")
        with engine.begin() as connection:
            assert (
                connection.scalar(
                    text("SELECT cancellation_customer_reason FROM orders WHERE id=:id"),
                    {"id": order_id},
                )
                == "Customer"
            )
            connection.execute(
                text(
                    "UPDATE orders SET cancellation_internal_reason=NULL, "
                    "cancellation_customer_reason=NULL WHERE id=:id"
                ),
                {"id": order_id},
            )
            connection.execute(
                text(
                    "INSERT INTO deletion_requests (id, order_id, reason, due_at) "
                    "VALUES (:id, :id, 'order_cancelled', now())"
                ),
                {"id": order_id},
            )
        with pytest.raises(RuntimeError, match="decisions must be retained"):
            command.downgrade(alembic_config, "0013_customer_blocking")
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM deletion_requests WHERE order_id=:id"), {"id": order_id}
            )
        command.downgrade(alembic_config, "0013_customer_blocking")
        command.upgrade(alembic_config, "head")
        command.check(alembic_config)
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM deletion_requests WHERE order_id=:id"), {"id": order_id}
            )
            connection.execute(text("DELETE FROM orders WHERE id=:id"), {"id": order_id})
            connection.execute(text("DELETE FROM customers WHERE id=:id"), {"id": customer_id})
        engine.dispose()

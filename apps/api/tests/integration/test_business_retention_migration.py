from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from sinegor.db.session import create_db_engine

pytestmark = pytest.mark.integration


def test_migration_backfills_only_proven_administrative_fulfillment(
    database_settings, alembic_config
):
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0014_order_cancellation")
    engine = create_db_engine(database_settings)
    customer, admin, proven, unknown = [uuid4() for _ in range(4)]
    stamp = datetime(2021, 3, 1, 12, tzinfo=UTC)
    values = {
        "customer": customer,
        "admin": admin,
        "stamp": stamp,
        "closed": stamp + timedelta(days=14),
    }
    try:
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO customers(id,email,created_at) VALUES (:customer, :email, :stamp)"
                ),
                values | {"email": f"{customer.hex}@example.ru"},
            )
            db.execute(
                text(
                    "INSERT INTO admin_users(id,email,password_hash) "
                    "VALUES (:admin,:email,'synthetic')"
                ),
                values | {"email": f"{admin.hex}@example.ru"},
            )
            for identifier in (proven, unknown):
                db.execute(
                    text(
                        "INSERT INTO orders(id,customer_id,service_type,status,created_at,ready_at,"
                        "result_notified_at,closed_at) VALUES (:id,:customer,'analysis',"
                        "'completed',:stamp,:stamp,:stamp,:closed)"
                    ),
                    values | {"id": identifier},
                )
            for kind in ("status_result_ready", "result_notification_sent"):
                db.execute(
                    text(
                        "INSERT INTO order_events(id,order_id,event_type,actor_admin_id) "
                        "VALUES (:id,:order,:kind,:admin)"
                    ),
                    values | {"id": uuid4(), "order": proven, "kind": kind},
                )
        command.upgrade(alembic_config, "head")
        with engine.connect() as db:
            assert (
                db.scalar(text("SELECT fulfilled_at FROM orders WHERE id=:id"), {"id": proven})
                == stamp
            )
            assert (
                db.scalar(text("SELECT fulfilled_at FROM orders WHERE id=:id"), {"id": unknown})
                is None
            )
            assert (
                db.scalar(
                    text("SELECT count(*) FROM orders WHERE id IN (:one,:two)"),
                    {"one": proven, "two": unknown},
                )
                == 2
            )
        command.check(alembic_config)
        with pytest.raises(RuntimeError):
            command.downgrade(alembic_config, "0014_order_cancellation")
    finally:
        command.upgrade(alembic_config, "head")
        with engine.begin() as db:
            db.execute(
                text("DELETE FROM order_events WHERE order_id IN (:one,:two)"),
                {"one": proven, "two": unknown},
            )
            db.execute(
                text("DELETE FROM orders WHERE id IN (:one,:two)"), {"one": proven, "two": unknown}
            )
            db.execute(text("DELETE FROM customers WHERE id=:id"), {"id": customer})
            db.execute(text("DELETE FROM admin_users WHERE id=:id"), {"id": admin})
        engine.dispose()

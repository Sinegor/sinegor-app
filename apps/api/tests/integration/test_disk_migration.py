from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from sinegor.db.session import create_db_engine
from sinegor.db.types import ServiceType
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.customers.models import Customer
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.orders.models import Order

pytestmark = pytest.mark.integration


def test_deletion_intent_migration_recovers_existing_attempts(database_settings, alembic_config):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    customer_id = uuid4()
    order_ids = [uuid4(), uuid4()]
    attempted_at = datetime.now(UTC) - timedelta(minutes=1)
    try:
        with Session(engine) as db:
            db.add(Customer(id=customer_id, email=f"{customer_id.hex}@example.ru"))
            db.flush()
            db.add_all(
                [
                    Order(id=identifier, customer_id=customer_id, service_type=ServiceType.ANALYSIS)
                    for identifier in order_ids
                ]
            )
            db.flush()
            db.add_all(
                [
                    DiskFolder(order_id=identifier, disk_path=f"disk:/orders/{identifier}")
                    for identifier in order_ids
                ]
            )
            db.add(
                OrderEvent(
                    order_id=order_ids[0],
                    event_type="disk_deletion_failed",
                    created_at=attempted_at,
                )
            )
            db.commit()
        command.downgrade(alembic_config, "0007_disk_operations")
        command.upgrade(alembic_config, "head")
        with Session(engine) as db:
            folders = {row.order_id: row for row in db.scalars(select(DiskFolder)).all()}
            assert folders[order_ids[0]].deletion_started_at == attempted_at
            assert folders[order_ids[1]].deletion_started_at is None
            assert not folders[order_ids[0]].deletion_succeeded
    finally:
        command.upgrade(alembic_config, "head")
        with engine.begin() as connection:
            connection.execute(delete(OrderEvent).where(OrderEvent.order_id.in_(order_ids)))
            connection.execute(delete(DiskFolder).where(DiskFolder.order_id.in_(order_ids)))
            connection.execute(delete(Order).where(Order.id.in_(order_ids)))
            connection.execute(delete(Customer).where(Customer.id == customer_id))
        engine.dispose()

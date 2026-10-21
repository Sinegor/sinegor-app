from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from test_disk import ROOT, MemoryDisk

from sinegor.db.session import create_db_engine
from sinegor.db.types import ServiceType
from sinegor.integrations.yandex_disk.client import Resource
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.auth.models import AdminUser
from sinegor.modules.customers.models import Customer
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.disk.service import provision
from sinegor.modules.orders.models import Order

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("operation", ["same_order", "same_path", "nested_paths"])
def test_competing_bindings_are_serialized(database_settings, alembic_config, operation):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    customer_id, admin_id = uuid4(), uuid4()
    order_ids = [uuid4(), uuid4()]
    disk = MemoryDisk()
    parent = ROOT + "/existing"
    disk.resources[parent] = Resource(parent, "parent")
    disk.resources[parent + "/child"] = Resource(parent + "/child", "child")
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    Customer(id=customer_id, email=f"{customer_id.hex}@example.ru"),
                    AdminUser(
                        id=admin_id, email=f"{admin_id.hex}@example.ru", password_hash="test"
                    ),
                ]
            )
            db.flush()
            db.add_all(
                [
                    Order(id=identifier, customer_id=customer_id, service_type=ServiceType.ANALYSIS)
                    for identifier in order_ids
                ]
            )
            db.commit()
        barrier = Barrier(2)

        def attempt(index):
            with Session(engine) as db:
                barrier.wait(timeout=10)
                try:
                    if operation == "same_order":
                        provision(db, disk, order_ids[0], admin_id)
                    else:
                        path = (
                            parent + "/child"
                            if index == 1 and operation == "nested_paths"
                            else parent
                        )
                        provision(db, disk, order_ids[index], admin_id, path)
                    return 200
                except HTTPException as error:
                    db.rollback()
                    return error.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt, index) for index in range(2)]
            results = sorted(future.result(timeout=20) for future in futures)
        assert results == ([200, 200] if operation == "same_order" else [200, 409])
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(DiskFolder)
                    .where(DiskFolder.order_id.in_(order_ids))
                )
                == 1
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(OrderEvent)
                    .where(
                        OrderEvent.order_id.in_(order_ids),
                        OrderEvent.event_type == "disk_folder_bound",
                    )
                )
                == 1
            )
        if operation == "same_order":
            assert len(disk.calls) == 1
    finally:
        with engine.begin() as connection:
            connection.execute(delete(OrderEvent).where(OrderEvent.order_id.in_(order_ids)))
            connection.execute(delete(DiskFolder).where(DiskFolder.order_id.in_(order_ids)))
            connection.execute(delete(Order).where(Order.id.in_(order_ids)))
            connection.execute(delete(AdminUser).where(AdminUser.id == admin_id))
            connection.execute(delete(Customer).where(Customer.id == customer_id))
        engine.dispose()

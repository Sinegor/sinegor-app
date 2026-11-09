from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from sinegor.db.session import create_db_engine
from sinegor.db.types import OrderStatus, ServiceType
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.customers.models import Customer
from sinegor.modules.orders.models import Order
from sinegor.modules.orders.service import locked_order, process_lifecycle, transition

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("operation", ["automatic_completion", "manual_cancellation"])
def test_competing_workers_record_one_transition(database_settings, alembic_config, operation):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    customer_id, order_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    completed = operation == "automatic_completion"
    try:
        with Session(engine) as db:
            db.add(Customer(id=customer_id, email=f"{customer_id.hex}@example.ru"))
            db.flush()
            db.add(
                Order(
                    id=order_id,
                    customer_id=customer_id,
                    service_type=ServiceType.ANALYSIS,
                    created_at=now - timedelta(days=20),
                    status=OrderStatus.RESULT_READY
                    if completed
                    else OrderStatus.AWAITING_AGREEMENT,
                    ready_at=now - timedelta(days=15) if completed else None,
                    result_notified_at=now - timedelta(days=15) if completed else None,
                )
            )
            db.commit()
        barrier = Barrier(2)

        def attempt():
            with Session(engine) as db:
                barrier.wait(timeout=10)
                if completed:
                    return process_lifecycle(db)
                try:
                    order = locked_order(db, order_id)
                    transition(
                        db,
                        order,
                        OrderStatus.CANCELLED,
                        None,
                        cancellation_internal_reason="Internal decision",
                        cancellation_customer_reason="Explanation for customer",
                    )
                    db.commit()
                    return 1
                except HTTPException as exc:
                    assert exc.status_code == 409
                    db.rollback()
                    return 0

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt) for _ in range(2)]
            assert sorted(f.result(timeout=20) for f in futures) == [0, 1]
        with Session(engine) as db:
            assert db.get(Order, order_id).status == (
                OrderStatus.COMPLETED if completed else OrderStatus.CANCELLED
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(OrderEvent)
                    .where(OrderEvent.order_id == order_id)
                )
                == 1
            )
    finally:
        with engine.begin() as connection:
            connection.execute(delete(OrderEvent).where(OrderEvent.order_id == order_id))
            connection.execute(delete(Order).where(Order.id == order_id))
            connection.execute(delete(Customer).where(Customer.id == customer_id))
        engine.dispose()

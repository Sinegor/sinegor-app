from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import test_retention_concurrency as helpers
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sinegor.db.types import OrderStatus
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.orders.models import Order
from sinegor.modules.orders.service import locked_order, transition
from sinegor.modules.retention.models import DeletionRequest

pytestmark = pytest.mark.integration
persisted = helpers.persisted


def test_competing_cancellations_keep_one_decision_and_request(persisted):
    with Session(persisted.engine) as db:
        order = db.get(Order, persisted.order_id)
        order.status = OrderStatus.IN_PROGRESS
        order.ready_at = order.result_notified_at = None
        db.add(
            DiskFolder(
                order_id=order.id,
                disk_path="disk:/orders/cancellation-race",
                resource_id="synthetic-cancel",
            )
        )
        db.commit()
    barrier = Barrier(2)

    def attempt(reason):
        with Session(persisted.engine) as db:
            barrier.wait(timeout=10)
            try:
                transition(
                    db,
                    locked_order(db, persisted.order_id),
                    OrderStatus.CANCELLED,
                    persisted.admin_id,
                    cancellation_internal_reason=reason,
                    cancellation_customer_reason="Customer " + reason,
                )
                db.commit()
                return reason
            except HTTPException as exc:
                assert exc.status_code == 409
                db.rollback()
                return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt, reason) for reason in ["First", "Second"]]
        results = [f.result(timeout=20) for f in futures]
    winner = next(x for x in results if x is not None)
    assert results.count(None) == 1
    with Session(persisted.engine) as db:
        order = db.get(Order, persisted.order_id)
        assert order.cancellation_internal_reason == winner
        assert order.cancellation_customer_reason == "Customer " + winner
        assert (
            db.scalar(
                select(func.count())
                .select_from(DeletionRequest)
                .where(DeletionRequest.order_id == order.id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(OrderEvent)
                .where(OrderEvent.order_id == order.id, OrderEvent.event_type == "status_cancelled")
            )
            == 1
        )

"""Order transitions are serialized by locking the order before any mutation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sinegor.db.types import AgreementStatus, OrderStatus
from sinegor.integrations.email.smtp import OrderMailer
from sinegor.modules.agreements.models import Agreement
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.orders.models import Order

TRANSITIONS = {
    OrderStatus.AWAITING_AGREEMENT: {OrderStatus.AWAITING_MATERIALS, OrderStatus.CANCELLED},
    OrderStatus.AWAITING_MATERIALS: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.RESULT_READY, OrderStatus.CANCELLED},
    OrderStatus.RESULT_READY: set(),
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


def locked_order(db: Session, order_id: UUID) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


def record_event(
    db: Session,
    order: Order,
    event_type: str,
    admin_id: UUID | None = None,
    customer_id: UUID | None = None,
) -> None:
    db.add(
        OrderEvent(
            order_id=order.id,
            event_type=event_type,
            actor_admin_id=admin_id,
            actor_customer_id=customer_id,
        )
    )


def require_agreement(db: Session, order: Order) -> None:
    agreement = db.scalar(select(Agreement).where(Agreement.order_id == order.id).with_for_update())
    if agreement is None or agreement.status != AgreementStatus.APPROVED:
        raise HTTPException(409, "An approved signed agreement is required")


def transition(
    db: Session,
    order: Order,
    target: OrderStatus,
    admin_id: UUID | None,
    *,
    mailer: OrderMailer | None = None,
    cancellation_internal_reason: str | None = None,
    cancellation_customer_reason: str | None = None,
) -> None:
    if target not in TRANSITIONS[order.status]:
        raise HTTPException(409, "Order status transition is not allowed")
    if target == OrderStatus.CANCELLED and any(
        not isinstance(reason, str) or not reason.strip() or len(reason) > 10000
        for reason in (cancellation_internal_reason, cancellation_customer_reason)
    ):
        raise HTTPException(422, "Both cancellation reasons are required")
    if target != OrderStatus.CANCELLED:
        require_agreement(db, order)
    if target == OrderStatus.RESULT_READY:
        if mailer is None:
            raise RuntimeError("Result mailer is required")
        # SMTP acceptance is required before starting the retention clock.
        ready_at = datetime.now(UTC)
        mailer.send_result_ready(order.customer.email, order.number)
        order.ready_at = ready_at
        order.result_notified_at = datetime.now(UTC)
        order.fulfilled_at = order.result_notified_at
        record_event(db, order, "result_notification_sent", admin_id)
    elif target == OrderStatus.CANCELLED:
        # Retention depends on the order locking helpers from this module.
        from sinegor.modules.retention.service import request_on_cancellation

        order.closed_at = datetime.now(UTC)
        order.cancellation_internal_reason = cancellation_internal_reason.strip()
        order.cancellation_customer_reason = cancellation_customer_reason.strip()
        order.status = target
        request_on_cancellation(db, order, order.closed_at, admin_id)
    order.status = target
    record_event(db, order, f"status_{target.value}", admin_id)


def process_lifecycle(db: Session, *, now: datetime | None = None) -> int:
    """Idempotent worker; never deletes materials or completes orders early."""
    now = now or datetime.now(UTC)
    candidates = db.scalars(
        select(Order)
        .where(
            (Order.status == OrderStatus.AWAITING_AGREEMENT)
            & Order.id.in_(
                select(Agreement.order_id).where(Agreement.status == AgreementStatus.APPROVED)
            )
            | (Order.status == OrderStatus.RESULT_READY)
            & (Order.result_notified_at <= now - timedelta(days=14))
        )
        .order_by(Order.id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).all()
    for order in candidates:
        if order.status == OrderStatus.AWAITING_AGREEMENT:
            transition(db, order, OrderStatus.AWAITING_MATERIALS, None)
        else:
            order.status = OrderStatus.COMPLETED
            order.closed_at = now
            record_event(db, order, "status_completed")
    db.commit()
    return len(candidates)

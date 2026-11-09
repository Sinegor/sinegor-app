"""Deletion decisions are serialized with the order; workers never delete materials."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sinegor.db.types import DeletionReason, DeletionStatus, OrderStatus
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.orders.models import Order
from sinegor.modules.orders.service import locked_order, record_event
from sinegor.modules.retention.models import DeletionRequest


def request_for(db: Session, order: Order) -> DeletionRequest | None:
    return db.scalar(
        select(DeletionRequest)
        .where(DeletionRequest.order_id == order.id)
        .execution_options(populate_existing=True)
    )


def eligible_at(order: Order, item: DeletionRequest) -> datetime:
    """Deletion basis is independent of the administrator's reminder date."""
    if order.status == OrderStatus.CANCELLED and order.closed_at is not None:
        return order.closed_at
    due = item.due_at
    if item.reason == DeletionReason.EARLY_PERMISSION:
        due = max(due, item.early_authorized_at or due)
    elif item.reason == DeletionReason.RETENTION_EXPIRED:
        due = max(due, order.result_notified_at + timedelta(days=14))
    return due


def effective_due_at(order: Order, item: DeletionRequest) -> datetime:
    return item.deferred_until or eligible_at(order, item)


def require_result(order: Order, now: datetime) -> None:
    if (
        order.status not in {OrderStatus.RESULT_READY, OrderStatus.COMPLETED}
        or order.result_notified_at is None
        or order.result_notified_at > now
    ):
        raise HTTPException(409, "A notified result is required")


def request_on_cancellation(
    db: Session, order: Order, now: datetime, admin_id: UUID | None
) -> None:
    """Use the caller's order lock and transaction; never call Disk or commit here."""
    folder = db.scalar(select(DiskFolder).where(DiskFolder.order_id == order.id))
    if folder is None or folder.deleted_at is not None:
        return
    item = request_for(db, order)
    if item is not None:
        if item.status == DeletionStatus.PERFORMED:
            raise HTTPException(409, "Deletion evidence conflicts with the current folder")
        return
    db.add(DeletionRequest(order=order, reason=DeletionReason.ORDER_CANCELLED, due_at=now))
    record_event(db, order, "deletion_requested", admin_id)


def require_deletion_basis(order: Order, item: DeletionRequest, now: datetime) -> None:
    if order.status == OrderStatus.CANCELLED:
        if order.closed_at is None or order.closed_at > now:
            raise HTTPException(409, "A cancelled order is required")
    elif item.reason == DeletionReason.ORDER_CANCELLED:
        raise HTTPException(409, "A cancelled order is required")
    else:
        require_result(order, now)


def require_editable(db: Session, order: Order) -> None:
    folder = db.scalar(select(DiskFolder).where(DiskFolder.order_id == order.id))
    if folder is not None and (
        folder.deletion_started_at is not None
        or folder.deletion_operation_id
        or folder.deletion_succeeded
        or folder.deleted_at is not None
    ):
        raise HTTPException(409, "Deletion has already started; its decision cannot be changed")


def authorize_early(db: Session, order_id: UUID, customer_id: UUID) -> DeletionRequest:
    order = locked_order(db, order_id)
    if order.customer_id != customer_id:
        raise HTTPException(404, "Order not found")
    now = datetime.now(UTC)
    require_result(order, now)
    item = request_for(db, order)
    if item is not None and item.early_authorized_at is not None:
        return item
    require_editable(db, order)
    if item is not None and item.status not in {DeletionStatus.WAITING, DeletionStatus.DEFERRED}:
        raise HTTPException(409, "Deletion decision is already recorded")
    if item is None:
        item = DeletionRequest(order=order)
        db.add(item)
    item.reason = DeletionReason.EARLY_PERMISSION
    item.early_authorized_at = now
    item.due_at = now
    record_event(db, order, "deletion_early_authorized", customer_id=customer_id)
    db.commit()
    return item


def decision_request(
    db: Session, order_id: UUID, request_id: UUID
) -> tuple[Order, DeletionRequest]:
    order = locked_order(db, order_id)
    item = request_for(db, order)
    if item is None or item.id != request_id:
        raise HTTPException(409, "Deletion request does not match this order")
    require_deletion_basis(order, item, datetime.now(UTC))
    return order, item


def confirm(db: Session, order_id: UUID, request_id: UUID, admin_id: UUID) -> DeletionRequest:
    order, item = decision_request(db, order_id, request_id)
    if item.status in {DeletionStatus.CONFIRMED, DeletionStatus.ERROR, DeletionStatus.PERFORMED}:
        return item
    now = datetime.now(UTC)
    if effective_due_at(order, item) > now:
        raise HTTPException(409, "Deletion is not due yet")
    if item.reason == DeletionReason.EARLY_PERMISSION and (
        item.early_authorized_at is None or item.early_authorized_at < order.result_notified_at
    ):
        raise HTTPException(409, "Current customer permission is required")
    require_editable(db, order)
    item.status = DeletionStatus.CONFIRMED
    item.confirmed_at = now
    item.confirmed_by_id = admin_id
    record_event(db, order, "deletion_confirmed", admin_id)
    db.commit()
    return item


def defer(
    db: Session,
    order_id: UUID,
    request_id: UUID,
    admin_id: UUID,
    until: datetime,
    note: str,
) -> DeletionRequest:
    order, item = decision_request(db, order_id, request_id)
    require_editable(db, order)
    if item.status == DeletionStatus.PERFORMED:
        raise HTTPException(409, "Deletion cannot be deferred in its current state")
    if (
        item.status == DeletionStatus.DEFERRED
        and item.deferred_until == until
        and item.admin_note == note
    ):
        return item
    if until <= datetime.now(UTC):
        raise HTTPException(409, "Reminder date must be in the future")
    item.status = DeletionStatus.DEFERRED
    item.deferred_until = until
    item.admin_note = note
    item.confirmed_at = item.confirmed_by_id = None
    record_event(db, order, "deletion_deferred", admin_id)
    db.commit()
    return item


def process_due(db: Session, *, now: datetime | None = None) -> int:
    """Create overdue requests and return expired deferrals to administrator review."""
    now = now or datetime.now(UTC)
    orders = db.scalars(
        select(Order)
        .where(
            Order.status.in_(
                [OrderStatus.RESULT_READY, OrderStatus.COMPLETED, OrderStatus.CANCELLED]
            )
        )
        .order_by(Order.id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).all()
    changed = 0
    for order in orders:
        item = request_for(db, order)
        if (
            item is None
            and order.status != OrderStatus.CANCELLED
            and order.result_notified_at + timedelta(days=14) <= now
        ):
            folder = db.scalar(select(DiskFolder).where(DiskFolder.order_id == order.id))
            if folder is not None and folder.deleted_at is not None:
                continue
            db.add(
                DeletionRequest(
                    order=order,
                    reason=DeletionReason.RETENTION_EXPIRED,
                    due_at=order.result_notified_at + timedelta(days=14),
                )
            )
            record_event(db, order, "deletion_requested")
            changed += 1
        elif (
            item is not None
            and item.status == DeletionStatus.DEFERRED
            and effective_due_at(order, item) <= now
        ):
            item.status = DeletionStatus.WAITING
            record_event(db, order, "deletion_deferral_expired")
            changed += 1
    db.commit()
    return changed

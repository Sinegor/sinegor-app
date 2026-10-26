"""Durable retries with short claims; delivery is at least once, not proof of reading."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sinegor.core.config import Settings
from sinegor.db.types import (
    AgreementStatus,
    DeletionStatus,
    OrderStatus,
    TokenPurpose,
)
from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.integrations.telegram.client import TelegramDeliveryError
from sinegor.modules.agreements.models import Agreement
from sinegor.modules.customers.models import Customer
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications.models import Notification
from sinegor.modules.orders.models import Order
from sinegor.modules.retention.service import effective_due_at

logger = logging.getLogger(__name__)


def enqueue(
    db: Session,
    kind: str,
    *,
    recipient: str | None = None,
    order_id: UUID | None = None,
    customer_id: UUID | None = None,
    payload: dict | None = None,
    dedup_key: str | None = None,
    retry_cancelled: bool = False,
) -> UUID:
    identifier = uuid4()
    statement = insert(Notification).values(
        id=identifier,
        kind=kind,
        recipient=recipient,
        order_id=order_id,
        customer_id=customer_id,
        payload=payload or {},
        dedup_key=dedup_key,
    )
    if retry_cancelled:
        statement = statement.on_conflict_do_update(
            index_elements=[Notification.dedup_key],
            set_={
                "recipient": statement.excluded.recipient,
                "payload": statement.excluded.payload,
                "status": "pending",
                "attempts": 0,
                "available_at": datetime.now(UTC),
                "last_error_code": None,
            },
            where=Notification.status == "cancelled",
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=[Notification.dedup_key])
    return db.scalar(statement.returning(Notification.id)) or db.scalar(
        select(Notification.id).where(Notification.dedup_key == dedup_key)
    )


def queue_invitation(db: Session, customer: Customer) -> UUID:
    db.scalar(
        select(Customer)
        .where(Customer.id == customer.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    active = db.scalar(
        select(Notification.id)
        .where(
            Notification.customer_id == customer.id,
            Notification.kind == "invitation",
            Notification.recipient == customer.email,
            Notification.status.in_(["pending", "processing"]),
        )
        .order_by(Notification.created_at.desc())
        .limit(1)
    )
    identifier = active or enqueue(
        db,
        "invitation",
        recipient=customer.email,
        customer_id=customer.id,
    )
    db.commit()
    return identifier


def deletion_deadline(order: Order) -> datetime | None:
    if (
        order.status not in {OrderStatus.RESULT_READY, OrderStatus.COMPLETED}
        or not order.result_notified_at
    ):
        return None
    folder = order.disk_folder
    if (
        folder is None
        or folder.deleted_at
        or folder.deletion_operation_id
        or folder.deletion_succeeded
    ):
        return None
    deletion = order.deletion_request
    if deletion is not None:
        if deletion.status == DeletionStatus.PERFORMED:
            return None
        return effective_due_at(order, deletion)
    return order.result_notified_at + timedelta(days=14)


def queue_deletion_reminders(db: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    orders = db.scalars(
        select(Order)
        .join(DiskFolder)
        .where(
            Order.status.in_([OrderStatus.RESULT_READY, OrderStatus.COMPLETED]),
            DiskFolder.deleted_at.is_(None),
        )
        .order_by(Order.id)
        .with_for_update(of=Order, skip_locked=True)
    ).all()
    count = 0
    for order in orders:
        deadline = deletion_deadline(order)
        if deadline is not None and deadline <= now:
            key = f"deletion_due:{order.id}:{deadline.isoformat()}"
            if db.scalar(select(Notification.id).where(Notification.dedup_key == key)) is None:
                enqueue(
                    db,
                    "deletion_due",
                    order_id=order.id,
                    payload={"due_at": deadline.isoformat()},
                    dedup_key=key,
                )
                count += 1
    db.commit()
    return count


def _deliver(
    db: Session, item: Notification, settings: Settings, auth_mailer, order_mailer, mailer, telegram
) -> bool:
    # Late import: authentication also enqueues jobs through this module.
    from sinegor.modules.auth.service import issue_and_send_link
    from sinegor.modules.orders.service import locked_order, transition

    if item.kind in {"invitation", "magic_link"}:
        customer = db.scalar(
            select(Customer).where(Customer.email == item.recipient).with_for_update()
        )
        if customer is None or item.customer_id is not None and item.customer_id != customer.id:
            return False
        purpose = TokenPurpose.INVITATION if item.kind == "invitation" else TokenPurpose.MAGIC_LINK
        # The raw token exists only in memory and the outgoing email, never in the outbox.
        issue_and_send_link(db, settings, auth_mailer, customer, purpose)
        return True
    if item.kind == "consultation":
        text = "SINEGOR — заявка на консультацию\nEmail: " + item.recipient
        # Older pending jobs contain only email and must still be deliverable.
        if phone := item.payload.get("phone"):
            text += "\nТелефон: " + phone
        telegram.send(text)
        return True
    order = locked_order(db, item.order_id)
    if item.kind == "deletion_due":
        deadline = deletion_deadline(order)
        if (
            deadline is None
            or deadline > datetime.now(UTC)
            or deadline.isoformat() != item.payload["due_at"]
        ):
            return False
        telegram.send(
            f"SINEGOR — наступил срок удаления материалов заказа №{order.number}.\n"
            "Требуется решение администратора; автоматического удаления нет.\n"
            f"{str(settings.public_origin).rstrip('/')}/admin/orders/{order.id}"
        )
        return True
    if order.customer.email != item.recipient and item.kind != "agreement_returned":
        return False  # An email edit revokes deliveries addressed to the previous identity.
    if item.kind == "result_ready":
        if order.status in {OrderStatus.RESULT_READY, OrderStatus.COMPLETED}:
            return True  # Domain commit succeeded before a worker restart.
        if order.status != OrderStatus.IN_PROGRESS:
            return False
        transition(
            db, order, OrderStatus.RESULT_READY, UUID(item.payload["admin_id"]), mailer=order_mailer
        )
        db.commit()
        return True
    if item.kind.startswith("agreement_"):
        if order.status == OrderStatus.CANCELLED:
            return False
        agreement = db.scalar(select(Agreement).where(Agreement.order_id == order.id))
        expected = {
            "agreement_initial": AgreementStatus.AWAITING_CUSTOMER,
            "agreement_returned": AgreementStatus.UNDER_REVIEW,
            "agreement_approved": AgreementStatus.APPROVED,
            "agreement_rejected": AgreementStatus.REJECTED,
        }
        if (
            agreement is None
            or agreement.revision != item.payload["revision"]
            or agreement.status != expected[item.kind]
        ):
            return False
        recipient = item.recipient
        if item.kind == "agreement_returned":
            recipient = str(settings.notification_admin_email or settings.smtp_from or "")
        if not recipient:
            raise MailDeliveryError("Administrator email is not configured")
        mailer.send_agreement_notice(recipient, order.number, item.kind)
        return True
    raise ValueError("Unknown notification kind")


def deliver_one(
    db: Session,
    settings: Settings,
    identifier: UUID,
    *,
    auth_mailer,
    order_mailer,
    mailer,
    telegram,
    force: bool = False,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    item = db.scalar(
        select(Notification)
        .where(Notification.id == identifier)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if item is None:
        db.rollback()
        return False
    if item.status in {"sent", "cancelled"}:
        already_sent = item.status == "sent"
        db.commit()
        return already_sent
    if (
        item.status == "processing"
        and item.lease_until > now
        or not force
        and item.available_at > now
    ):
        db.rollback()
        return False
    lease = uuid4()
    item.status, item.lease_id = "processing", lease
    item.lease_until = now + timedelta(minutes=5)
    item.attempts += 1
    attempt = item.attempts
    db.commit()
    error_code, delay = None, min(3600, 30 * 2 ** min(attempt - 1, 7))
    try:
        sent = _deliver(db, item, settings, auth_mailer, order_mailer, mailer, telegram)
        state = "sent" if sent else "cancelled"
        db.commit()
    except Exception as exc:
        db.rollback()
        error_code = (
            "telegram_failed"
            if isinstance(exc, TelegramDeliveryError)
            else "smtp_failed"
            if isinstance(exc, MailDeliveryError)
            else "delivery_failed"
        )
        if isinstance(exc, TelegramDeliveryError) and exc.retry_after:
            delay = max(delay, exc.retry_after)
        logger.error("notification_delivery_failed", extra={"exception_type": type(exc).__name__})
        state = "pending"
    values = dict(
        status=state,
        lease_id=None,
        lease_until=None,
        last_error_code=error_code,
        available_at=max(now, datetime.now(UTC)) + timedelta(seconds=delay),
    )
    if state in {"sent", "cancelled"}:
        values.update(
            recipient=None, payload={}, sent_at=datetime.now(UTC) if state == "sent" else None
        )
    db.execute(
        update(Notification)
        .where(Notification.id == identifier, Notification.lease_id == lease)
        .values(**values)
    )
    db.commit()
    return state == "sent"


def deliver_from_app(app, identifier: UUID, *, force: bool = False) -> bool:
    with app.state.session_factory() as db:
        try:
            return deliver_one(
                db,
                app.state.settings,
                identifier,
                auth_mailer=app.state.auth_mailer,
                order_mailer=app.state.order_mailer,
                mailer=app.state.notification_mailer,
                telegram=app.state.telegram_notifier,
                force=force,
            )
        except Exception as exc:
            db.rollback()
            logger.error("notification_worker_failed", extra={"exception_type": type(exc).__name__})
            return False


def process_pending(
    db: Session,
    settings: Settings,
    *,
    auth_mailer,
    order_mailer,
    mailer,
    telegram,
    limit: int = 100,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    identifiers = list(
        db.scalars(
            select(Notification.id)
            .where(
                or_(
                    Notification.status == "pending",
                    (Notification.status == "processing") & (Notification.lease_until <= now),
                ),
                Notification.available_at <= now,
            )
            .order_by(Notification.created_at, Notification.id)
            .limit(limit)
        )
    )
    db.commit()
    return sum(
        deliver_one(
            db,
            settings,
            identifier,
            auth_mailer=auth_mailer,
            order_mailer=order_mailer,
            mailer=mailer,
            telegram=telegram,
            now=now,
        )
        for identifier in identifiers
    )


def deliver_order_from_app(app, order_id: UUID) -> None:
    with app.state.session_factory() as db:
        identifiers = list(
            db.scalars(
                select(Notification.id).where(
                    Notification.order_id == order_id,
                    Notification.status == "pending",
                )
            )
        )
        db.commit()
    for identifier in identifiers:
        deliver_from_app(app, identifier)

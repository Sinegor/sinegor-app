"""Durable retries with short claims; delivery is at least once, not proof of reading."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select, update
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
from sinegor.modules.notifications.consultations import (
    MANUAL_RETRY,
    contact_deadline,
    expire_consultation,
    purge_expired_consultations,
    retry_not_before,
)
from sinegor.modules.notifications.models import Notification
from sinegor.modules.notifications.retry import (
    TELEGRAM_KINDS,
    deadline,
    deadline_expression,
    retry_delay,
)
from sinegor.modules.orders.models import Order
from sinegor.modules.retention.service import effective_due_at
from sinegor.modules.security_events.service import Actor

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
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if customer.blocked_at is not None:
        raise HTTPException(409, "Customer access is blocked")
    active = db.scalar(
        select(Notification.id)
        .where(
            Notification.customer_id == customer.id,
            Notification.kind == "invitation",
            Notification.recipient == customer.email,
            Notification.status.in_(["pending", "processing", "failed", "expired"]),
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
    db: Session,
    item: Notification,
    settings: Settings,
    auth_mailer,
    order_mailer,
    mailer,
    telegram,
    *,
    actor: Actor | None = None,
) -> bool:
    # Late import: authentication also enqueues jobs through this module.
    from sinegor.modules.auth.service import issue_and_send_link
    from sinegor.modules.orders.service import locked_order, transition

    if item.kind in {"invitation", "magic_link"}:
        customer = db.scalar(
            select(Customer)
            .where(Customer.email == item.recipient)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if (
            customer is None
            or customer.blocked_at is not None
            or item.customer_id is not None
            and item.customer_id != customer.id
        ):
            return False
        db.refresh(item)
        if item.status != "processing" or item.recipient != customer.email:
            return False
        purpose = TokenPurpose.INVITATION if item.kind == "invitation" else TokenPurpose.MAGIC_LINK
        # The raw token exists only in memory and the outgoing email, never in the outbox.
        issue_and_send_link(db, settings, auth_mailer, customer, purpose, actor=actor)
        return True
    if item.kind in {"customer_blocked", "customer_unblocked"}:
        customer = db.scalar(
            select(Customer)
            .where(Customer.id == item.customer_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if (
            customer is None
            or customer.email != item.recipient
            or customer.access_revision != item.payload.get("access_revision")
            or (customer.blocked_at is not None) != (item.kind == "customer_blocked")
        ):
            return False
        mailer.send_access_notice(customer.email, customer.block_reason)
        return True
    if item.kind == "consultation":
        recipient = str(settings.notification_admin_email or settings.smtp_from or "")
        if not recipient:
            raise MailDeliveryError("Administrator email is not configured", permanent=True)
        # Older pending jobs contain only email and must still be deliverable.
        mailer.send_consultation_notice(recipient, item.recipient, item.payload.get("phone"))
        return True
    if item.kind == "consultation_telegram":
        telegram.send("Поступила новая заявка на консультацию")
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
            raise MailDeliveryError("Administrator email is not configured", permanent=True)
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
    actor: Actor | None = None,
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
    if item.kind in {"consultation", "consultation_telegram"} and now >= contact_deadline(item):
        expire_consultation(item)
        db.commit()
        return item.status == "sent"
    if item.status in {"sent", "cancelled"}:
        already_sent = item.status == "sent"
        db.commit()
        return already_sent
    if item.status == "processing" and item.lease_until > now:
        db.rollback()
        return False
    if force and retry_not_before(item, now) is not None:
        db.rollback()
        return False
    # Explicit administrator actions may retry a stopped job, but never a sent one.
    if not force:
        if item.status in {"failed", "expired"}:
            db.commit()
            return False
        if now >= deadline(item) and item.last_error_code != MANUAL_RETRY:
            item.status, item.lease_id, item.lease_until = "expired", None, None
            db.commit()
            return False
        if item.available_at > now:
            db.rollback()
            return False
    lease = uuid4()
    item.status, item.lease_id = "processing", lease
    item.lease_until = now + timedelta(minutes=5)
    item.attempts += 1
    attempt = item.attempts
    db.commit()
    error_code, delay = None, retry_delay(settings, attempt)
    try:
        sent = _deliver(
            db, item, settings, auth_mailer, order_mailer, mailer, telegram, actor=actor
        )
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
        permanent = isinstance(exc, (TelegramDeliveryError, MailDeliveryError)) and exc.permanent
        if permanent:
            error_code = (
                "telegram_permanent" if isinstance(exc, TelegramDeliveryError) else "smtp_permanent"
            )
        if isinstance(exc, TelegramDeliveryError) and exc.retry_after:
            error_code = "telegram_rate_limited"
            delay = max(delay, exc.retry_after)
        logger.error("notification_delivery_failed", extra={"exception_type": type(exc).__name__})
        state = "failed" if permanent else "pending"
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


def deliver_from_app(
    app,
    identifier: UUID,
    *,
    force: bool = False,
    actor: Actor | None = None,
) -> bool:
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
                actor=actor,
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
    # Retention is independent of queue capacity, provider failures and retry state.
    purge_expired_consultations(db, now=now)
    identifiers = list(
        db.scalars(
            select(Notification.id)
            .where(
                or_(
                    Notification.status == "pending",
                    (Notification.status == "processing") & (Notification.lease_until <= now),
                ),
                or_(Notification.available_at <= now, deadline_expression() <= now),
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


def delivery_summary(db: Session, *, now: datetime | None = None) -> list[dict]:
    """Only aggregate safe state for the admin shell, never contact data or provider text."""
    now = now or datetime.now(UTC)
    channel = case((Notification.kind.in_(TELEGRAM_KINDS), "telegram"), else_="smtp")
    reason = case(
        (Notification.status == "failed", "permanent"),
        (or_(Notification.status == "expired", deadline_expression() <= now), "expired"),
        (
            (Notification.kind.in_(["customer_blocked", "customer_unblocked"]))
            & Notification.last_error_code.is_not(None),
            "temporary",
        ),
        else_="delayed",
    )
    rows = db.execute(
        select(channel.label("channel"), reason.label("reason"), func.count().label("count"))
        .where(
            Notification.status.in_(["pending", "processing", "failed", "expired"]),
            or_(
                Notification.status.in_(["failed", "expired"]),
                Notification.created_at <= now - timedelta(hours=24),
                Notification.kind.in_(["customer_blocked", "customer_unblocked"])
                & Notification.last_error_code.is_not(None),
            ),
        )
        .group_by(channel, reason)
        .order_by(channel, reason)
    )
    return [dict(row._mapping) for row in rows]

"""Minimal administrator recovery view over the outbox; no separate contact store."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from sinegor.modules.destruction import service as destruction
from sinegor.modules.notifications.models import Notification
from sinegor.modules.notifications.retry import CONSULTATION_KINDS

HANDLED = "manually_handled"
MANUAL_RETRY = "manual_retry"
CONTACTS_EXPIRED = "contacts_expired"
UNDELIVERED = ("pending", "processing", "failed", "expired")


def contact_deadline(item: Notification) -> datetime:
    return item.created_at + timedelta(days=7)


def _destruction_metadata(items: list[Notification], initiator: str, basis: str | None) -> dict:
    subjects = []
    for item in items:
        categories = []
        if item.recipient:
            categories.append("Адрес электронной почты")
        if item.payload.get("phone"):
            categories.append("Номер телефона")
        if any(value for key, value in item.payload.items() if key != "phone"):
            categories.append("Сведения обращения за консультацией")
        if not categories:
            continue
        identity = item.recipient or item.payload.get("phone")
        subjects.append(
            {
                "identity": identity or "Субъект не установлен по сохранившимся сведениям",
                "categories": categories,
                "source": "notifications.recipient" if item.recipient else "notifications.payload",
            }
        )
    return {
        "subjects": subjects,
        "entity": {"notification_ids": ",".join(str(item.id) for item in items)},
        "source": "notifications",
        "basis": basis,
        "method": "Обнуление recipient и очистка payload в PostgreSQL",
        "initiator": initiator,
        "executor": "FastAPI",
    }


def expire_consultation(item: Notification, *, db: Session | None = None) -> None:
    """Caller holds the row lock and has checked the seven-day contact deadline."""
    operation = None
    if db is not None:
        metadata = _destruction_metadata(
            [item], "scheduler", "Истечение семидневного срока хранения"
        )
        if metadata["subjects"]:
            operation = destruction.prepare(
                db, key=f"consultation_auto:{item.id}", kind="consultation_auto", metadata=metadata
            )
    if item.status not in {"sent", "cancelled"}:
        item.status = "expired"
    item.last_error_code = (
        CONTACTS_EXPIRED
        if item.status == "expired"
        else HANDLED
        if item.status == "cancelled" and item.last_error_code == HANDLED
        else None
    )
    item.recipient, item.payload = None, {}
    item.lease_id = item.lease_until = None
    if operation is not None:
        db.flush()
        destruction.confirm(db, operation)


def purge_expired_consultations(db: Session, *, now: datetime | None = None) -> int:
    """Scrub overdue contacts even when automatic delivery has already stopped."""
    now = now or datetime.now(UTC)
    items = db.scalars(
        select(Notification)
        .where(
            Notification.kind.in_(CONSULTATION_KINDS),
            Notification.created_at <= now - timedelta(days=7),
            or_(
                Notification.recipient.is_not(None),
                Notification.payload != {},
                Notification.status.in_(("pending", "processing", "failed")),
                Notification.last_error_code.not_in((HANDLED, CONTACTS_EXPIRED)),
            ),
        )
        # Match administrative actions: lock SMTP roots before Telegram partners.
        .order_by(Notification.kind, Notification.created_at, Notification.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    for item in items:
        # Revoke even an active lease: it cannot extend the contact retention window.
        # The delivery worker's lease-conditional update cannot restore cleared data.
        expire_consultation(item, db=db)
    db.commit()
    return len(items)


def retry_not_before(item: Notification, now: datetime) -> datetime | None:
    # Older jobs did not distinguish Retry-After from other Telegram failures.
    # Preserve their saved waiting interval rather than risk sending too early.
    if (
        item.kind == "consultation_telegram"
        and item.last_error_code in {"telegram_rate_limited", "telegram_failed"}
        and item.available_at > now
    ):
        return item.available_at
    return None


def _channel(item: Notification, now: datetime) -> dict:
    reason = None
    if item.status in UNDELIVERED:
        if (
            item.last_error_code == MANUAL_RETRY
            and item.status in {"pending", "processing"}
            and now < contact_deadline(item)
        ):
            reason = "awaiting"
        elif item.status == "failed":
            reason = "permanent"
        elif item.status == "expired" or now >= item.created_at + timedelta(days=3):
            reason = "expired"
        elif item.last_error_code:
            reason = "temporary"
        else:
            reason = "awaiting"
    return {
        "channel": "smtp" if item.kind == "consultation" else "telegram",
        "status": item.status,
        "retry_after": retry_not_before(item, now),
        "reason": reason,
        "attention": item.status in UNDELIVERED
        and (item.status in {"failed", "expired"} or now >= item.created_at + timedelta(hours=24)),
    }


def list_consultations(
    db: Session,
    *,
    view: str = "active",
    limit: int = 25,
    offset: int = 0,
    now: datetime | None = None,
) -> list[dict]:
    now = now or datetime.now(UTC)
    telegram = aliased(Notification)
    handled = or_(
        func.coalesce(Notification.last_error_code == HANDLED, False),
        func.coalesce(telegram.last_error_code == HANDLED, False),
    )
    rows = db.execute(
        select(Notification, telegram)
        .outerjoin(
            telegram,
            (telegram.kind == "consultation_telegram")
            & (telegram.dedup_key == "consultation_telegram:" + cast(Notification.id, String)),
        )
        .where(
            Notification.kind == "consultation",
            handled
            if view == "handled"
            else ~handled
            & or_(Notification.status.in_(UNDELIVERED), telegram.status.in_(UNDELIVERED)),
        )
        .order_by(Notification.created_at, Notification.id)
        .limit(limit)
        .offset(offset)
    )
    result = []
    for root, partner in rows:
        is_handled = root.last_error_code == HANDLED or (
            partner is not None and partner.last_error_code == HANDLED
        )
        cutoff = contact_deadline(root)
        contacts_available = (
            not is_handled and root.status in UNDELIVERED and now < cutoff and bool(root.recipient)
        )
        result.append(
            {
                "id": root.id,
                "created_at": root.created_at,
                "observed_at": now,
                "contacts_expires_at": cutoff,
                "email": root.recipient if contacts_available else None,
                "phone": root.payload.get("phone") if contacts_available else None,
                "contacts_expiring": bool(contacts_available and now >= cutoff - timedelta(days=1)),
                "status": "handled" if is_handled else "unresolved",
                "channels": [_channel(item, now) for item in (root, partner) if item is not None],
                "can_handle": not is_handled
                and not any(item.status == "processing" for item in (root, partner) if item),
                "can_retry": not is_handled and now < cutoff,
            }
        )
    return result


def _locked_pair(db: Session, identifier: UUID) -> list[Notification]:
    root = db.scalar(
        select(Notification)
        .where(Notification.id == identifier, Notification.kind == "consultation")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if root is None:
        raise HTTPException(404, "Consultation not found")
    partner = db.scalar(
        select(Notification)
        .where(
            Notification.kind == "consultation_telegram",
            Notification.dedup_key == f"consultation_telegram:{root.id}",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return [root] + ([partner] if partner is not None else [])


def retry_consultation(db: Session, identifier: UUID, channel: str) -> UUID:
    items = _locked_pair(db, identifier)
    if datetime.now(UTC) >= contact_deadline(items[0]) or any(
        item.last_error_code == HANDLED for item in items
    ):
        raise HTTPException(409, "Consultation is no longer available for delivery")
    kind = "consultation" if channel == "smtp" else "consultation_telegram"
    item = next((item for item in items if item.kind == kind), None)
    if item is None or item.status not in {"pending", "failed", "expired"}:
        raise HTTPException(409, "Channel is not available for retry")
    now = datetime.now(UTC)
    if retry_not_before(item, now) is not None:
        raise HTTPException(409, "Provider retry interval has not elapsed")
    # Persist one explicit attempt so a restart cannot lose the accepted action.
    # A failure replaces this marker; it does not renew the automatic retry period.
    item.status, item.available_at, item.last_error_code = "pending", now, MANUAL_RETRY
    db.commit()
    return item.id


def handle_consultation(db: Session, identifier: UUID, admin_id: UUID | None = None) -> None:
    items = _locked_pair(db, identifier)
    if any(item.status == "processing" for item in items):
        raise HTTPException(409, "Delivery is in progress")
    if not any(item.status in UNDELIVERED or item.last_error_code == HANDLED for item in items):
        raise HTTPException(409, "Consultation is already delivered")
    operation = None
    metadata = _destruction_metadata(
        items, f"admin:{admin_id}" if admin_id else "Администратор не установлен", None
    )
    if metadata["subjects"]:
        operation = destruction.prepare(
            db,
            key=f"consultation_manual:{identifier}",
            kind="consultation_manual",
            metadata=metadata,
        )
    for item in items:
        if item.status in UNDELIVERED:
            item.status = "cancelled"
            item.last_error_code = HANDLED
            item.lease_id = item.lease_until = None
        item.recipient, item.payload = None, {}
    if operation is not None:
        db.flush()
        destruction.confirm(db, operation)
    db.commit()

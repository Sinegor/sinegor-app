"""Safe administrator monitoring over the outbox, with one selection for both views."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from sinegor.modules.notifications.models import Notification
from sinegor.modules.notifications.retry import TELEGRAM_KINDS, deadline_expression

SAFE_ERROR_CODES = frozenset(
    {
        "smtp_failed",
        "smtp_permanent",
        "telegram_failed",
        "telegram_permanent",
        "telegram_rate_limited",
        "delivery_failed",
        "contacts_expired",
        "manual_retry",
    }
)


def _problems(now: datetime):
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
    return select(
        Notification.id,
        Notification.kind,
        Notification.status,
        Notification.created_at,
        Notification.available_at,
        Notification.attempts,
        Notification.last_error_code,
        Notification.order_id,
        Notification.customer_id,
        channel.label("channel"),
        reason.label("reason"),
    ).where(
        Notification.status.in_(["pending", "processing", "failed", "expired"]),
        or_(
            Notification.status.in_(["failed", "expired"]),
            Notification.created_at <= now - timedelta(hours=24),
            Notification.kind.in_(["customer_blocked", "customer_unblocked"])
            & Notification.last_error_code.is_not(None),
        ),
    )


def delivery_summary(db: Session, *, now: datetime | None = None) -> list[dict]:
    """Only aggregate safe state for the admin shell, never contact data or provider text."""
    problems = _problems(now or datetime.now(UTC)).subquery()
    channel, reason = problems.c.channel, problems.c.reason
    rows = db.execute(
        select(channel, reason, func.count().label("count"))
        .group_by(channel, reason)
        .order_by(channel, reason)
    )
    return [dict(row._mapping) for row in rows]


def list_delivery_problems(
    db: Session, *, limit: int = 25, offset: int = 0, now: datetime | None = None
) -> list[dict]:
    rows = db.execute(
        _problems(now or datetime.now(UTC))
        .order_by(Notification.created_at, Notification.id)
        .limit(limit)
        .offset(offset)
    )
    result = []
    for row in rows:
        item = dict(row._mapping)
        code = item.pop("last_error_code")
        item["error_code"] = code if code in SAFE_ERROR_CODES else None
        result.append(item)
    return result

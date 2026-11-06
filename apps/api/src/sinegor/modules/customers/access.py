"""Access changes share the customer lock with credential issuance and consumption."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, or_, update
from sqlalchemy.orm import Session as DBSession

from sinegor.modules.auth.models import AuthToken, Session
from sinegor.modules.customers.models import Customer
from sinegor.modules.notifications.models import Notification
from sinegor.modules.notifications.service import enqueue
from sinegor.modules.security_events.service import record


def change_access(
    db: DBSession,
    customer: Customer,
    admin_id: UUID,
    *,
    reason: str | None = None,
    comment: str | None = None,
) -> UUID | None:
    # Caller holds a customer row lock until this transaction commits.
    blocked = reason is not None
    if (customer.blocked_at is not None) == blocked:
        db.commit()
        return None
    now = datetime.now(UTC)
    customer.blocked_at = now if blocked else None
    customer.block_reason = reason
    customer.block_comment = (comment or None) if blocked else None
    customer.access_revision += 1
    kind = "customer_blocked" if blocked else "customer_unblocked"
    if blocked:
        db.execute(
            delete(AuthToken).where(
                AuthToken.customer_id == customer.id, AuthToken.used_at.is_(None)
            )
        )
        db.execute(
            update(Session)
            .where(Session.customer_id == customer.id, Session.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        # Revoke queued access deliveries as well; otherwise a delayed job could issue a
        # fresh link after unblocking. Workers recheck status under the same customer lock.
        db.execute(
            update(Notification)
            .where(
                Notification.kind.in_(["invitation", "magic_link"]),
                or_(
                    Notification.customer_id == customer.id,
                    Notification.recipient == customer.email,
                ),
                Notification.status.not_in(["sent", "cancelled"]),
            )
            .values(status="cancelled", recipient=None, payload={}, lease_id=None, lease_until=None)
        )
    db.execute(
        update(Notification)
        .where(
            Notification.customer_id == customer.id,
            Notification.kind.in_(["customer_blocked", "customer_unblocked"]),
            Notification.status.not_in(["sent", "cancelled"]),
        )
        .values(status="cancelled", recipient=None, payload={}, lease_id=None, lease_until=None)
    )
    record(
        db,
        "privilege_changed",
        kind,
        user_id=admin_id,
        user_role="admin",
        subject_user_id=customer.id,
    )
    if blocked:
        record(
            db,
            "credential_revoked",
            kind,
            user_id=admin_id,
            user_role="admin",
            subject_user_id=customer.id,
        )
    identifier = enqueue(
        db,
        kind,
        customer_id=customer.id,
        recipient=customer.email,
        payload={"access_revision": customer.access_revision},
    )
    db.commit()
    return identifier

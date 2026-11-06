"""Append-only security facts, separate from permanent business history."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from sinegor.db.base import Base

EventType = Literal[
    "authentication",
    "rate_limit",
    "access_denied",
    "credential_issued",
    "credential_revoked",
    "privilege_changed",
]
Result = Literal["success", "failure"]
Reason = Literal[
    "admin_login",
    "magic_link_login",
    "invalid_credentials",
    "invalid_request",
    "attempt_limit",
    "authentication_required",
    "admin_required",
    "customer_required",
    "order_not_owned",
    "csrf_failed",
    "session_created",
    "session_rotated",
    "logout",
    "magic_link_issued",
    "invitation_issued",
    "link_replaced",
    "link_consumed",
    "delivery_failed",
    "email_changed",
    "admin_created",
    "agreement_required",
    "customer_blocked",
    "customer_unblocked",
]


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('authentication', 'rate_limit', 'access_denied', "
            "'credential_issued', 'credential_revoked', 'privilege_changed')",
            name="event_type",
        ),
        CheckConstraint("result IN ('success', 'failure')", name="result"),
        CheckConstraint(
            "reason_code IN ('admin_login', 'magic_link_login', 'invalid_credentials', "
            "'invalid_request', 'attempt_limit', 'authentication_required', 'admin_required', "
            "'customer_required', 'order_not_owned', 'csrf_failed', 'session_created', "
            "'session_rotated', 'logout', 'magic_link_issued', 'invitation_issued', "
            "'link_replaced', 'link_consumed', 'delivery_failed', "
            "'email_changed', 'admin_created', 'agreement_required', "
            "'customer_blocked', 'customer_unblocked')",
            name="reason_code",
        ),
        CheckConstraint("request_id ~ '^[0-9a-f]{32}$'", name="request_id"),
        CheckConstraint(
            "user_role IS NULL OR user_role IN ('admin', 'customer')", name="user_role"
        ),
        CheckConstraint("(user_id IS NULL) = (user_role IS NULL)", name="known_user"),
        Index("ix_security_events_recorded_at", "recorded_at"),
        Index("ix_security_events_event_type_recorded_at", "event_type", "recorded_at"),
        {"schema": "public"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.statement_timestamp()
    )
    event_type: Mapped[str] = mapped_column(String(24))
    result: Mapped[str] = mapped_column(String(7))
    user_id: Mapped[UUID | None]
    user_role: Mapped[str | None] = mapped_column(String(8))
    subject_user_id: Mapped[UUID | None]
    request_id: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(32))

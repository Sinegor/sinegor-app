"""Delivery outbox, not a CRM: contact data is cleared after delivery/cancellation."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sinegor.db.base import Base
from sinegor.db.mixins import Entity


class Notification(Entity, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("status IN ('pending','processing','sent','cancelled')", name="status"),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint(
            "(status = 'processing') = (lease_id IS NOT NULL AND lease_until IS NOT NULL)",
            name="lease",
        ),
        Index("ix_notifications_status_available_at", "status", "available_at"),
    )
    kind: Mapped[str] = mapped_column(String(32))
    dedup_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    customer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT")
    )
    recipient: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_id: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(32))

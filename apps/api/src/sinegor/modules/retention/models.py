from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sinegor.db.base import Base
from sinegor.db.mixins import Entity
from sinegor.db.types import DeletionReason, DeletionStatus, enum_column

if TYPE_CHECKING:
    from sinegor.modules.auth.models import AdminUser
    from sinegor.modules.orders.models import Order


class DeletionRequest(Entity, Base):
    __tablename__ = "deletion_requests"
    __table_args__ = (
        CheckConstraint(
            "reason <> 'early_permission' OR early_authorized_at IS NOT NULL",
            name="early_permission",
        ),
        CheckConstraint(
            "status NOT IN ('confirmed', 'performed', 'error') OR "
            "(confirmed_at IS NOT NULL AND confirmed_by_id IS NOT NULL)",
            name="admin_confirmation",
        ),
        CheckConstraint(
            "status <> 'deferred' OR (deferred_until IS NOT NULL "
            "AND nullif(btrim(admin_note), '') IS NOT NULL)",
            name="deferral_evidence",
        ),
        CheckConstraint(
            "(status = 'performed') = (performed_at IS NOT NULL)", name="performed_status"
        ),
        CheckConstraint(
            "performed_at IS NULL OR (confirmed_at IS NOT NULL AND performed_at >= confirmed_at)",
            name="performed_time",
        ),
        Index("ix_deletion_requests_status_due_at", "status", "due_at"),
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), unique=True
    )
    reason: Mapped[DeletionReason] = mapped_column(enum_column(DeletionReason, "deletion_reason"))
    status: Mapped[DeletionStatus] = mapped_column(
        enum_column(DeletionStatus, "deletion_status"),
        server_default=DeletionStatus.WAITING.value,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    early_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deferred_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_note: Mapped[str | None] = mapped_column(Text)
    order: Mapped[Order] = relationship(back_populates="deletion_request")
    confirmed_by: Mapped[AdminUser | None] = relationship()


class RetentionFileDeletion(Entity, Base):
    """Committed deletion intent after an expired order graph has been removed.

    No FK to the deleted order: retries survive removal of business history.
    This is a work queue, not a destruction record or proof of deletion.
    """

    __tablename__ = "retention_file_deletions"
    __table_args__ = (Index("ix_retention_file_deletions_attempt", "last_attempted_at", "id"),)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_key: Mapped[str] = mapped_column(Text, unique=True)
    # Independent registry survives deletion of the order and its agreement.
    operation_id: Mapped[UUID | None] = mapped_column(index=True)

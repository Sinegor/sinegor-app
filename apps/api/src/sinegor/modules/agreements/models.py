from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sinegor.db.base import Base
from sinegor.db.mixins import Entity
from sinegor.db.types import AgreementStatus, enum_column

if TYPE_CHECKING:
    from sinegor.modules.auth.models import AdminUser
    from sinegor.modules.orders.models import Order


class Agreement(Entity, Base):
    __tablename__ = "agreements"
    __table_args__ = (
        CheckConstraint(
            "final_sha256 IS NULL OR final_sha256 ~ '^[0-9a-f]{64}$'",
            name="final_sha256_format",
        ),
        CheckConstraint(
            "status <> 'approved' OR (nullif(btrim(final_pdf_key), '') IS NOT NULL "
            "AND final_sha256 IS NOT NULL "
            "AND verified_at IS NOT NULL AND verified_by_id IS NOT NULL)",
            name="approved_evidence",
        ),
        CheckConstraint(
            "verified_at IS NULL OR verified_at >= created_at", name="verification_time"
        ),
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[AgreementStatus] = mapped_column(
        enum_column(AgreementStatus, "agreement_status"),
        server_default=AgreementStatus.AWAITING_CUSTOMER.value,
    )
    initial_pdf_key: Mapped[str | None] = mapped_column(Text)
    returned_pdf_key: Mapped[str | None] = mapped_column(Text)
    final_pdf_key: Mapped[str | None] = mapped_column(Text)
    final_sha256: Mapped[str | None] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    order: Mapped[Order] = relationship(back_populates="agreement")
    verified_by: Mapped[AdminUser | None] = relationship()

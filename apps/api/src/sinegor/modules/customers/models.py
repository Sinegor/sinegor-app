from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from sinegor.db.base import Base
from sinegor.db.mixins import Entity

if TYPE_CHECKING:
    from sinegor.modules.orders.models import Order


class Customer(Entity, Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "(blocked_at IS NULL AND block_reason IS NULL AND block_comment IS NULL) OR "
            "(blocked_at IS NOT NULL AND block_reason IS NOT NULL AND "
            "length(btrim(block_reason)) BETWEEN 1 AND 2000 AND "
            "(block_comment IS NULL OR length(block_comment) <= 2000))",
            name="block_details",
        ),
        CheckConstraint(
            "email = lower(btrim(email)) AND email <> '' AND email !~ '[[:space:]]'",
            name="normalized_email",
        ),
    )

    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    block_reason: Mapped[str | None] = mapped_column(Text)
    block_comment: Mapped[str | None] = mapped_column(Text)
    access_revision: Mapped[int] = mapped_column(Integer, server_default="0")

    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    orders: Mapped[list[Order]] = relationship(back_populates="customer", passive_deletes="all")

    @validates("email")
    def normalize_email(self, key: str, value: str) -> str:
        return value.strip().lower()

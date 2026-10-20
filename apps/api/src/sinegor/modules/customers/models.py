from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from sinegor.db.base import Base
from sinegor.db.mixins import Entity

if TYPE_CHECKING:
    from sinegor.modules.orders.models import Order


class Customer(Entity, Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "email = lower(btrim(email)) AND email <> '' AND email !~ '[[:space:]]'",
            name="normalized_email",
        ),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    orders: Mapped[list[Order]] = relationship(back_populates="customer", passive_deletes="all")

    @validates("email")
    def normalize_email(self, key: str, value: str) -> str:
        return value.strip().lower()

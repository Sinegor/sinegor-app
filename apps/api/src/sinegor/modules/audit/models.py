from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sinegor.db.base import Base
from sinegor.db.mixins import Entity

if TYPE_CHECKING:
    from sinegor.modules.auth.models import AdminUser
    from sinegor.modules.customers.models import Customer
    from sinegor.modules.orders.models import Order


class OrderEvent(Entity, Base):
    __tablename__ = "order_events"
    __table_args__ = (
        CheckConstraint("event_type ~ '^[a-z][a-z0-9_]*$'", name="event_type_format"),
        CheckConstraint(
            "actor_customer_id IS NULL OR actor_admin_id IS NULL", name="at_most_one_actor"
        ),
        Index("ix_order_events_order_id_created_at", "order_id", "created_at"),
    )
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(String(64))
    actor_customer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT")
    )
    actor_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    order: Mapped[Order] = relationship(back_populates="events")
    actor_customer: Mapped[Customer | None] = relationship()
    actor_admin: Mapped[AdminUser | None] = relationship()

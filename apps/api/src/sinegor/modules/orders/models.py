from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sinegor.db.base import Base
from sinegor.db.mixins import Entity
from sinegor.db.types import OrderStatus, PaymentStatus, ServiceType, enum_column

if TYPE_CHECKING:
    from sinegor.modules.agreements.models import Agreement
    from sinegor.modules.audit.models import OrderEvent
    from sinegor.modules.auth.models import AdminUser
    from sinegor.modules.customers.models import Customer
    from sinegor.modules.disk.models import DiskFolder
    from sinegor.modules.retention.models import DeletionRequest


class Order(Entity, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "agreed_price IS NULL OR (agreed_price >= 0 AND agreed_price <> 'NaN'::numeric)",
            name="nonnegative_price",
        ),
        CheckConstraint("ready_at IS NULL OR ready_at >= created_at", name="ready_time"),
        CheckConstraint(
            "result_notified_at IS NULL OR "
            "(ready_at IS NOT NULL AND result_notified_at >= ready_at)",
            name="notification_time",
        ),
        CheckConstraint(
            "status NOT IN ('result_ready', 'completed') OR "
            "(ready_at IS NOT NULL AND result_notified_at IS NOT NULL)",
            name="ready_evidence",
        ),
        CheckConstraint(
            "(status IN ('completed', 'cancelled')) = (closed_at IS NOT NULL)",
            name="closed_status",
        ),
        CheckConstraint("closed_at IS NULL OR closed_at >= created_at", name="closed_time"),
        CheckConstraint(
            "status <> 'completed' OR closed_at >= result_notified_at",
            name="completion_time",
        ),
        Index("ix_orders_status_ready_at", "status", "ready_at"),
    )

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    service_type: Mapped[ServiceType] = mapped_column(enum_column(ServiceType, "service_type"))
    description: Mapped[str | None] = mapped_column(Text)
    agreed_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus, "order_status"),
        server_default=OrderStatus.AWAITING_AGREEMENT.value,
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship(back_populates="orders")
    agreement: Mapped[Agreement | None] = relationship(
        back_populates="order", passive_deletes="all"
    )
    disk_folder: Mapped[DiskFolder | None] = relationship(
        back_populates="order", passive_deletes="all"
    )
    material_handover: Mapped[MaterialHandover | None] = relationship(
        back_populates="order",
        passive_deletes="all",
    )
    payment_record: Mapped[PaymentRecord | None] = relationship(
        back_populates="order",
        passive_deletes="all",
    )
    deletion_request: Mapped[DeletionRequest | None] = relationship(
        back_populates="order",
        passive_deletes="all",
    )
    events: Mapped[list[OrderEvent]] = relationship(
        back_populates="order",
        passive_deletes="all",
        order_by="OrderEvent.created_at, OrderEvent.id",
    )


class MaterialHandover(Entity, Base):
    __tablename__ = "material_handovers"
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        unique=True,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)
    order: Mapped[Order] = relationship(back_populates="material_handover")


class PaymentRecord(Entity, Base):
    __tablename__ = "payment_records"
    __table_args__ = (
        CheckConstraint(
            "status <> 'paid' OR (confirmed_at IS NOT NULL AND confirmed_by_id IS NOT NULL)",
            name="paid_confirmation",
        ),
        CheckConstraint(
            "confirmed_at IS NULL OR confirmed_at >= created_at", name="confirmation_time"
        ),
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        unique=True,
    )
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus, "payment_status"),
        server_default=PaymentStatus.UNPAID.value,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    note: Mapped[str | None] = mapped_column(Text)
    order: Mapped[Order] = relationship(back_populates="payment_record")
    confirmed_by: Mapped[AdminUser | None] = relationship()

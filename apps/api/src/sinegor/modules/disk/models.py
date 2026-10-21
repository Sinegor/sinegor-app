from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sinegor.db.base import Base
from sinegor.db.mixins import Entity

if TYPE_CHECKING:
    from sinegor.modules.orders.models import Order


class DiskFolder(Entity, Base):
    __tablename__ = "disk_folders"
    __table_args__ = (
        CheckConstraint(
            "disk_path LIKE 'disk:/%' AND length(disk_path) > 6", name="disk_path_format"
        ),
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), unique=True
    )
    disk_path: Mapped[str] = mapped_column(Text, unique=True)
    resource_id: Mapped[str | None] = mapped_column(Text, unique=True)
    folder_url: Mapped[str | None] = mapped_column(Text)
    deletion_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_succeeded: Mapped[bool] = mapped_column(Boolean, server_default="false")
    deletion_operation_id: Mapped[str | None] = mapped_column(String(256))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order: Mapped[Order] = relationship(back_populates="disk_folder")

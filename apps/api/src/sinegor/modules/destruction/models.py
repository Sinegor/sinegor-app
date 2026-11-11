from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sinegor.db.base import Base
from sinegor.db.mixins import Entity


class DestructionOperation(Entity, Base):
    __tablename__ = "destruction_operations"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('disk_folder','consultation_auto','consultation_manual',"
            "'security_events','customer_fields','agreement','order_history','customer')",
            name="kind",
        ),
        CheckConstraint(
            "state IN ('preparing','executing','verifying','error','uncertain',"
            "'documents_pending','ready')",
            name="state",
        ),
        CheckConstraint("(destroyed_at IS NULL) = (expires_at IS NULL)", name="confirmation"),
        CheckConstraint(
            "state NOT IN ('documents_pending','ready') OR destroyed_at IS NOT NULL",
            name="confirmed_state",
        ),
        CheckConstraint("state <> 'ready' OR bundle_key IS NOT NULL", name="ready_bundle"),
        Index("ix_destruction_operations_created_at", "created_at", "id"),
        Index("ix_destruction_operations_expires_at", "expires_at"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, default="preparing")
    metadata_json: Mapped[dict] = mapped_column(JSONB)
    destroyed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bundle_key: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)

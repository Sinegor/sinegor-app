"""Anonymous analytics choices; never link these rows to accounts or contacts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from sinegor.db.base import Base


class AnalyticsConsentEvent(Base):
    __tablename__ = "analytics_consent_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('grant', 'withdraw')", name="event_type"),
        CheckConstraint("text_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'", name="text_version"),
    )

    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    browser_id: Mapped[UUID] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(8))
    text_version: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

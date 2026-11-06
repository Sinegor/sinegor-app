from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sinegor.modules.analytics.models import AnalyticsConsentEvent
from sinegor.modules.analytics.schemas import ConsentInput


def record_event(db: Session, payload: ConsentInput) -> AnalyticsConsentEvent:
    """A retry retains its original server time; no browser identity is authenticated."""
    values = payload.model_dump()
    db.execute(
        insert(AnalyticsConsentEvent)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[AnalyticsConsentEvent.event_id])
    )
    event = db.scalar(
        select(AnalyticsConsentEvent).where(AnalyticsConsentEvent.event_id == payload.event_id)
    )
    if any(getattr(event, name) != value for name, value in values.items()):
        raise HTTPException(409, "Event identifier already used")
    db.commit()
    return event


def purge_events(db: Session, *, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=180)
    result = db.execute(
        delete(AnalyticsConsentEvent).where(AnalyticsConsentEvent.recorded_at < cutoff)
    )
    db.commit()
    return result.rowcount

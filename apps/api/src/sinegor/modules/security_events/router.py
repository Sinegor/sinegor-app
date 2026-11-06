from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from sinegor.modules.auth.dependencies import Admin, Database
from sinegor.modules.security_events.models import EventType, Reason, Result, SecurityEvent

router = APIRouter(prefix="/admin/security-events", tags=["security-events"])


class SecurityEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    recorded_at: datetime
    event_type: EventType
    result: Result
    user_id: UUID | None
    user_role: str | None
    subject_user_id: UUID | None
    request_id: str
    reason_code: Reason


@router.get("", response_model=list[SecurityEventRead])
def list_events(
    principal: Admin,
    db: Database,
    date_from: date | None = None,
    date_to: date | None = None,
    event_type: EventType | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Invalid date range")
    statement = select(SecurityEvent)
    if date_from:
        statement = statement.where(
            SecurityEvent.recorded_at >= datetime.combine(date_from, time.min, UTC)
        )
    if date_to and date_to < date.max:
        statement = statement.where(
            SecurityEvent.recorded_at < datetime.combine(date_to + timedelta(days=1), time.min, UTC)
        )
    if event_type:
        statement = statement.where(SecurityEvent.event_type == event_type)
    return db.scalars(
        statement.order_by(SecurityEvent.recorded_at.desc(), SecurityEvent.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()

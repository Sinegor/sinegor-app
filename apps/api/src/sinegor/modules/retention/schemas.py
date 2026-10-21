from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from sinegor.db.types import DeletionReason, DeletionStatus


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = Field(strict=True)

    @field_validator("confirm")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Explicit confirmation is required")
        return value


class ConfirmDeletion(Confirmation):
    deletion_request_id: UUID


class DeferDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deletion_request_id: UUID
    deferred_until: AwareDatetime
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def require_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Deferral reason is required")
        return value


class CustomerDeletionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    reason: DeletionReason
    status: DeletionStatus
    due_at: datetime
    early_authorized_at: datetime | None
    deferred_until: datetime | None
    performed_at: datetime | None


class DeletionRead(CustomerDeletionRead):
    created_at: datetime
    confirmed_at: datetime | None
    confirmed_by_id: UUID | None
    admin_note: str | None

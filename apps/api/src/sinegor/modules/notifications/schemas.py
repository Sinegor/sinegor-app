import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from sinegor.modules.auth.schemas import EmailInput


class ConsultationInput(EmailInput):
    phone: str = Field(min_length=1, max_length=50)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        normalized = re.sub(r"[ ()-]", "", value)
        if re.fullmatch(r"\+[1-9][0-9]{6,14}", normalized) is None:
            raise ValueError("Use an international phone number with 7–15 digits")
        return normalized


class DeliverySummary(BaseModel):
    channel: Literal["smtp", "telegram"]
    reason: Literal["permanent", "expired", "delayed", "temporary"]
    count: int


class ConsultationChannel(BaseModel):
    channel: Literal["smtp", "telegram"]
    status: Literal["pending", "processing", "sent", "cancelled", "failed", "expired"]
    reason: Literal["permanent", "expired", "temporary", "awaiting"] | None
    attention: bool
    retry_after: datetime | None


class ConsultationRead(BaseModel):
    id: UUID
    created_at: datetime
    contacts_expires_at: datetime
    observed_at: datetime
    email: str | None
    phone: str | None
    contacts_expiring: bool
    status: Literal["unresolved", "handled"]
    channels: list[ConsultationChannel]
    can_handle: bool
    can_retry: bool


class ConsultationConfirmation(BaseModel):
    confirmed: Literal[True]


class ConsultationRetry(ConsultationConfirmation):
    channel: Literal["smtp", "telegram"]


class DeliveryProblem(BaseModel):
    id: UUID
    kind: str
    channel: Literal["smtp", "telegram"]
    reason: Literal["permanent", "expired", "delayed", "temporary"]
    status: Literal["pending", "processing", "failed", "expired"]
    created_at: datetime
    available_at: datetime
    attempts: int
    error_code: str | None
    order_id: UUID | None
    customer_id: UUID | None

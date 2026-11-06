from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sinegor.db.types import OrderStatus, PaymentStatus, ServiceType


class OrderTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_type: ServiceType
    description: str | None = Field(default=None, max_length=10000)
    agreed_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class OrderCreate(OrderTerms):
    customer_id: UUID


class OrderRead(OrderTerms):
    model_config = ConfigDict(from_attributes=True)
    # Existing TEXT values predate the input length limit.
    description: str | None = None
    id: UUID
    number: int
    customer_id: UUID
    status: OrderStatus
    created_at: datetime
    ready_at: datetime | None
    result_notified_at: datetime | None
    closed_at: datetime | None


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: OrderStatus
    result_uploaded: bool = False

    @model_validator(mode="after")
    def result_evidence(self):
        if self.status == OrderStatus.RESULT_READY and not self.result_uploaded:
            raise ValueError("Confirm result upload")
        return self


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=2000)


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: PaymentStatus
    confirmed_at: datetime | None
    confirmed_by_id: UUID | None
    note: str | None


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_type: str
    created_at: datetime


class HandoverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    submitted_at: datetime
    note: str | None

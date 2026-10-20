from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from sinegor.db.types import OrderStatus, ServiceType


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=320)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class CustomerCreate(EmailInput):
    display_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)


class AdminLogin(EmailInput):
    password: SecretStr = Field(min_length=1, max_length=128)
    code: str = Field(pattern=r"^[0-9]{6}$")


class MagicLinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class PrincipalRead(BaseModel):
    id: UUID
    role: Literal["customer", "admin"]
    email: str
    expires_at: datetime


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    display_name: str | None
    phone: str | None


class OrderAccessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    number: int
    service_type: ServiceType
    status: OrderStatus

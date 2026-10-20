"""Stable database values shared by ORM models and future business services."""

from enum import StrEnum

from sqlalchemy import Enum


class ServiceType(StrEnum):
    ANALYSIS = "analysis"
    TECHNICAL_PREPARATION = "technical_preparation"


class OrderStatus(StrEnum):
    AWAITING_AGREEMENT = "awaiting_agreement"
    AWAITING_MATERIALS = "awaiting_materials"
    IN_PROGRESS = "in_progress"
    RESULT_READY = "result_ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AgreementStatus(StrEnum):
    AWAITING_CUSTOMER = "awaiting_customer"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class TokenPurpose(StrEnum):
    INVITATION = "invitation"
    MAGIC_LINK = "magic_link"


class PaymentStatus(StrEnum):
    UNPAID = "unpaid"
    PAID = "paid"


class DeletionReason(StrEnum):
    RETENTION_EXPIRED = "retention_expired"
    EARLY_PERMISSION = "early_permission"


class DeletionStatus(StrEnum):
    WAITING = "waiting"
    DEFERRED = "deferred"
    CONFIRMED = "confirmed"
    PERFORMED = "performed"
    ERROR = "error"


def enum_column(enum: type[StrEnum], name: str) -> Enum:
    """VARCHAR + named CHECK, storing values rather than Python member names."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda items: [item.value for item in items],
    )

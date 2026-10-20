from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sinegor.db.types import AgreementStatus
from sinegor.modules.agreements.models import Agreement


class AgreementRead(BaseModel):
    id: UUID
    order_id: UUID
    status: AgreementStatus
    revision: int
    initial_available: bool
    returned_available: bool
    final_available: bool
    final_sha256: str | None
    rejection_reason: str | None
    verified_at: datetime | None
    verified_by_id: UUID | None

    @classmethod
    def from_agreement(cls, agreement: Agreement):
        return cls(
            id=agreement.id,
            order_id=agreement.order_id,
            status=agreement.status,
            revision=agreement.revision,
            initial_available=agreement.initial_pdf_key is not None,
            returned_available=agreement.returned_pdf_key is not None,
            final_available=agreement.final_pdf_key is not None,
            final_sha256=agreement.final_sha256,
            rejection_reason=agreement.rejection_reason,
            verified_at=agreement.verified_at,
            verified_by_id=agreement.verified_by_id,
        )


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class RejectionInput(ReviewInput):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")

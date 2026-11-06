from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator

TEXT_VERSION = "1"


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    event_id: UUID4
    browser_id: UUID4
    event_type: Literal["grant", "withdraw"]
    text_version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

    @model_validator(mode="after")
    def current_grant(self):
        if self.event_type == "grant" and self.text_version != TEXT_VERSION:
            raise ValueError("Consent text version is obsolete")
        return self


class ConsentReceipt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    event_type: Literal["grant", "withdraw"]
    text_version: str
    recorded_at: datetime

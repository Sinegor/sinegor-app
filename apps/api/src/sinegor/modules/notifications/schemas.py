import re

from pydantic import Field, field_validator

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

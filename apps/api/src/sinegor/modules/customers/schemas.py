from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from sinegor.modules.auth.schemas import EmailInput


class CustomerUpdate(EmailInput):
    email: str | None = None
    # None is an omission default only; explicit null is rejected by validation.
    display_name: Annotated[str, Field(min_length=1, max_length=255)] | SkipJsonSchema[None] = None
    phone: str | None = Field(default=None, max_length=50)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("Укажите ФИО заказчика.")
        return value

    @model_validator(mode="after")
    def validate_email(self):
        if "email" in self.model_fields_set:
            if self.email is None:
                raise ValueError("Email cannot be null")
            self.email = str(EmailInput(email=self.email).email)
        return self


class CustomerBlock(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}
    reason: str = Field(min_length=1, max_length=2000)
    internal_comment: str | None = Field(default=None, max_length=2000)

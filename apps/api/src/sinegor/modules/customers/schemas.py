from pydantic import BaseModel, Field, model_validator

from sinegor.modules.auth.schemas import EmailInput


class CustomerUpdate(EmailInput):
    email: str | None = None
    display_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)

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

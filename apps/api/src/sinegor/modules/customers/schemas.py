from pydantic import Field, model_validator

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

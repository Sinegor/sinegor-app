from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sinegor.integrations.yandex_disk.paths import canonical_path


class AttachFolder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disk_path: str = Field(max_length=1024)

    @field_validator("disk_path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return canonical_path(value)


class FolderLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_url: str = Field(max_length=2048)
    access_granted: bool = Field(strict=True)

    @field_validator("access_granted")
    @classmethod
    def require_access(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Manual access confirmation is required")
        return value

    @field_validator("folder_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "disk.yandex.ru"
            or not parsed.path.startswith(("/client/", "/invite/"))
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            raise ValueError("Use a Yandex Disk shared-folder link from its interface")
        return value


class DeleteFolder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deletion_request_id: UUID
    confirm: bool = Field(strict=True)
    permanent_deletion_verified: bool = Field(
        default=False,
        strict=True,
        description="Administrator verified permanent deletion in Disk after a lost API response",
    )

    @field_validator("confirm")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Explicit deletion confirmation is required")
        return value


class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    disk_path: str
    resource_id: str | None
    folder_url: str | None
    deleted_at: datetime | None
    deletion_operation_id: str | None
    deletion_started_at: datetime | None


class CustomerFolderRead(BaseModel):
    folder_url: str

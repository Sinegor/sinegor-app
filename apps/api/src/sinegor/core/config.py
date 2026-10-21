"""Validated environment configuration; secrets never appear in repr/errors."""

import os
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

API_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=API_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    public_origin: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    db_connect_timeout: int = Field(default=5, ge=1, le=30)

    session_secret: SecretStr | None = None
    auth_encryption_key: SecretStr | None = None
    magic_link_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    session_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    admin_session_ttl_seconds: int = Field(default=28800, ge=60, le=86400)
    csrf_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    auth_rate_window_seconds: int = Field(default=900, ge=60, le=3600)
    auth_ip_limit: int = Field(default=30, ge=1, le=1000)
    auth_account_limit: int = Field(default=5, ge=1, le=100)
    yandex_disk_token: SecretStr | None = None
    yandex_disk_root: str | None = None
    yandex_disk_timeout: int = Field(default=10, ge=1, le=30)

    smtp_host: str = "smtp.yandex.ru"
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: EmailStr | None = None
    agreement_storage_dir: Path = API_ROOT / "storage" / "agreements"
    agreement_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1, le=50 * 1024 * 1024)

    @field_validator("agreement_storage_dir")
    @classmethod
    def validate_agreement_storage(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("AGREEMENT_STORAGE_DIR must be absolute")
        resolved = value.resolve()
        public_roots = (API_ROOT.parent / app / "public" for app in ("web", "cms"))
        if resolved == Path("/") or any(
            resolved.is_relative_to(root.resolve()) for root in public_roots
        ):
            raise ValueError("Agreement storage must be a private directory")
        return resolved

    @field_validator(
        "yandex_disk_token",
        "yandex_disk_root",
        "session_secret",
        "auth_encryption_key",
        "smtp_username",
        "smtp_password",
        "smtp_from",
        mode="before",
    )
    @classmethod
    def empty_optional_setting(cls, value):
        return None if value == "" else value

    @field_validator("yandex_disk_root")
    @classmethod
    def validate_disk_root(cls, value: str | None) -> str | None:
        if value is not None:
            from sinegor.integrations.yandex_disk.paths import canonical_path

            return canonical_path(value)
        return value

    @property
    def session_cookie_name(self) -> str:
        return "__Host-sinegor_session" if self.app_env == "production" else "sinegor_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "__Host-sinegor_csrf" if self.app_env == "production" else "sinegor_csrf"

    @field_validator("auth_encryption_key")
    @classmethod
    def validate_encryption_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            try:
                Fernet(value.get_secret_value().encode())
            except (ValueError, TypeError) as exc:
                raise ValueError("AUTH_ENCRYPTION_KEY must be a Fernet key") from exc
        return value

    @field_validator("public_origin")
    @classmethod
    def validate_origin(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if (
            value.path not in (None, "/")
            or value.query
            or value.fragment
            or value.username
            or value.password
        ):
            raise ValueError("PUBLIC_ORIGIN must contain only scheme, host and optional port")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = (
                url.drivername == "postgresql+psycopg"
                and bool(url.host)
                and bool(url.database)
                and not url.query  # connection options are managed by the application
            )
        except Exception:
            valid = False
        if not valid:
            raise ValueError("Expected a PostgreSQL psycopg URL with host and database")
        return value

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.session_secret is not None and len(self.session_secret.get_secret_value()) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 characters")
        if self.app_env == "production":
            if self.session_secret is None or self.auth_encryption_key is None:
                raise ValueError("Production requires SESSION_SECRET and AUTH_ENCRYPTION_KEY")
            if self.public_origin.scheme != "https":
                raise ValueError("Production PUBLIC_ORIGIN must use HTTPS")
            if self.log_level == "DEBUG":
                raise ValueError("Production logging must not use DEBUG")
            url = make_url(self.database_url.get_secret_value())
            if not url.password or url.password in {"CHANGE_ME", "sinegor_dev"}:
                raise ValueError("Production requires dedicated database credentials")
        return self


def load_settings() -> Settings:
    """Environment overrides the selected dotenv; never read unrelated root secrets."""
    env_file = os.environ.get("SINEGOR_ENV_FILE", str(API_ROOT / ".env"))
    return Settings(_env_file=env_file)

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from sinegor.db.base import Base
from sinegor.db.mixins import Entity
from sinegor.db.types import TokenPurpose, enum_column
from sinegor.modules.customers.models import Customer


class AdminUser(Entity, Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint(
            "email = lower(btrim(email)) AND email <> '' AND email !~ '[[:space:]]'",
            name="normalized_email",
        ),
        CheckConstraint("btrim(password_hash) <> ''", name="password_hash_present"),
        CheckConstraint(
            "last_totp_step IS NULL OR last_totp_step >= 0", name="totp_step_nonnegative"
        ),
    )

    last_totp_step: Mapped[int | None] = mapped_column(BigInteger)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    @validates("email")
    def normalize_email(self, key: str, value: str) -> str:
        return value.strip().lower()


class AuthToken(Entity, Base):
    __tablename__ = "auth_tokens"
    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_sha256"),
        CheckConstraint("expires_at > created_at", name="positive_lifetime"),
        CheckConstraint(
            "used_at IS NULL OR (used_at >= created_at AND used_at <= expires_at)",
            name="used_during_lifetime",
        ),
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    purpose: Mapped[TokenPurpose] = mapped_column(enum_column(TokenPurpose, "token_purpose"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer: Mapped[Customer] = relationship()


class Session(Entity, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("session_hash ~ '^[0-9a-f]{64}$'", name="session_hash_sha256"),
        CheckConstraint(
            "(customer_id IS NULL) <> (admin_id IS NULL)", name="exactly_one_principal"
        ),
        CheckConstraint("expires_at > created_at", name="positive_lifetime"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation_time"),
    )

    session_hash: Mapped[str] = mapped_column(String(64), unique=True)
    customer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"),
        index=True,
    )
    admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer: Mapped[Customer | None] = relationship()
    admin: Mapped[AdminUser | None] = relationship()


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (
        CheckConstraint("key_hash ~ '^[0-9a-f]{64}$'", name="key_hash_sha256"),
        CheckConstraint("attempts > 0", name="positive_attempts"),
    )
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="1")

"""PostgreSQL counters survive failed logins and work across app processes."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sinegor.core.config import Settings
from sinegor.modules.auth.models import AuthRateLimit


def enforce_rate_limit(
    db: Session, settings: Settings, key: str, scope: str, ip: str, identity: str | None = None
) -> None:
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=settings.auth_rate_window_seconds)
    scopes = [(f"{scope}:ip:{ip}", settings.auth_ip_limit)]
    if identity is not None:
        scopes.append((f"{scope}:account:{identity}", settings.auth_account_limit))
    for bucket, limit in scopes:
        digest = hmac.new(key.encode(), bucket.encode(), hashlib.sha256).hexdigest()
        expired = AuthRateLimit.window_started_at <= cutoff
        statement = insert(AuthRateLimit).values(key_hash=digest, window_started_at=now, attempts=1)
        statement = statement.on_conflict_do_update(
            index_elements=[AuthRateLimit.key_hash],
            set_={
                "window_started_at": case((expired, now), else_=AuthRateLimit.window_started_at),
                "attempts": case((expired, 1), else_=AuthRateLimit.attempts + 1),
            },
        ).returning(AuthRateLimit.attempts)
        attempts = db.scalar(statement)
        # Commit even rejected attempts. Auth service changes must happen after this function.
        db.commit()
        if attempts > limit:
            raise HTTPException(
                429,
                "Too many attempts",
                headers={
                    "Retry-After": str(settings.auth_rate_window_seconds),
                },
            )

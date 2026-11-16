"""Remove expired authentication state, never customers, orders or audit records."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401 -- register relationships in this standalone CLI
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.jobs.runtime import run_job
from sinegor.modules.auth.models import AuthRateLimit, AuthToken, Session


def _run(settings) -> None:
    now = datetime.now(UTC)
    engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as db:
            db.execute(delete(AuthToken).where(AuthToken.expires_at < now))
            db.execute(delete(Session).where(Session.expires_at < now))
            db.execute(
                delete(AuthRateLimit).where(
                    AuthRateLimit.window_started_at
                    < now - timedelta(seconds=settings.auth_rate_window_seconds),
                )
            )
            db.commit()
    finally:
        engine.dispose()
    print("Expired authentication state removed")


def main() -> int:
    return run_job("purge_auth", load_settings, _run)


if __name__ == "__main__":
    raise SystemExit(main())

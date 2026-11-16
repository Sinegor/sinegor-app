"""Use a dedicated maintenance DATABASE_URL; runtime cannot execute this operation."""

from sqlalchemy import text

from sinegor.core.config import load_settings
from sinegor.db.session import create_db_engine
from sinegor.jobs.runtime import run_job


def _run(settings) -> None:
    engine = create_db_engine(settings)
    try:
        with engine.begin() as connection:
            count = connection.scalar(text("SELECT public.purge_security_events()"))
    finally:
        engine.dispose()
    print(f"Expired security events removed: {count}")


def main() -> int:
    return run_job("purge_security_events", load_settings, _run)


if __name__ == "__main__":
    raise SystemExit(main())

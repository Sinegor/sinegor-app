"""Daily retention job for anonymous analytics events older than 180 days."""

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401 -- standalone job model registry
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.jobs.runtime import run_job
from sinegor.modules.analytics.service import purge_events


def _run(settings) -> None:
    engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as db:
            count = purge_events(db)
    finally:
        engine.dispose()
    print(f"Expired analytics consent events removed: {count}")


def main() -> int:
    return run_job("purge_analytics", load_settings, _run)


if __name__ == "__main__":
    raise SystemExit(main())

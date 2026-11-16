"""Run periodically: advance approved orders and close results after fourteen days."""

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401 -- register all ORM relationships
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.jobs.runtime import run_job
from sinegor.modules.destruction.service import generate_pending
from sinegor.modules.orders.service import process_lifecycle
from sinegor.modules.retention.archive import RetentionArchive
from sinegor.modules.retention.service import process_due


def _run(settings) -> int:
    engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as db:
            count = process_lifecycle(db)
            requests = process_due(db)
            documents = generate_pending(db, RetentionArchive(settings.destruction_archive_dir))
    finally:
        engine.dispose()
    print(f"Orders advanced: {count}")
    print(f"Deletion requests updated: {requests}")
    print(f"Destruction documents ready: {documents['ready']}; failed: {documents['failed']}")
    return int(bool(documents["failed"]))


def main() -> int:
    return run_job("process_orders", load_settings, _run)


if __name__ == "__main__":
    raise SystemExit(main())

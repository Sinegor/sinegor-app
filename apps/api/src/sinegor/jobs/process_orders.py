"""Run periodically: advance approved orders and close results after fourteen days."""

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401 -- register all ORM relationships
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.modules.orders.service import process_lifecycle
from sinegor.modules.retention.service import process_due


def main() -> None:
    engine = create_db_engine(load_settings())
    try:
        with create_session_factory(engine)() as db:
            count = process_lifecycle(db)
            requests = process_due(db)
    finally:
        engine.dispose()
    print(f"Orders advanced: {count}")
    print(f"Deletion requests updated: {requests}")


if __name__ == "__main__":
    main()

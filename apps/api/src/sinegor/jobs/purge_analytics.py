"""Daily retention job for anonymous analytics events older than 180 days."""

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401 -- standalone job model registry
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.modules.analytics.service import purge_events


def main() -> None:
    engine = create_db_engine(load_settings())
    try:
        with create_session_factory(engine)() as db:
            count = purge_events(db)
    finally:
        engine.dispose()
    print(f"Expired analytics consent events removed: {count}")


if __name__ == "__main__":
    main()

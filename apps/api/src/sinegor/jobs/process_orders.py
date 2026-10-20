"""Run periodically: advance approved orders and close results after fourteen days."""

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401 -- register all ORM relationships
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.modules.orders.service import process_lifecycle


def main() -> None:
    engine = create_db_engine(load_settings())
    try:
        with create_session_factory(engine)() as db:
            count = process_lifecycle(db)
    finally:
        engine.dispose()
    print(f"Orders advanced: {count}")


if __name__ == "__main__":
    main()

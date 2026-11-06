"""Use a dedicated maintenance DATABASE_URL; runtime cannot execute this operation."""

from sqlalchemy import text

from sinegor.core.config import load_settings
from sinegor.db.session import create_db_engine


def main() -> None:
    engine = create_db_engine(load_settings())
    try:
        with engine.begin() as connection:
            count = connection.scalar(text("SELECT public.purge_security_events()"))
    finally:
        engine.dispose()
    print(f"Expired security events removed: {count}")


if __name__ == "__main__":
    main()

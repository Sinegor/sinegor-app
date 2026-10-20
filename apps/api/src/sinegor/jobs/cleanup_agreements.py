"""Retry obsolete PDF removal, then reclaim day-old objects without database references."""

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401 -- register ORM mappings for standalone CLI
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.modules.agreements.service import cleanup_files, cleanup_orphans
from sinegor.modules.agreements.storage import AgreementStorage


def main() -> None:
    settings = load_settings()
    engine = create_db_engine(settings)
    storage = AgreementStorage(settings.agreement_storage_dir)
    try:
        with create_session_factory(engine)() as db:
            removed = cleanup_files(db, storage)
            orphans = cleanup_orphans(db, storage)
    finally:
        engine.dispose()
    print(f"Obsolete PDFs removed: {removed}; orphan PDFs removed: {orphans}")


if __name__ == "__main__":
    main()

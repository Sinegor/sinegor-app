"""Generate pending destruction documents, without repeating any deletion."""

import argparse
import json

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.modules.destruction.service import generate_pending
from sinegor.modules.retention.archive import RetentionArchive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error("--limit must be between 1 and 10000")
    try:
        settings = load_settings()
        engine = create_db_engine(settings)
        try:
            with create_session_factory(engine)() as db:
                result = generate_pending(
                    db, RetentionArchive(settings.destruction_archive_dir), limit=args.limit
                )
        finally:
            engine.dispose()
    except Exception:
        print(json.dumps({"error": "documents_generation_failed"}))
        return 1
    print(json.dumps(result))
    return int(bool(result["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())

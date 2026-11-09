"""Preview or execute expired business-data and destruction-document cleanup."""

import argparse
import json
from dataclasses import asdict

from sinegor.core.config import load_settings
from sinegor.core.logging import configure_logging
from sinegor.db import models  # noqa: F401 -- register ORM mappings
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.modules.agreements.storage import AgreementStorage
from sinegor.modules.retention.archive import RetentionArchive
from sinegor.modules.retention.business import cleanup_business


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error("--limit must be between 1 and 10000")
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings)
    failed = False
    output = {"dry_run": not args.execute}
    try:
        try:
            with create_session_factory(engine)() as db:
                result = cleanup_business(
                    db,
                    AgreementStorage(settings.agreement_storage_dir),
                    dry_run=not args.execute,
                    limit=args.limit,
                )
                output["business"] = asdict(result)
                failed = bool(result.failed or (args.execute and result.pending_files))
        except Exception:
            output["business_error"] = "business_cleanup_failed"
            failed = True
        try:
            result = RetentionArchive(settings.destruction_archive_dir).cleanup(
                dry_run=not args.execute
            )
            output["archive"] = asdict(result)
            failed |= bool(result.failed)
        except Exception:
            output["archive_error"] = "archive_cleanup_failed"
            failed = True
    finally:
        engine.dispose()
    print(json.dumps(output))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

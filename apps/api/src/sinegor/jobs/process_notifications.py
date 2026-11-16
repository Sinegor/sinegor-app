"""Run periodically to deliver durable notifications and remind the administrator."""

import logging
from time import perf_counter

from sinegor.core.config import load_settings
from sinegor.core.logging import configure_logging
from sinegor.db import models  # noqa: F401
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.integrations.email.smtp import SMTPAuthMailer
from sinegor.integrations.telegram.client import TelegramNotifier
from sinegor.jobs.runtime import run_job
from sinegor.modules.notifications.service import process_pending, queue_deletion_reminders

logger = logging.getLogger(__name__)


def _run(settings) -> int:
    started = perf_counter()
    logger.info("notifications_run_started")
    try:
        configure_logging(settings.log_level)
        logger.setLevel(logging.INFO)
        engine = create_db_engine(settings)
        mailer = SMTPAuthMailer(settings)
        try:
            with create_session_factory(engine)() as db:
                queue_deletion_reminders(db)
                count = process_pending(
                    db,
                    settings,
                    auth_mailer=mailer,
                    order_mailer=mailer,
                    mailer=mailer,
                    telegram=TelegramNotifier(settings),
                )
        finally:
            engine.dispose()
    except Exception as exc:
        logger.error("notifications_run_failed", extra={"exception_type": type(exc).__name__})
        return 1
    # Fixed metadata only; provider failures are reported by the existing delivery logger.
    logger.info(
        "notifications_run_completed delivered=%d",
        count,
        extra={"duration_ms": round((perf_counter() - started) * 1000, 2)},
    )
    return 0


def main() -> int:
    return run_job("process_notifications", load_settings, _run)


if __name__ == "__main__":
    raise SystemExit(main())

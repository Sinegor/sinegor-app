"""Run periodically to deliver durable notifications and remind the administrator."""

from sinegor.core.config import load_settings
from sinegor.core.logging import configure_logging
from sinegor.db import models  # noqa: F401
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.integrations.email.smtp import SMTPAuthMailer
from sinegor.integrations.telegram.client import TelegramNotifier
from sinegor.modules.notifications.service import process_pending, queue_deletion_reminders


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
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
    print(f"Notifications delivered: {count}")


if __name__ == "__main__":
    main()

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from alembic import command
from sqlalchemy import delete
from sqlalchemy.orm import Session

from sinegor.db.session import create_db_engine
from sinegor.modules.notifications.models import Notification
from sinegor.modules.notifications.service import deliver_one, enqueue

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("kind", ["consultation", "consultation_telegram"])
def test_two_workers_do_not_send_the_same_claimed_notification(
    database_settings, alembic_config, kind
):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    sending, release = Event(), Event()
    messages = []

    class Mailer:
        def send_consultation_notice(self, recipient, email, phone=None):
            Telegram().send("synthetic SMTP notice")

    class Telegram:
        def send(self, text):
            messages.append(text)
            sending.set()
            assert release.wait(timeout=10)

    with Session(engine) as db:
        database_settings.notification_admin_email = "executor@example.ru"
        identifier = enqueue(
            db, kind, recipient="concurrency@example.ru" if kind == "consultation" else None
        )
        db.commit()

    def attempt():
        with Session(engine) as db:
            return deliver_one(
                db,
                database_settings,
                identifier,
                auth_mailer=None,
                order_mailer=None,
                mailer=Mailer(),
                telegram=Telegram(),
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(attempt)
            try:
                assert sending.wait(timeout=10)
                second = executor.submit(attempt)
                assert second.result(timeout=5) is False
            finally:
                release.set()
            assert first.result(timeout=10) is True
        assert len(messages) == 1
        with Session(engine) as db:
            item = db.get(Notification, identifier)
            assert item.status == "sent" and item.attempts == 1
            assert item.recipient is None
    finally:
        release.set()
        with engine.begin() as connection:
            connection.execute(delete(Notification).where(Notification.id == identifier))
        engine.dispose()

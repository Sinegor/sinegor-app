"""Cleanup must share admin lock order and fence late delivery completions."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from alembic import command
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from sinegor.db.session import create_db_engine
from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.modules.notifications import consultations, service
from sinegor.modules.notifications.models import Notification

pytestmark = pytest.mark.integration


@pytest.fixture
def committed_pair(database_settings, alembic_config):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    at = datetime.now(UTC) - timedelta(days=7)
    with Session(engine) as db:
        root_id = service.enqueue(
            db, "consultation", recipient="race@example.ru", payload={"phone": "+79991234567"}
        )
        partner_id = service.enqueue(
            db, "consultation_telegram", dedup_key=f"consultation_telegram:{root_id}"
        )
        root, partner = (db.get(Notification, key) for key in (root_id, partner_id))
        root.created_at = at
        root.status = "expired"
        # A legacy Telegram timestamp must not invert the root -> partner lock order.
        partner.created_at = at - timedelta(seconds=1)
        partner.status = "sent"
        db.commit()
    try:
        yield engine, root_id, partner_id, at + timedelta(days=7)
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(Notification).where(Notification.id.in_((root_id, partner_id)))
            )
        engine.dispose()


def test_cleanup_locks_root_before_telegram_like_admin_actions(committed_pair):
    engine, root_id, partner_id, cutoff = committed_pair
    with Session(engine) as db:
        partner = db.get(Notification, partner_id)
        partner.status = "failed"
        db.commit()
    started = Event()
    pids = []

    def cleanup():
        with Session(engine) as db:
            pids.append(db.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            return consultations.purge_expired_consultations(db, now=cutoff)

    with Session(engine) as admin, ThreadPoolExecutor(max_workers=1) as executor:
        admin.scalar(select(Notification).where(Notification.id == root_id).with_for_update())
        future = executor.submit(cleanup)
        try:
            assert started.wait(timeout=5)
            deadline = time.monotonic() + 5
            while True:
                with engine.connect() as observer:
                    blocked = observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pids[0]}
                    )
                if blocked:
                    break
                assert time.monotonic() < deadline, "Cleanup did not reach the held root lock"
                time.sleep(0.01)
            try:
                admin.scalar(
                    select(Notification)
                    .where(Notification.id == partner_id)
                    .with_for_update(nowait=True)
                )
            except DBAPIError:
                pytest.fail(
                    "Cleanup locked Telegram before the root, inverting the admin lock order"
                )
        finally:
            admin.rollback()
        assert future.result(timeout=10) >= 1


@pytest.mark.parametrize("failure", [False, True])
def test_cleanup_revokes_live_lease_and_late_delivery_cannot_restore_contacts(
    committed_pair, database_settings, failure
):
    engine, root_id, _, cutoff = committed_pair
    sending, release = Event(), Event()
    delivered = []
    database_settings.notification_admin_email = "executor@example.ru"

    class Mailer:
        def send_consultation_notice(self, recipient, email, phone):
            delivered.append((email, phone))
            sending.set()
            assert release.wait(timeout=10)
            if failure:
                raise MailDeliveryError("synthetic timeout with private data")

    def attempt():
        with Session(engine) as db:
            return service.deliver_one(
                db,
                database_settings,
                root_id,
                auth_mailer=None,
                order_mailer=None,
                mailer=Mailer(),
                telegram=None,
                force=True,
                now=cutoff - timedelta(microseconds=1),
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(attempt)
        try:
            assert sending.wait(timeout=5)
            with Session(engine) as db:
                assert consultations.purge_expired_consultations(db, now=cutoff) == 1
                item = db.get(Notification, root_id)
                assert item.status == "expired" and item.lease_id is None
                assert item.recipient is None and item.payload == {}
        finally:
            release.set()
        future.result(timeout=10)
    with Session(engine) as db:
        item = db.get(Notification, root_id)
        assert item.status == "expired" and item.last_error_code == "contacts_expired"
        assert item.recipient is None and item.payload == {} and item.lease_id is None
        assert item.attempts == 1
    assert delivered == [("race@example.ru", "+79991234567")]

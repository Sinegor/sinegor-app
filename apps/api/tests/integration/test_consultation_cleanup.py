"""Seven-day contact retention is independent of delivery state and queue capacity."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_notifications as helpers

from sinegor.modules.notifications import consultations, service
from sinegor.modules.notifications.models import Notification

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors
channels = helpers.channels


def job(channels, *, kind="consultation", state="expired", age=timedelta(days=7)):
    identifier = service.enqueue(
        channels.db,
        kind,
        recipient="retention@example.ru",
        payload={"phone": "+79991234567", "legacy": {"email": "retention@example.ru"}},
    )
    item = channels.db.get(Notification, identifier)
    item.created_at = datetime.now(UTC) - age
    item.status = state
    item.last_error_code = "legacy private@example.ru"
    item.attempts = 2
    if state == "processing":
        item.lease_id, item.lease_until = uuid4(), datetime.now(UTC) + timedelta(minutes=5)
    channels.db.commit()
    return item


def assert_anonymous(channels, item, *, state="expired", error="contacts_expired"):
    channels.db.refresh(item)
    assert item.recipient is None
    assert item.payload == {}
    assert item.status == state
    assert item.last_error_code == error
    assert item.lease_id is None and item.lease_until is None


@pytest.mark.parametrize("kind", ["consultation", "consultation_telegram"])
@pytest.mark.parametrize(
    "state", ["pending", "processing", "failed", "expired", "sent", "cancelled"]
)
def test_worker_scrubs_all_overdue_consultation_states_without_sending(channels, kind, state):
    item = job(channels, kind=kind, state=state)
    created_at, attempts = item.created_at, item.attempts
    assert helpers.process(channels, now=created_at + timedelta(days=7), limit=0) == 0
    terminal = state in {"sent", "cancelled"}
    assert_anonymous(
        channels,
        item,
        state=state if terminal else "expired",
        error=None if terminal else "contacts_expired",
    )
    assert item.created_at == created_at and item.attempts == attempts
    assert channels.app.state.notification_mailer.consultations == []
    assert channels.app.state.telegram_notifier.messages == []


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_exact_seven_day_boundary(channels, offset):
    item = job(channels)
    now = item.created_at + timedelta(days=7, microseconds=offset)
    assert helpers.process(channels, now=now, limit=0) == 0
    channels.db.refresh(item)
    if offset < 0:
        assert item.recipient == "retention@example.ru" and item.payload["phone"] == "+79991234567"
    else:
        assert_anonymous(channels, item)


def test_three_day_automatic_stop_preserves_contacts_and_full_warning_day(channels):
    item = job(channels, state="pending", age=timedelta())
    created_at = item.created_at
    assert helpers.process(channels, now=created_at + timedelta(days=3)) == 0
    channels.db.refresh(item)
    assert item.status == "expired" and item.recipient == "retention@example.ru"
    for offset, warning in [(-1, False), (0, True), (86400000000 - 1, True)]:
        now = created_at + timedelta(days=6, microseconds=offset)
        helpers.process(channels, now=now, limit=0)
        row = consultations.list_consultations(channels.db, now=now)[0]
        assert row["email"] == "retention@example.ru" and row["phone"] == "+79991234567"
        assert row["contacts_expiring"] is warning
        assert row["can_retry"]
    helpers.process(channels, now=created_at + timedelta(days=7), limit=0)
    assert_anonymous(channels, item)
    row = consultations.list_consultations(channels.db, now=created_at + timedelta(days=7))[0]
    assert row["email"] is None and row["phone"] is None
    assert not row["contacts_expiring"] and not row["can_retry"]


def test_cleanup_is_idempotent_and_preserves_manual_outcome_and_other_kinds(channels):
    item = job(channels)
    handled = job(channels, state="cancelled")
    handled.last_error_code = consultations.HANDLED
    unrelated = job(channels, kind="invitation", state="failed", age=timedelta(days=20))
    channels.db.commit()
    helpers.process(channels, limit=0)
    assert_anonymous(channels, item)
    assert_anonymous(channels, handled, state="cancelled", error=consultations.HANDLED)
    helpers.process(channels, now=datetime.now(UTC) + timedelta(days=1), limit=0)
    assert_anonymous(channels, item)
    assert consultations.purge_expired_consultations(channels.db) == 0
    channels.db.refresh(unrelated)
    assert unrelated.recipient == "retention@example.ru" and unrelated.payload["phone"]
    assert unrelated.status == "failed" and unrelated.last_error_code == "legacy private@example.ru"


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize(
    "state", ["pending", "processing", "failed", "expired", "sent", "cancelled"]
)
def test_direct_delivery_cannot_leave_overdue_contacts(channels, force, state):
    item = job(channels, state=state)
    result = service.deliver_one(
        channels.db,
        channels.settings,
        item.id,
        auth_mailer=channels.mailer,
        order_mailer=channels.app.state.order_mailer,
        mailer=channels.app.state.notification_mailer,
        telegram=channels.app.state.telegram_notifier,
        now=item.created_at + timedelta(days=7),
        force=force,
    )
    terminal = state in {"sent", "cancelled"}
    assert result is (state == "sent")
    assert_anonymous(
        channels,
        item,
        state=state if terminal else "expired",
        error=None if terminal else "contacts_expired",
    )
    assert not channels.app.state.notification_mailer.consultations


def test_manual_delivery_remains_available_until_deadline_and_clears_on_success(channels):
    item = job(channels, age=timedelta(days=7) - timedelta(minutes=1))
    helpers.process(channels, limit=0)
    identifier = consultations.retry_consultation(channels.db, item.id, "smtp")
    assert service.deliver_from_app(channels.app, identifier)
    assert_anonymous(channels, item, state="sent", error=None)
    assert len(channels.app.state.notification_mailer.consultations) == 1


def test_manual_cancellation_clears_data_before_expiry(channels):
    item = job(channels, age=timedelta(days=4))
    consultations.handle_consultation(channels.db, item.id)
    assert_anonymous(channels, item, state="cancelled", error=consultations.HANDLED)

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_notifications as helpers
from sqlalchemy import select
from test_auth import login_admin, login_customer
from test_notifications import process
from test_orders import approve, status

from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.integrations.telegram.client import TelegramDeliveryError
from sinegor.modules.notifications import service
from sinegor.modules.notifications.models import Notification
from sinegor.modules.orders.service import process_lifecycle

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors
channels = helpers.channels


def queue(channels, kind="consultation", age=timedelta()):
    identifier = service.enqueue(
        channels.db, kind, recipient="private@example.ru", payload={"phone": "+79991234567"}
    )
    job = channels.db.get(Notification, identifier)
    job.created_at = datetime.now(UTC) - age
    channels.db.commit()
    return job


@pytest.mark.parametrize(
    "kind,days", [("consultation", 3), ("consultation_telegram", 3), ("invitation", 7)]
)
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_exact_automatic_retry_deadline(channels, kind, days, offset):
    job = queue(channels, kind)
    cutoff = job.created_at + timedelta(days=days)
    calls = []

    def deliver(*args, **kwargs):
        calls.append(True)
        return True

    from unittest.mock import patch

    with patch.object(service, "_deliver", deliver):
        process(channels, now=cutoff + timedelta(microseconds=offset))
    assert bool(calls) is (offset < 0)
    assert job.status == ("sent" if offset < 0 else "expired")
    if offset >= 0:
        assert job.attempts == 0 and job.recipient == "private@example.ru"


def test_backoff_doubles_from_thirty_minutes_and_caps_at_day(channels, monkeypatch):
    channels.app.state.notification_mailer.fail = True
    channels.settings.notification_retry_jitter = 0
    job = queue(channels)
    now = job.created_at + timedelta(seconds=1)
    for delay in [1800, 3600, 7200, 14400, 28800, 57600]:
        assert process(channels, now=now) == 0
        assert job.available_at == now + timedelta(seconds=delay)
        now = job.available_at
    assert job.attempts == 6
    # Seven-day kinds exercise the capped portion without a fabricated attempt limit.
    job.kind = "agreement_initial"
    channels.db.commit()
    monkeypatch.setattr(
        service, "_deliver", lambda *a, **kw: (_ for _ in ()).throw(MailDeliveryError())
    )
    for _ in range(2):
        process(channels, now=now)
        assert job.available_at == now + timedelta(days=1)
        now = job.available_at


def test_permanent_failure_stops_and_manual_force_does_not_repeat_sent(channels):
    job = queue(channels)

    def fail(*args):
        raise MailDeliveryError(permanent=True)

    channels.app.state.notification_mailer.send_consultation_notice = fail
    assert process(channels) == 0
    assert job.status == "failed" and job.last_error_code == "smtp_permanent"
    assert job.recipient == "private@example.ru"
    assert process(channels, now=job.created_at + timedelta(days=1)) == 0
    assert job.attempts == 1
    channels.app.state.notification_mailer.send_consultation_notice = lambda *a: None
    args = dict(
        auth_mailer=channels.mailer,
        order_mailer=channels.app.state.order_mailer,
        mailer=channels.app.state.notification_mailer,
        telegram=channels.app.state.telegram_notifier,
        force=True,
    )
    assert service.deliver_one(channels.db, channels.settings, job.id, **args)
    assert job.status == "sent" and job.recipient is None and job.payload == {}
    assert service.deliver_one(channels.db, channels.settings, job.id, **args)
    assert job.attempts == 2


def test_retry_after_longer_than_lifetime_never_causes_early_delivery(channels):
    job = queue(channels, "consultation_telegram")

    def fail(*args):
        raise TelegramDeliveryError(4 * 86400)

    channels.app.state.telegram_notifier.send = fail
    process(channels)
    assert job.available_at >= job.created_at + timedelta(days=3)
    process(channels, now=job.created_at + timedelta(days=3))
    assert job.status == "expired" and job.attempts == 1


def test_expired_active_lease_is_not_stolen_and_expired_lease_does_not_send(channels):
    job = queue(channels, age=timedelta(days=4))
    now = datetime.now(UTC)
    job.status = "processing"
    job.lease_id = uuid4()
    job.lease_until = now + timedelta(minutes=1)
    channels.db.commit()
    assert process(channels, now=now) == 0
    assert job.status == "processing"
    assert process(channels, now=now + timedelta(minutes=1)) == 0
    assert job.status == "expired" and job.lease_id is None
    assert not channels.app.state.notification_mailer.consultations


def test_administrative_warning_boundaries_authorization_and_channel_isolation(channels, actors):
    a = queue(channels)
    b = queue(channels, "consultation_telegram")
    a.created_at = b.created_at = datetime.now(UTC) - timedelta(hours=24) + timedelta(seconds=2)
    channels.db.commit()
    url = "/api/admin/notifications/summary"
    assert channels.client.get(url).status_code == 401
    login_customer(channels, actors.customer.email)
    assert channels.client.get(url).status_code == 403
    login_admin(channels, actors)
    assert channels.client.get(url).json() == []
    a.created_at = b.created_at = datetime.now(UTC) - timedelta(hours=24)
    b.status = "sent"
    b.recipient = None
    b.payload = {}
    channels.db.commit()
    response = channels.client.get(url)
    assert response.status_code == 200
    assert response.json() == [{"channel": "smtp", "reason": "delayed", "count": 1}]
    assert "private@example.ru" not in response.text and "+79991234567" not in response.text
    a.status = "failed"
    a.created_at = datetime.now(UTC)
    channels.db.commit()
    assert channels.client.get(url).json() == [
        {"channel": "smtp", "reason": "permanent", "count": 1}
    ]


def test_failed_readiness_never_starts_ready_or_completion_clock(channels, actors):
    login_admin(channels, actors)
    approve(channels, actors)
    assert status(channels, actors.order, "awaiting_materials").status_code == 200
    assert status(channels, actors.order, "in_progress").status_code == 200

    def fail(*args):
        raise MailDeliveryError(permanent=True)

    channels.app.state.order_mailer.send_result_ready = fail
    assert status(channels, actors.order, "result_ready", result_uploaded=True).status_code == 503
    channels.db.refresh(actors.order)
    assert actors.order.ready_at is None and actors.order.result_notified_at is None
    job = channels.db.scalar(select(Notification))
    assert job.status == "failed"
    process(channels, now=job.created_at + timedelta(days=20))
    process_lifecycle(channels.db, now=job.created_at + timedelta(days=20))
    channels.db.refresh(actors.order)
    assert actors.order.status.value == "in_progress"


@pytest.mark.parametrize("stopped", ["failed", "expired"])
def test_manual_invitation_retry_resolves_the_existing_stopped_job(channels, actors, stopped):
    login_admin(channels, actors)
    identifier = service.enqueue(
        channels.db, "invitation", recipient=actors.customer.email, customer_id=actors.customer.id
    )
    job = channels.db.get(Notification, identifier)
    job.status = stopped
    job.last_error_code = "smtp_permanent" if stopped == "failed" else "smtp_failed"
    job.created_at = datetime.now(UTC) - timedelta(days=8)
    channels.db.commit()
    response = helpers.post(channels, f"/api/admin/customers/{actors.customer.id}/invite")
    assert response.status_code == 202
    channels.db.refresh(job)
    assert job.status == "sent" and job.recipient is None and job.payload == {}
    assert service.delivery_summary(channels.db) == []
    assert channels.db.scalars(select(Notification)).all() == [job]
    assert len(channels.mailer.messages) == 1

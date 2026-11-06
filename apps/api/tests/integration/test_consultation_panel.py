from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_notifications as helpers
from test_auth import login_admin, login_customer, post

from sinegor.modules.notifications import service
from sinegor.modules.notifications.models import Notification

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors
channels = helpers.channels
BASE = "/api/admin/consultations"


def pair(channels, *, age=timedelta(days=1), smtp="failed", telegram="pending"):
    identifier = service.enqueue(
        channels.db,
        "consultation",
        recipient="private@example.ru",
        payload={"phone": "+79991234567"},
    )
    other = service.enqueue(
        channels.db, "consultation_telegram", dedup_key=f"consultation_telegram:{identifier}"
    )
    root, tg = (channels.db.get(Notification, key) for key in (identifier, other))
    for job, state in [(root, smtp), (tg, telegram)]:
        job.created_at = datetime.now(UTC) - age
        job.status = state
        job.last_error_code = "smtp_permanent" if state == "failed" else "unsafe private text"
        if state == "sent":
            job.recipient, job.payload = None, {}
    channels.db.commit()
    return root, tg


def test_list_is_admin_only_and_safe(channels, actors):
    root, tg = pair(channels)
    assert channels.client.get(BASE).status_code == 401
    login_customer(channels, actors.customer.email)
    assert channels.client.get(BASE).status_code == 403
    login_admin(channels, actors)
    response = channels.client.get(BASE)
    assert response.status_code == 200
    row = response.json()[0]
    assert row["id"] == str(root.id)
    assert row["email"] == "private@example.ru" and row["phone"] == "+79991234567"
    assert row["status"] == "unresolved"
    assert row["channels"][0]["reason"] == "permanent"
    assert row["channels"][1]["reason"] == "temporary"
    assert "unsafe private text" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "offset,visible,warning",
    [
        (-86400000001, True, False),
        (-86400000000, True, True),
        (-1, True, True),
        (0, False, False),
        (1, False, False),
    ],
)
def test_exact_contact_window_and_warning(channels, actors, monkeypatch, offset, visible, warning):
    root, _ = pair(channels)
    cutoff = root.created_at + timedelta(days=7)
    from sinegor.modules.notifications import consultations

    rows = consultations.list_consultations(
        channels.db, now=cutoff + timedelta(microseconds=offset)
    )
    assert bool(rows[0]["email"]) is visible
    assert bool(rows[0]["phone"]) is visible
    assert rows[0]["contacts_expiring"] is warning


def test_retry_only_failed_channel_and_preserve_original_dates(channels, actors):
    root, tg = pair(channels, age=timedelta(days=4), smtp="expired", telegram="sent")
    login_admin(channels, actors)
    created = root.created_at
    response = post(channels, f"{BASE}/{root.id}/retry", {"channel": "smtp", "confirmed": True})
    assert response.status_code == 202
    channels.db.refresh(root)
    assert root.status == "sent" and root.created_at == created
    assert root.recipient is None and root.payload == {}
    assert len(channels.app.state.notification_mailer.consultations) == 1
    assert channels.app.state.telegram_notifier.messages == []
    assert (
        post(
            channels, f"{BASE}/{root.id}/retry", {"channel": "smtp", "confirmed": True}
        ).status_code
        == 409
    )
    assert channels.client.get(BASE).json() == []


def test_handle_stops_both_channels_clears_data_and_persists_explicit_status(channels, actors):
    root, tg = pair(channels)
    login_admin(channels, actors)
    url = f"{BASE}/{root.id}/handle"
    assert post(channels, url, {"confirmed": True}).status_code == 200
    for job in (root, tg):
        channels.db.refresh(job)
        assert job.status == "cancelled" and job.last_error_code == "manually_handled"
        assert job.recipient is None and job.payload == {}
    assert channels.client.get(BASE).json() == []
    rows = channels.client.get(BASE + "?view=handled").json()
    assert rows[0]["status"] == "handled" and rows[0]["email"] is None
    assert post(channels, url, {"confirmed": True}).status_code == 200
    assert (
        post(
            channels, f"{BASE}/{root.id}/retry", {"confirmed": True, "channel": "smtp"}
        ).status_code
        == 409
    )
    assert helpers.process(channels, now=datetime.now(UTC) + timedelta(days=2)) == 0


@pytest.mark.parametrize("action", ["retry", "handle"])
def test_mutations_require_admin_csrf_and_explicit_confirmation(channels, actors, action):
    root, _ = pair(channels)
    url = f"{BASE}/{root.id}/{action}"
    payload = {"confirmed": True, **({"channel": "smtp"} if action == "retry" else {})}
    assert post(channels, url, payload).status_code == 401
    login_customer(channels, actors.customer.email)
    assert post(channels, url, payload).status_code == 403
    login_admin(channels, actors)
    assert channels.client.post(url, json=payload).status_code == 403
    assert post(channels, url, payload | {"confirmed": False}).status_code == 422
    assert (
        post(channels, url, {k: v for k, v in payload.items() if k != "confirmed"}).status_code
        == 422
    )
    assert post(channels, f"{BASE}/{uuid4()}/{action}", payload).status_code == 404
    assert root.status == "failed"


def test_retry_rejected_at_seven_days_and_worker_cannot_bypass(channels, actors):
    root, _ = pair(channels, age=timedelta(days=7))
    login_admin(channels, actors)
    assert (
        post(
            channels, f"{BASE}/{root.id}/retry", {"confirmed": True, "channel": "smtp"}
        ).status_code
        == 409
    )
    assert not service.deliver_from_app(channels.app, root.id, force=True)
    assert channels.app.state.notification_mailer.consultations == []
    assert channels.client.get(BASE).json()[0]["email"] is None


def test_processing_channel_prevents_handling_or_stealing_lease(channels, actors):
    root, tg = pair(channels)
    tg.status, tg.lease_id = "processing", uuid4()
    tg.lease_until = datetime.now(UTC) + timedelta(minutes=5)
    channels.db.commit()
    login_admin(channels, actors)
    assert post(channels, f"{BASE}/{root.id}/handle", {"confirmed": True}).status_code == 409
    assert root.recipient == "private@example.ru"
    assert (
        post(
            channels, f"{BASE}/{root.id}/retry", {"confirmed": True, "channel": "telegram"}
        ).status_code
        == 409
    )


def test_warning_starts_at_twenty_four_hours_and_permanent_is_immediate(channels):
    root, _ = pair(channels, age=timedelta(), smtp="pending", telegram="sent")
    from sinegor.modules.notifications import consultations

    at = root.created_at
    for offset, expected in [(-1, False), (0, True), (1, True)]:
        row = consultations.list_consultations(
            channels.db, now=at + timedelta(hours=24, microseconds=offset)
        )[0]
        assert row["channels"][0]["attention"] is expected
    root.status = "failed"
    channels.db.commit()
    assert consultations.list_consultations(channels.db, now=at)[0]["channels"][0]["attention"]


def test_pagination_and_no_other_notifications(channels, actors):
    roots = [pair(channels)[0] for _ in range(3)]
    service.enqueue(channels.db, "invitation", recipient="unrelated@example.ru")
    channels.db.commit()
    login_admin(channels, actors)
    first = channels.client.get(BASE + "?limit=2").json()
    second = channels.client.get(BASE + "?limit=2&offset=2").json()
    assert len(first) == 2 and len(second) == 1
    assert {r["id"] for r in first + second} == {str(r.id) for r in roots}
    assert channels.client.get(BASE + "?limit=101").status_code == 422


def test_manual_retry_survives_lost_background_task(channels, actors, monkeypatch):
    from fastapi import BackgroundTasks

    root, tg = pair(channels, age=timedelta(days=4), smtp="expired", telegram="sent")
    login_admin(channels, actors)
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *args, **kwargs: None)
    assert (
        post(
            channels, f"{BASE}/{root.id}/retry", {"channel": "smtp", "confirmed": True}
        ).status_code
        == 202
    )
    channels.db.refresh(root)
    assert root.status == "pending"
    assert helpers.process(channels) == 1
    channels.db.refresh(root)
    assert root.status == "sent" and root.recipient is None
    assert tg.attempts == 0


def test_manual_telegram_retry_cannot_bypass_retry_after(channels, actors):
    from sinegor.integrations.telegram.client import TelegramDeliveryError

    root, tg = pair(channels, age=timedelta(), smtp="sent", telegram="pending")

    def limited(*args):
        raise TelegramDeliveryError(3600)

    channels.app.state.telegram_notifier.send = limited
    helpers.process(channels)
    login_admin(channels, actors)
    assert (
        post(
            channels, f"{BASE}/{root.id}/retry", {"channel": "telegram", "confirmed": True}
        ).status_code
        == 409
    )
    assert not service.deliver_from_app(channels.app, tg.id, force=True)
    channels.db.refresh(tg)
    assert tg.attempts == 1


def test_handling_partial_smtp_success_keeps_success_and_anonymous_history(channels, actors):
    root, tg = pair(channels, smtp="sent", telegram="failed")
    login_admin(channels, actors)
    row = channels.client.get(BASE).json()[0]
    assert row["email"] is None and row["phone"] is None
    assert post(channels, f"{BASE}/{root.id}/handle", {"confirmed": True}).status_code == 200
    channels.db.refresh(root)
    channels.db.refresh(tg)
    assert root.status == "sent" and tg.status == "cancelled"
    assert channels.client.get(BASE + "?view=handled").json()[0]["status"] == "handled"


def test_failed_manual_attempt_does_not_restart_automatic_period(channels, actors):
    root, _ = pair(channels, age=timedelta(days=4), smtp="expired", telegram="sent")
    login_admin(channels, actors)
    channels.app.state.notification_mailer.fail = True
    created = root.created_at
    assert (
        post(
            channels, f"{BASE}/{root.id}/retry", {"confirmed": True, "channel": "smtp"}
        ).status_code
        == 202
    )
    channels.db.refresh(root)
    assert root.status == "pending" and root.attempts == 1 and root.created_at == created
    helpers.process(channels, now=root.available_at)
    channels.db.refresh(root)
    assert root.status == "expired" and root.attempts == 1


@pytest.mark.parametrize("error_code", ["telegram_failed", "telegram_rate_limited"])
def test_saved_telegram_wait_is_preserved_for_old_and_new_error_codes(channels, actors, error_code):
    root, tg = pair(channels, age=timedelta(), smtp="sent", telegram="pending")
    tg.last_error_code = error_code
    tg.available_at = datetime.now(UTC) + timedelta(hours=1)
    channels.db.commit()
    login_admin(channels, actors)
    assert (
        post(
            channels, f"{BASE}/{root.id}/retry", {"confirmed": True, "channel": "telegram"}
        ).status_code
        == 409
    )
    assert not service.deliver_from_app(channels.app, tg.id, force=True)


def test_queued_manual_attempt_at_contact_cutoff_is_reported_expired(channels, actors):
    from sinegor.modules.notifications import consultations

    root, _ = pair(channels, age=timedelta(days=4), smtp="expired", telegram="sent")
    consultations.retry_consultation(channels.db, root.id, "smtp")
    cutoff = root.created_at + timedelta(days=7)
    helpers.process(channels, now=cutoff)
    row = consultations.list_consultations(channels.db, now=cutoff)[0]
    assert row["channels"][0]["status"] == "expired"
    assert row["channels"][0]["reason"] == "expired"

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_auth as helpers
from sqlalchemy import func, select
from test_agreements import pdf
from test_auth import post
from test_orders import ResultMailer, approve, mutate, status

from sinegor.db.types import AgreementStatus, DeletionReason, DeletionStatus, OrderStatus
from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.integrations.telegram.client import TelegramDeliveryError
from sinegor.modules.agreements import service as agreements
from sinegor.modules.agreements.storage import AgreementStorage
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.auth.models import AuthToken
from sinegor.modules.customers.models import Customer
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications import service
from sinegor.modules.notifications.models import Notification
from sinegor.modules.retention.models import DeletionRequest

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors


class Notices:
    fail = False

    def __init__(self):
        self.messages = []

    def send_agreement_notice(self, recipient, number, kind):
        if self.fail:
            raise MailDeliveryError("simulated private response")
        self.messages.append((recipient, number, kind))


class Telegram:
    fail = False

    def __init__(self):
        self.messages = []

    def send(self, text):
        if self.fail:
            raise TelegramDeliveryError(120)
        self.messages.append(text)


@pytest.fixture
def channels(auth, actors, tmp_path):
    auth.app.state.notification_mailer = Notices()
    auth.app.state.telegram_notifier = Telegram()
    auth.app.state.order_mailer = ResultMailer()
    auth.settings.notification_admin_email = actors.admin.email
    auth.app.state.agreement_storage = AgreementStorage(tmp_path / "agreements")
    return auth


def process(auth, **kwargs):
    return service.process_pending(
        auth.db,
        auth.settings,
        auth_mailer=auth.mailer,
        order_mailer=auth.app.state.order_mailer,
        mailer=auth.app.state.notification_mailer,
        telegram=auth.app.state.telegram_notifier,
        **kwargs,
    )


def test_consultation_no_crm_and_contact_data_cleared(channels, actors):
    count = channels.db.scalar(select(func.count()).select_from(Customer))
    response = post(
        channels,
        "/api/consultations",
        {"email": " Person@Example.ru ", "phone": "+7 (999) 123-45-67"},
    )
    assert response.status_code == 202
    assert channels.app.state.telegram_notifier.messages == [
        "SINEGOR — заявка на консультацию\nEmail: person@example.ru\nТелефон: +79991234567",
    ]
    job = channels.db.scalar(select(Notification))
    assert job.kind == "consultation" and job.status == "sent" and job.attempts == 1
    assert job.recipient is None and job.payload == {}
    assert channels.db.scalar(select(func.count()).select_from(Customer)) == count
    assert process(channels) == 0


def test_consultation_validation_csrf_and_limits(channels):
    payload = {"email": "a@example.ru", "phone": "+79991234567"}
    assert channels.client.post("/api/consultations", json=payload).status_code == 403
    csrf = channels.client.get("/api/auth/csrf").json()["csrf_token"]
    assert (
        channels.client.post(
            "/api/consultations",
            json=payload,
            headers={"Origin": "https://untrusted.example", "X-CSRF-Token": csrf},
        ).status_code
        == 403
    )
    for invalid in (
        {"email": "a@example.ru"},
        {"phone": "+79991234567"},
        payload | {"email": "bad"},
        payload | {"phone": "not a phone"},
        payload | {"phone": "+1234567" + " " * 43},
        payload | {"files": []},
    ):
        assert post(channels, "/api/consultations", invalid).status_code == 422
    assert channels.db.scalar(select(func.count()).select_from(Notification)) == 0
    for index in range(channels.settings.auth_account_limit):
        # Changing the phone must not bypass the existing email identity limit.
        assert (
            post(
                channels, "/api/consultations", payload | {"phone": f"+7999123456{index}"}
            ).status_code
            == 202
        )
    assert post(channels, "/api/consultations", payload).status_code == 429


def test_consultation_ip_limit_is_preserved(channels):
    channels.settings.auth_ip_limit = 2
    for index in range(2):
        assert (
            post(
                channels,
                "/api/consultations",
                {"email": f"person{index}@example.ru", "phone": "+79991234567"},
            ).status_code
            == 202
        )
    assert (
        post(
            channels,
            "/api/consultations",
            {"email": "another@example.ru", "phone": "+442079460958"},
        ).status_code
        == 429
    )


def test_consultation_errors_and_delivery_logs_do_not_expose_contacts(channels, caplog):
    payload = {"email": "private@example.ru", "phone": "+79991234567\nInjected: private"}
    response = post(channels, "/api/consultations", payload)
    assert response.status_code == 422
    assert "private" not in response.text
    channels.app.state.telegram_notifier.fail = True
    assert (
        post(channels, "/api/consultations", payload | {"phone": "+79991234567"}).status_code == 202
    )
    assert "notification_delivery_failed" in caplog.text
    assert "private@example.ru" not in caplog.text
    assert "+79991234567" not in caplog.text


def test_telegram_failure_retains_job_and_obeys_retry_after(channels):
    channels.app.state.telegram_notifier.fail = True
    assert (
        post(
            channels,
            "/api/consultations",
            {"email": "a@example.ru", "phone": "+7 (999) 123-45-67"},
        ).status_code
        == 202
    )
    job = channels.db.scalar(select(Notification))
    assert job.status == "pending" and job.last_error_code == "telegram_failed"
    assert job.recipient == "a@example.ru" and job.attempts == 1
    assert job.payload == {"phone": "+79991234567"}
    assert process(channels, now=job.available_at - timedelta(microseconds=1)) == 0
    channels.app.state.telegram_notifier.fail = False
    assert process(channels, now=job.available_at) == 1
    assert job.status == "sent" and job.recipient is None and job.attempts == 2
    assert job.payload == {}
    assert channels.app.state.telegram_notifier.messages == [
        "SINEGOR — заявка на консультацию\nEmail: a@example.ru\nТелефон: +79991234567"
    ]
    assert process(channels, now=job.available_at) == 0


def test_committed_request_survives_missing_background_task(channels, monkeypatch):
    from sinegor.modules.notifications import router

    monkeypatch.setattr(router, "deliver_from_app", lambda *args: None)
    assert (
        post(
            channels,
            "/api/consultations",
            {"email": "a@example.ru", "phone": "+79991234567"},
        ).status_code
        == 202
    )
    assert not channels.app.state.telegram_notifier.messages
    assert channels.db.scalar(select(Notification)).status == "pending"
    assert process(channels) == 1
    assert "Телефон: +79991234567" in channels.app.state.telegram_notifier.messages[0]


def test_magic_link_survives_process_stop_and_never_stores_raw_token(channels, actors, monkeypatch):
    from sinegor.modules.auth import router

    monkeypatch.setattr(router, "deliver_from_app", lambda *args: None)
    assert (
        post(channels, "/api/auth/magic-link/request", {"email": actors.customer.email}).status_code
        == 202
    )
    assert not channels.mailer.messages
    assert channels.db.scalar(select(AuthToken)) is None
    assert process(channels) == 1
    raw = channels.mailer.token()
    job = channels.db.scalar(select(Notification))
    assert raw not in repr(job.__dict__)
    assert job.payload == {} and job.recipient is None
    assert post(channels, "/api/auth/magic-link/verify", {"token": raw}).status_code == 204


def test_unknown_magic_link_is_uniform_and_clears_contact_data(channels):
    response = post(channels, "/api/auth/magic-link/request", {"email": "unknown@example.ru"})
    assert response.status_code == 202
    job = channels.db.scalar(select(Notification))
    assert job.status == "cancelled" and job.recipient is None
    assert not channels.mailer.messages


def test_invitation_error_retries_without_losing_previous_link(channels, actors):
    helpers.login_admin(channels, actors)
    path = f"/api/admin/customers/{actors.customer.id}/invite"
    assert post(channels, path).status_code == 202
    previous = channels.mailer.token()
    channels.mailer.fail = True
    assert post(channels, path).status_code == 503
    job = channels.db.scalar(select(Notification).where(Notification.status == "pending"))
    assert job.kind == "invitation" and job.last_error_code == "smtp_failed"
    assert post(channels, "/api/auth/magic-link/verify", {"token": previous}).status_code == 204
    channels.mailer.fail = False
    assert process(channels, now=job.available_at) == 1
    assert (
        post(
            channels, "/api/auth/magic-link/verify", {"token": channels.mailer.token()}
        ).status_code
        == 204
    )


def test_email_edit_cancels_pending_old_identity(channels, actors):
    helpers.login_admin(channels, actors)
    channels.mailer.fail = True
    assert post(channels, f"/api/admin/customers/{actors.customer.id}/invite").status_code == 503
    job = channels.db.scalar(select(Notification))
    assert (
        mutate(
            channels,
            "PATCH",
            f"/api/admin/customers/{actors.customer.id}",
            {"email": "new@example.ru"},
        ).status_code
        == 200
    )
    channels.mailer.fail = False
    assert process(channels, now=job.available_at) == 0
    assert job.status == "cancelled" and not channels.mailer.messages


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_agreement_notifications_follow_committed_revisions(channels, actors, decision):
    storage = channels.app.state.agreement_storage
    order = actors.order
    item = agreements.upload(
        channels.db, storage, order.id, pdf("initial"), 0, actors.admin.id, initial=True
    )
    assert process(channels) == 1
    item = agreements.upload(
        channels.db,
        storage,
        order.id,
        pdf("returned"),
        item.revision,
        actors.customer.id,
        initial=False,
    )
    assert process(channels) == 1
    agreements.review(
        channels.db,
        storage,
        order.id,
        item.revision,
        actors.admin.id,
        reason="Sign again" if decision == "reject" else None,
    )
    assert process(channels) == 1
    messages = channels.app.state.notification_mailer.messages
    assert [m[2] for m in messages] == [
        "agreement_initial",
        "agreement_returned",
        "agreement_approved" if decision == "approve" else "agreement_rejected",
    ]
    assert messages[0][0] == actors.customer.email and messages[1][0] == actors.admin.email
    assert process(channels) == 0


def test_agreement_failure_does_not_undo_upload_and_stale_notice_is_cancelled(channels, actors):
    storage = channels.app.state.agreement_storage
    item = agreements.upload(
        channels.db, storage, actors.order.id, pdf("initial"), 0, actors.admin.id, initial=True
    )
    channels.app.state.notification_mailer.fail = True
    assert process(channels) == 0
    assert item.status == AgreementStatus.AWAITING_CUSTOMER
    assert storage.read(item.initial_pdf_key, item.initial_sha256)[0]
    job = channels.db.scalar(select(Notification))
    agreements.upload(
        channels.db,
        storage,
        actors.order.id,
        pdf("returned"),
        item.revision,
        actors.customer.id,
        initial=False,
    )
    channels.app.state.notification_mailer.fail = False
    assert process(channels, now=job.available_at) == 1
    assert job.status == "cancelled"


def test_result_ready_retries_and_starts_clock_only_after_smtp(channels, actors):
    helpers.login_admin(channels, actors)
    approve(channels, actors)
    assert status(channels, actors.order, "awaiting_materials").status_code == 200
    assert status(channels, actors.order, "in_progress").status_code == 200
    channels.app.state.order_mailer.fail = True
    assert (
        status(
            channels, actors.order, "result_ready", result_uploaded=True, access_read_only=True
        ).status_code
        == 503
    )
    job = channels.db.scalar(select(Notification))
    assert (
        actors.order.result_notified_at is None and actors.order.status == OrderStatus.IN_PROGRESS
    )
    channels.app.state.order_mailer.fail = False
    assert process(channels, now=job.available_at) == 1
    channels.db.refresh(actors.order)
    assert actors.order.status == OrderStatus.RESULT_READY and actors.order.result_notified_at
    event = channels.db.scalar(
        select(OrderEvent).where(OrderEvent.event_type == "status_result_ready")
    )
    assert event.actor_admin_id == actors.admin.id
    assert process(channels) == 0


def test_result_ready_can_retry_cancelled_notification_after_email_round_trip(channels, actors):
    helpers.login_admin(channels, actors)
    approve(channels, actors)
    assert status(channels, actors.order, "awaiting_materials").status_code == 200
    assert status(channels, actors.order, "in_progress").status_code == 200
    channels.app.state.order_mailer.fail = True
    assert (
        status(
            channels, actors.order, "result_ready", result_uploaded=True, access_read_only=True
        ).status_code
        == 503
    )
    job = channels.db.scalar(select(Notification))
    original_email = actors.customer.email
    customer_path = f"/api/admin/customers/{actors.customer.id}"
    assert (
        mutate(channels, "PATCH", customer_path, {"email": "changed@example.ru"}).status_code == 200
    )
    assert process(channels, now=job.available_at) == 0
    assert job.status == "cancelled" and job.recipient is None and job.payload == {}
    assert mutate(channels, "PATCH", customer_path, {"email": original_email}).status_code == 200
    channels.app.state.order_mailer.fail = False
    assert process(channels, now=job.available_at) == 0
    assert job.status == "cancelled" and not channels.app.state.order_mailer.messages
    assert actors.order.status == OrderStatus.IN_PROGRESS
    assert actors.order.result_notified_at is None

    assert (
        status(
            channels, actors.order, "result_ready", result_uploaded=True, access_read_only=True
        ).status_code
        == 200
    )
    channels.db.refresh(actors.order)
    assert actors.order.status == OrderStatus.RESULT_READY
    assert actors.order.result_notified_at is not None
    assert channels.app.state.order_mailer.messages == [(original_email, actors.order.number)]
    assert process(channels) == 0
    assert (
        status(
            channels, actors.order, "result_ready", result_uploaded=True, access_read_only=True
        ).status_code
        == 409
    )
    assert len(channels.app.state.order_mailer.messages) == 1
    assert (
        channels.db.scalar(
            select(func.count())
            .select_from(OrderEvent)
            .where(OrderEvent.event_type == "status_result_ready")
        )
        == 1
    )


def ready(channels, actors):
    now = datetime.now(UTC)
    order = actors.order
    order.created_at = now - timedelta(days=20)
    order.ready_at = order.result_notified_at = now - timedelta(days=15)
    order.status = OrderStatus.RESULT_READY
    channels.db.add(
        DiskFolder(order_id=order.id, disk_path=f"disk:/orders/{order.id}", resource_id="folder")
    )
    channels.db.commit()
    return now


def test_deletion_reminder_once_without_deletion_or_request_creation(channels, actors):
    now = ready(channels, actors)
    assert service.queue_deletion_reminders(channels.db, now=now) == 1
    assert service.queue_deletion_reminders(channels.db, now=now) == 0
    assert process(channels) == 1
    assert len(channels.app.state.telegram_notifier.messages) == 1
    assert str(actors.order.number) in channels.app.state.telegram_notifier.messages[0]
    assert channels.db.scalar(select(DeletionRequest)) is None
    assert (
        actors.order.status == OrderStatus.RESULT_READY and not actors.order.disk_folder.deleted_at
    )


def test_deletion_deferral_cancels_stale_reminder(channels, actors):
    now = ready(channels, actors)
    assert service.queue_deletion_reminders(channels.db) == 1
    deletion = DeletionRequest(
        order_id=actors.order.id,
        reason=DeletionReason.RETENTION_EXPIRED,
        status=DeletionStatus.DEFERRED,
        due_at=now - timedelta(days=1),
        deferred_until=now + timedelta(days=2),
        admin_note="Pending clarification",
    )
    channels.db.add(deletion)
    channels.db.commit()
    channels.db.refresh(actors.order)
    assert process(channels) == 0
    assert not channels.app.state.telegram_notifier.messages
    assert service.queue_deletion_reminders(channels.db) == 0


def test_expired_worker_lease_can_be_recovered(channels):
    # Jobs queued before phone became required must remain deliverable.
    identifier = service.enqueue(channels.db, "consultation", recipient="a@example.ru")
    channels.db.commit()
    job = channels.db.get(Notification, identifier)
    job.status, job.lease_id = "processing", uuid4()
    job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    channels.db.commit()
    assert process(channels) == 1
    assert job.status == "sent" and job.lease_id is None and job.lease_until is None
    assert channels.app.state.telegram_notifier.messages == [
        "SINEGOR — заявка на консультацию\nEmail: a@example.ru"
    ]


def test_result_notification_can_be_reissued_after_customer_email_changes(channels, actors):
    helpers.login_admin(channels, actors)
    approve(channels, actors)
    assert status(channels, actors.order, "awaiting_materials").status_code == 200
    assert status(channels, actors.order, "in_progress").status_code == 200
    channels.app.state.order_mailer.fail = True
    assert (
        status(
            channels, actors.order, "result_ready", result_uploaded=True, access_read_only=True
        ).status_code
        == 503
    )
    assert (
        mutate(
            channels,
            "PATCH",
            f"/api/admin/customers/{actors.customer.id}",
            {"email": "updated@example.ru"},
        ).status_code
        == 200
    )
    channels.app.state.order_mailer.fail = False
    assert (
        status(
            channels, actors.order, "result_ready", result_uploaded=True, access_read_only=True
        ).status_code
        == 200
    )
    assert channels.app.state.order_mailer.messages == [("updated@example.ru", actors.order.number)]
    pending = channels.db.scalar(select(Notification).where(Notification.status == "pending"))
    assert process(channels, now=pending.available_at) == 0
    assert pending.status == "cancelled"


def test_cancelled_order_does_not_send_agreement_action(channels, actors):
    agreements.upload(
        channels.db,
        channels.app.state.agreement_storage,
        actors.order.id,
        pdf("initial"),
        0,
        actors.admin.id,
        initial=True,
    )
    actors.order.status = OrderStatus.CANCELLED
    actors.order.closed_at = datetime.now(UTC)
    channels.db.commit()
    assert process(channels) == 0
    assert channels.db.scalar(select(Notification)).status == "cancelled"
    assert not channels.app.state.notification_mailer.messages


def test_deletion_reminder_fourteen_day_boundary(channels, actors):
    ready(channels, actors)
    deadline = actors.order.result_notified_at + timedelta(days=14)
    assert (
        service.queue_deletion_reminders(channels.db, now=deadline - timedelta(microseconds=1)) == 0
    )
    assert service.queue_deletion_reminders(channels.db, now=deadline) == 1


def test_notification_outbox_rolls_back_with_domain_change(channels, actors, monkeypatch):
    def fail_before_commit(*args):
        raise RuntimeError("Simulated transaction failure")

    with monkeypatch.context() as patch:
        patch.setattr(agreements, "finish", fail_before_commit)
        with pytest.raises(RuntimeError):
            agreements.upload(
                channels.db,
                channels.app.state.agreement_storage,
                actors.order.id,
                pdf("initial"),
                0,
                actors.admin.id,
                initial=True,
            )
    channels.db.rollback()
    assert channels.db.scalar(select(Notification)) is None
    from sinegor.modules.agreements.models import Agreement

    assert channels.db.scalar(select(Agreement)) is None

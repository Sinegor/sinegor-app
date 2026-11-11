"""23.5: one administrator decision, durable result and replaceable reminders."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_retention as helpers
from sqlalchemy import select

from sinegor.db.types import DeletionReason, DeletionStatus, OrderStatus
from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.integrations.yandex_disk.client import Resource
from sinegor.modules.disk import service as disk_service
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications import service as notifications
from sinegor.modules.notifications.models import Notification
from sinegor.modules.orders.service import locked_order, transition
from sinegor.modules.retention import service
from sinegor.modules.retention.models import DeletionRequest

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors
retention = helpers.retention


def request(auth, actors, reason=DeletionReason.EARLY_PERMISSION):
    if reason == DeletionReason.ORDER_CANCELLED:
        actors.order.status = OrderStatus.IN_PROGRESS
        actors.order.ready_at = actors.order.result_notified_at = None
        auth.db.commit()
        transition(
            auth.db,
            locked_order(auth.db, actors.order.id),
            OrderStatus.CANCELLED,
            actors.admin.id,
            cancellation_internal_reason="private",
            cancellation_customer_reason="public",
        )
        auth.db.commit()
        return auth.db.scalar(select(DeletionRequest))
    if reason == DeletionReason.RETENTION_EXPIRED:
        actors.order.ready_at = actors.order.result_notified_at = datetime.now(UTC) - timedelta(
            days=15
        )
        auth.db.commit()
        service.process_due(auth.db)
        return auth.db.scalar(select(DeletionRequest))
    helpers.login_customer(auth)
    helpers.permission(auth, actors)
    helpers.admin(auth)
    return auth.db.scalar(select(DeletionRequest))


def jobs(auth, kind):
    return auth.db.scalars(select(Notification).where(Notification.kind == kind)).all()


@pytest.mark.parametrize("reason", list(DeletionReason))
def test_one_admin_action_deletes_for_each_basis_and_enqueues_one_email(retention, actors, reason):
    item = request(retention, actors, reason)
    original_status = actors.order.status
    assert item.status == DeletionStatus.WAITING
    assert jobs(retention, "materials_deleted") == []
    assert helpers.delete(retention, actors, item.id).status_code == 200
    assert helpers.delete(retention, actors, item.id).status_code == 200
    assert item.status == DeletionStatus.PERFORMED
    assert item.confirmed_by_id == actors.admin.id
    assert actors.order.status == original_status
    assert (
        retention.db.get(type(retention.agreement), retention.agreement.id).final_sha256 == "a" * 64
    )
    assert helpers.event_count(retention, "deletion_confirmed") == 1
    assert len([c for c in retention.disk.calls if c[0] == "delete"]) == 1
    (email,) = jobs(retention, "materials_deleted")
    assert email.recipient == actors.customer.email
    assert email.customer_id == actors.customer.id and email.order_id == actors.order.id
    assert "private" not in str(email.payload)
    assert notifications.queue_deletion_reminders(retention.db) == 0


def test_deferred_request_can_be_deleted_before_reminder(retention, actors):
    item = request(retention, actors)
    assert (
        helpers.deferred(
            retention, actors, item.id, datetime.now(UTC) + timedelta(days=4)
        ).status_code
        == 200
    )
    assert helpers.delete(retention, actors, item.id).status_code == 200
    assert item.status == DeletionStatus.PERFORMED


def test_reminder_date_replaces_previous_in_both_directions(retention, actors):
    item = request(retention, actors)
    later = datetime.now(UTC) + timedelta(days=4)
    earlier = later - timedelta(days=2)
    for date in [later, earlier, later]:
        assert helpers.deferred(retention, actors, item.id, date).status_code == 200
        assert item.deferred_until == date
        assert (
            notifications.queue_deletion_reminders(retention.db, now=date - timedelta(seconds=1))
            == 0
        )
    assert helpers.event_count(retention, "deletion_deferred") == 3
    assert helpers.deferred(retention, actors, item.id, later).status_code == 200
    assert helpers.event_count(retention, "deletion_deferred") == 3
    assert len(retention.db.scalars(select(DeletionRequest)).all()) == 1
    assert not [c for c in retention.disk.calls if c[0] == "delete"]


@pytest.mark.parametrize(
    "reason", [DeletionReason.EARLY_PERMISSION, DeletionReason.RETENTION_EXPIRED]
)
def test_cancellation_preserves_existing_request_and_reminders(retention, actors, reason):
    item = request(retention, actors, reason)
    # Existing open requests can survive cancellation; terminal result_ready cannot be cancelled.
    actors.order.status = OrderStatus.IN_PROGRESS
    retention.db.commit()
    transition(
        retention.db,
        locked_order(retention.db, actors.order.id),
        OrderStatus.CANCELLED,
        actors.admin.id,
        cancellation_internal_reason="private",
        cancellation_customer_reason="public",
    )
    retention.db.commit()
    assert retention.db.scalar(select(DeletionRequest)).id == item.id
    assert notifications.queue_deletion_reminders(retention.db) == 1
    assert helpers.delete(retention, actors, item.id).status_code == 200


def test_email_waits_for_verified_async_result_and_retries_smtp(retention, actors):
    class Mailer:
        fail = True
        sent = []

        def send_materials_deleted(self, recipient, number):
            if self.fail:
                raise MailDeliveryError()
            self.sent.append((recipient, number))

    mailer = Mailer()
    retention.app.state.notification_mailer = mailer
    item = request(retention, actors)
    retention.disk.pending = True
    assert helpers.delete(retention, actors, item.id).status_code == 202
    assert jobs(retention, "materials_deleted") == []
    assert helpers.delete(retention, actors, item.id).status_code == 202
    assert jobs(retention, "materials_deleted") == []
    retention.disk.status = "failed"
    assert helpers.delete(retention, actors, item.id).status_code == 503
    assert jobs(retention, "materials_deleted") == []
    retention.disk.pending = False
    assert helpers.delete(retention, actors, item.id).status_code == 200
    (email,) = jobs(retention, "materials_deleted")

    channels = dict(auth_mailer=None, order_mailer=None, mailer=mailer, telegram=None)
    assert notifications.process_pending(retention.db, retention.settings, **channels) == 0
    assert email.status == "pending"
    email.available_at = datetime.now(UTC) - timedelta(seconds=1)
    retention.db.commit()
    mailer.fail = False
    assert notifications.process_pending(retention.db, retention.settings, **channels) == 1
    assert mailer.sent == [(actors.customer.email, actors.order.number)]
    assert notifications.process_pending(retention.db, retention.settings, **channels) == 0


def test_unverified_or_changed_folder_never_closes_request_or_sends_email(retention, actors):
    item = request(retention, actors)
    folder = retention.db.scalar(select(DiskFolder))
    retention.disk.resources[folder.disk_path] = Resource(folder.disk_path, "another-resource")
    assert helpers.delete(retention, actors, item.id).status_code == 409
    assert item.status != DeletionStatus.PERFORMED and item.performed_at is None
    assert jobs(retention, "materials_deleted") == []
    assert not [c for c in retention.disk.calls if c[0] == "delete"]


def test_future_retention_deadline_and_wrong_request_still_block_deletion(retention, actors):
    item = DeletionRequest(
        order=actors.order,
        reason=DeletionReason.RETENTION_EXPIRED,
        due_at=actors.order.result_notified_at + timedelta(days=14),
    )
    retention.db.add(item)
    retention.db.commit()
    assert helpers.delete(retention, actors, item.id).status_code == 409
    assert helpers.delete(retention, actors, uuid4()).status_code == 409
    assert item.confirmed_at is None
    assert not [c for c in retention.disk.calls if c[0] == "delete"]


def test_finalization_and_email_are_atomic_and_recoverable(retention, actors, monkeypatch):
    item = request(retention, actors)
    original = notifications.enqueue

    def fail(db, kind, **kwargs):
        if kind == "materials_deleted":
            raise RuntimeError("outbox unavailable")
        return original(db, kind, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(notifications, "enqueue", fail)
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            disk_service.delete_folder(
                retention.db, retention.disk, actors.order.id, item.id, actors.admin.id
            )
    retention.db.rollback()
    retention.db.refresh(item)
    assert item.status != DeletionStatus.PERFORMED
    assert retention.db.scalar(select(DiskFolder)).deleted_at is None
    assert helpers.delete(retention, actors, item.id).status_code == 200
    assert len(jobs(retention, "materials_deleted")) == 1
    assert len([c for c in retention.disk.calls if c[0] == "delete"]) == 1


def test_deferral_cancels_old_reminder_and_deletion_cancels_new_one(retention, actors):
    item = request(retention, actors)
    assert notifications.queue_deletion_reminders(retention.db) == 1
    until = datetime.now(UTC) + timedelta(days=2)
    assert helpers.deferred(retention, actors, item.id, until).status_code == 200
    channels = dict(auth_mailer=None, order_mailer=None, mailer=None, telegram=None)
    # A stale Telegram task is cancelled without ever touching the channel.
    assert notifications.process_pending(retention.db, retention.settings, **channels) == 0
    assert jobs(retention, "deletion_due")[0].status == "cancelled"
    earlier = until - timedelta(days=1)
    assert helpers.deferred(retention, actors, item.id, earlier).status_code == 200
    assert notifications.queue_deletion_reminders(retention.db, now=earlier) == 1
    assert helpers.delete(retention, actors, item.id).status_code == 200
    reminder = [j for j in jobs(retention, "deletion_due") if j.status == "pending"][0]
    assert (
        notifications.deliver_one(retention.db, retention.settings, reminder.id, **channels)
        is False
    )
    assert reminder.status == "cancelled"


def test_returning_to_a_previously_cancelled_reminder_date_restores_delivery(retention, actors):
    item = request(retention, actors)
    first = datetime.now(UTC) + timedelta(days=2)
    second = first + timedelta(days=1)
    assert helpers.deferred(retention, actors, item.id, first).status_code == 200
    assert notifications.queue_deletion_reminders(retention.db, now=first) == 1
    assert helpers.deferred(retention, actors, item.id, second).status_code == 200
    assert (
        notifications.process_pending(
            retention.db,
            retention.settings,
            auth_mailer=None,
            order_mailer=None,
            mailer=None,
            telegram=None,
        )
        == 0
    )
    assert jobs(retention, "deletion_due")[0].status == "cancelled"
    assert helpers.deferred(retention, actors, item.id, first).status_code == 200
    assert notifications.queue_deletion_reminders(retention.db, now=first) == 1
    (reminder,) = jobs(retention, "deletion_due")
    assert reminder.status == "pending"
    assert reminder.payload["due_at"] == first.isoformat()

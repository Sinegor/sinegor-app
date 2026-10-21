from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_auth as helpers
from sqlalchemy import func, select
from test_auth import login_admin, post
from test_disk import MemoryDisk
from test_orders import approve

from sinegor.db.types import DeletionReason, DeletionStatus, OrderStatus
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications import service as notifications
from sinegor.modules.orders.service import process_lifecycle
from sinegor.modules.retention import service
from sinegor.modules.retention.models import DeletionRequest

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors


@pytest.fixture
def retention(auth, actors):
    login_admin(auth, actors)
    auth.admin_cookies = dict(auth.client.cookies)
    auth.disk = auth.app.state.yandex_disk = MemoryDisk()
    assert post(auth, f"/api/admin/orders/{actors.order.id}/folder").status_code == 200
    auth.agreement = approve(auth, actors)
    now = datetime.now(UTC)
    actors.order.created_at = now - timedelta(days=20)
    actors.order.ready_at = actors.order.result_notified_at = now - timedelta(days=1)
    actors.order.status = OrderStatus.RESULT_READY
    auth.db.commit()
    return auth


def admin(auth):
    auth.client.cookies.clear()
    auth.client.cookies.update(auth.admin_cookies)


def login_customer(auth):
    # A separate browser must not revoke the administrator's session when logging in.
    auth.client.cookies.clear()
    helpers.login_customer(auth)


def path(actors):
    return f"/api/admin/orders/{actors.order.id}/deletion-request"


def permission(auth, actors, **payload):
    return post(
        auth,
        f"/api/customer/orders/{actors.order.id}/deletion-permission",
        {"confirm": True, **payload},
    )


def confirmed(auth, actors, identifier):
    return post(
        auth, path(actors) + "/confirm", {"deletion_request_id": str(identifier), "confirm": True}
    )


def deferred(auth, actors, identifier, until, note="Accepted clarification by email"):
    return post(
        auth,
        path(actors) + "/defer",
        {"deletion_request_id": str(identifier), "deferred_until": until.isoformat(), "note": note},
    )


def delete(auth, actors, identifier):
    return post(
        auth,
        f"/api/admin/orders/{actors.order.id}/folder/delete",
        {"deletion_request_id": str(identifier), "confirm": True},
    )


def event_count(auth, name):
    return auth.db.scalar(
        select(func.count()).select_from(OrderEvent).where(OrderEvent.event_type == name)
    )


def test_fourteen_day_boundary_creates_one_request_without_deleting(retention, actors):
    due = actors.order.result_notified_at + timedelta(days=14)
    assert process_lifecycle(retention.db, now=due - timedelta(microseconds=1)) == 0
    assert service.process_due(retention.db, now=due - timedelta(microseconds=1)) == 0
    assert retention.db.scalar(select(DeletionRequest)) is None
    assert process_lifecycle(retention.db, now=due) == 1
    assert service.process_due(retention.db, now=due) == 1
    item = retention.db.scalar(select(DeletionRequest))
    assert item.reason == DeletionReason.RETENTION_EXPIRED
    assert item.status == DeletionStatus.WAITING and item.due_at == due
    assert item.confirmed_at is None and item.performed_at is None
    assert service.process_due(retention.db, now=due) == 0
    assert process_lifecycle(retention.db, now=due) == 0
    assert actors.order.status == OrderStatus.COMPLETED
    assert event_count(retention, "deletion_requested") == 1
    assert not [c for c in retention.disk.calls if c[0] == "delete"]
    assert retention.db.get(type(retention.agreement), retention.agreement.id)


def test_due_request_is_visible_even_if_folder_binding_is_missing(retention, actors):
    folder = retention.db.scalar(select(DiskFolder))
    retention.db.delete(folder)
    retention.db.commit()
    assert (
        service.process_due(retention.db, now=actors.order.result_notified_at + timedelta(days=14))
        == 1
    )
    assert retention.client.get(path(actors)).json()["status"] == "waiting"


def test_early_permission_is_idempotent_and_attributed_to_customer(retention, actors):
    login_customer(retention)
    first = permission(retention, actors)
    assert first.status_code == 200, first.text
    assert permission(retention, actors).json() == first.json()
    item = retention.db.scalar(select(DeletionRequest))
    assert item.reason == DeletionReason.EARLY_PERMISSION
    assert item.status == DeletionStatus.WAITING
    assert item.early_authorized_at >= actors.order.result_notified_at
    assert "admin_note" not in first.json() and "confirmed_by_id" not in first.json()
    event = retention.db.scalar(
        select(OrderEvent).where(OrderEvent.event_type == "deletion_early_authorized")
    )
    assert event.actor_customer_id == actors.customer.id and event.actor_admin_id is None
    assert event_count(retention, "deletion_early_authorized") == 1
    assert actors.order.status == OrderStatus.RESULT_READY
    assert not [c for c in retention.disk.calls if c[0] == "delete"]


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_customer_permission_requires_explicit_boolean(retention, actors, value):
    login_customer(retention)
    assert permission(retention, actors, confirm=value).status_code == 422
    assert retention.db.scalar(select(DeletionRequest)) is None


@pytest.mark.parametrize("state", [OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED])
def test_no_permission_before_notified_result(retention, actors, state):
    actors.order.status = state
    actors.order.ready_at = actors.order.result_notified_at = None
    actors.order.closed_at = datetime.now(UTC) if state == OrderStatus.CANCELLED else None
    retention.db.commit()
    login_customer(retention)
    assert permission(retention, actors).status_code == 409
    assert retention.db.scalar(select(DeletionRequest)) is None


def test_early_delete_requires_admin_decision_and_preserves_agreement(retention, actors):
    login_customer(retention)
    identifier = permission(retention, actors).json()["id"]
    admin(retention)
    assert delete(retention, actors, identifier).status_code == 409
    first = confirmed(retention, actors, identifier)
    assert first.status_code == 200
    assert first.json()["confirmed_by_id"] == str(actors.admin.id)
    assert confirmed(retention, actors, identifier).json() == first.json()
    assert event_count(retention, "deletion_confirmed") == 1
    assert not [c for c in retention.disk.calls if c[0] == "delete"]
    assert delete(retention, actors, identifier).status_code == 200
    assert delete(retention, actors, identifier).status_code == 200
    item = retention.db.scalar(select(DeletionRequest))
    assert item.status == DeletionStatus.PERFORMED and item.performed_at
    assert actors.order.status == OrderStatus.RESULT_READY
    assert (
        retention.db.get(type(retention.agreement), retention.agreement.id).final_sha256 == "a" * 64
    )
    assert event_count(retention, "disk_folder_deleted") == 1
    assert len([c for c in retention.disk.calls if c[0] == "delete"]) == 1
    due = actors.order.result_notified_at + timedelta(days=14)
    assert process_lifecycle(retention.db, now=due) == 1
    assert service.process_due(retention.db, now=due) == 0
    assert actors.order.status == OrderStatus.COMPLETED
    assert item.status == DeletionStatus.PERFORMED


def test_premature_confirmation_and_wrong_request_never_delete(retention, actors):
    retention.db.add(
        DeletionRequest(
            order=actors.order,
            reason=DeletionReason.RETENTION_EXPIRED,
            due_at=actors.order.result_notified_at + timedelta(days=14),
        )
    )
    retention.db.commit()
    item = retention.db.scalar(select(DeletionRequest))
    assert confirmed(retention, actors, item.id).status_code == 409
    assert confirmed(retention, actors, uuid4()).status_code == 409
    assert delete(retention, actors, item.id).status_code == 409
    assert item.status == DeletionStatus.WAITING


def test_deferral_revokes_unexecuted_confirmation_and_requires_new_decision(retention, actors):
    login_customer(retention)
    identifier = permission(retention, actors).json()["id"]
    admin(retention)
    assert confirmed(retention, actors, identifier).status_code == 200
    until = datetime.now(UTC) + timedelta(days=2)
    first = deferred(retention, actors, identifier, until)
    assert first.status_code == 200, first.text
    assert deferred(retention, actors, identifier, until).json() == first.json()
    item = retention.db.scalar(select(DeletionRequest))
    assert item.status == DeletionStatus.DEFERRED
    assert item.confirmed_at is None and item.confirmed_by_id is None
    assert confirmed(retention, actors, identifier).status_code == 409
    assert delete(retention, actors, identifier).status_code == 409
    assert service.process_due(retention.db, now=until - timedelta(microseconds=1)) == 0
    assert service.process_due(retention.db, now=until) == 1
    assert item.status == DeletionStatus.WAITING and item.confirmed_at is None
    assert service.process_due(retention.db, now=until) == 0
    assert event_count(retention, "deletion_deferral_expired") == 1
    assert event_count(retention, "deletion_deferred") == 1
    assert not [c for c in retention.disk.calls if c[0] == "delete"]


def test_completion_is_independent_of_deferral_and_permission_does_not_cancel_it(retention, actors):
    due = actors.order.result_notified_at + timedelta(days=14)
    assert service.process_due(retention.db, now=due) == 1
    item = retention.db.scalar(select(DeletionRequest))
    until = due + timedelta(days=3)
    assert deferred(retention, actors, item.id, until).status_code == 200
    login_customer(retention)
    assert permission(retention, actors).status_code == 200
    assert item.status == DeletionStatus.DEFERRED and item.deferred_until == until
    assert process_lifecycle(retention.db, now=due) == 1
    assert actors.order.status == OrderStatus.COMPLETED
    assert item.status == DeletionStatus.DEFERRED


@pytest.mark.parametrize("change", ["empty_note", "naive_time", "past_time", "shorten"])
def test_deferral_rejects_invalid_input(retention, actors, change):
    login_customer(retention)
    identifier = permission(retention, actors).json()["id"]
    admin(retention)
    until = datetime.now(UTC) + timedelta(days=3)
    assert deferred(retention, actors, identifier, until).status_code == 200
    if change == "empty_note":
        response = deferred(retention, actors, identifier, until, note="   ")
    elif change == "naive_time":
        response = deferred(retention, actors, identifier, until.replace(tzinfo=None))
    else:
        response = deferred(
            retention,
            actors,
            identifier,
            until - timedelta(days=1 if change == "shorten" else 4),
        )
    assert response.status_code == (422 if change in {"empty_note", "naive_time"} else 409)


def test_async_deletion_prevents_changes_to_decision_and_records_failure(retention, actors):
    login_customer(retention)
    identifier = permission(retention, actors).json()["id"]
    admin(retention)
    assert confirmed(retention, actors, identifier).status_code == 200
    retention.disk.pending = True
    assert delete(retention, actors, identifier).status_code == 202
    assert (
        deferred(retention, actors, identifier, datetime.now(UTC) + timedelta(days=1)).status_code
        == 409
    )
    retention.disk.status = "failed"
    assert delete(retention, actors, identifier).status_code == 503
    item = retention.db.scalar(select(DeletionRequest))
    assert item.status == DeletionStatus.ERROR and item.performed_at is None
    assert event_count(retention, "disk_deletion_failed") == 1
    retention.disk.pending = False
    assert delete(retention, actors, identifier).status_code == 200
    assert item.status == DeletionStatus.PERFORMED


def test_access_csrf_listing_and_customer_private_fields(retention, actors):
    assert retention.client.get(path(actors)).json() is None
    login_customer(retention)
    identifier = permission(retention, actors).json()["id"]
    customer_path = f"/api/customer/orders/{actors.order.id}/deletion-request"
    assert retention.client.get(customer_path).json()["id"] == identifier
    assert (
        retention.client.get(
            f"/api/customer/orders/{actors.other_order.id}/deletion-request"
        ).status_code
        == 404
    )
    assert (
        post(
            retention,
            f"/api/customer/orders/{actors.other_order.id}/deletion-permission",
            {"confirm": True},
        ).status_code
        == 404
    )
    assert retention.client.get("/api/admin/deletion-requests").status_code == 403
    assert confirmed(retention, actors, identifier).status_code == 403
    admin(retention)
    until = datetime.now(UTC) + timedelta(days=2)
    assert (
        deferred(retention, actors, identifier, until, note="Private admin note").status_code == 200
    )
    assert len(retention.client.get("/api/admin/deletion-requests?status=deferred").json()) == 1
    assert retention.client.get("/api/admin/deletion-requests?status=waiting").json() == []
    assert retention.client.get("/api/admin/deletion-requests?limit=101").status_code == 422
    assert (
        retention.client.post(
            path(actors) + "/confirm", json={"confirm": True, "deletion_request_id": identifier}
        ).status_code
        == 403
    )
    login_customer(retention)
    assert "Private admin note" not in retention.client.get(customer_path).text
    retention.client.cookies.clear()
    assert retention.client.get(customer_path).status_code == 401


def test_early_request_is_picked_up_by_durable_telegram_notifications(retention, actors):
    class Telegram:
        messages = []

        def send(self, text):
            self.messages.append(text)

    login_customer(retention)
    assert permission(retention, actors).status_code == 200
    assert notifications.queue_deletion_reminders(retention.db) == 1
    assert notifications.queue_deletion_reminders(retention.db) == 0
    telegram = Telegram()
    assert (
        notifications.process_pending(
            retention.db,
            retention.settings,
            auth_mailer=None,
            order_mailer=None,
            mailer=None,
            telegram=telegram,
        )
        == 1
    )
    assert len(telegram.messages) == 1 and str(actors.order.number) in telegram.messages[0]
    assert retention.db.scalar(select(DeletionRequest)).status == DeletionStatus.WAITING
    assert not [c for c in retention.disk.calls if c[0] == "delete"]


@pytest.mark.parametrize("action", ["early", "confirm", "defer", "due"])
def test_request_and_event_are_rolled_back_together(retention, actors, monkeypatch, action):
    item = None
    if action in {"confirm", "defer"}:
        item = DeletionRequest(
            order=actors.order,
            reason=DeletionReason.EARLY_PERMISSION,
            early_authorized_at=datetime.now(UTC),
            due_at=datetime.now(UTC),
        )
        retention.db.add(item)
        retention.db.commit()

    def fail_event(*args, **kwargs):
        raise RuntimeError("Simulated event storage failure")

    monkeypatch.setattr(service, "record_event", fail_event)
    with pytest.raises(RuntimeError, match="Simulated event storage failure"):
        if action == "early":
            service.authorize_early(retention.db, actors.order.id, actors.customer.id)
        elif action == "confirm":
            service.confirm(retention.db, actors.order.id, item.id, actors.admin.id)
        elif action == "defer":
            service.defer(
                retention.db,
                actors.order.id,
                item.id,
                actors.admin.id,
                datetime.now(UTC) + timedelta(days=2),
                "Accepted clarification",
            )
        else:
            service.process_due(
                retention.db, now=actors.order.result_notified_at + timedelta(days=14)
            )
    retention.db.rollback()
    if item is None:
        assert retention.db.scalar(select(DeletionRequest)) is None
    else:
        retention.db.refresh(item)
        assert item.status == DeletionStatus.WAITING
        assert item.confirmed_at is None and item.deferred_until is None
    assert event_count(retention, "deletion_early_authorized") == 0
    assert event_count(retention, "deletion_requested") == 0
    assert event_count(retention, "deletion_confirmed") == 0
    assert event_count(retention, "deletion_deferred") == 0

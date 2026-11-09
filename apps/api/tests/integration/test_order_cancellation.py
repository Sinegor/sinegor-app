"""23.4: real API/transactions; only external Disk/Telegram are test doubles."""

from datetime import UTC, datetime, timedelta

import pytest
import test_auth as helpers
from fastapi import HTTPException
from sqlalchemy import event, func, select
from test_auth import login_admin, login_customer, post
from test_disk import MemoryDisk
from test_notifications import Telegram
from test_orders import approve

from sinegor.db.types import OrderStatus
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications import service as notifications
from sinegor.modules.notifications.models import Notification
from sinegor.modules.orders.models import Order
from sinegor.modules.orders.service import transition
from sinegor.modules.retention import service as retention
from sinegor.modules.retention.models import DeletionRequest

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors
REASONS = {
    "cancellation_internal_reason": "Private internal basis",
    "cancellation_customer_reason": "Explanation for customer <script>unsafe()</script>",
}


def cancel(auth, actors, **changes):
    return post(
        auth,
        f"/api/admin/orders/{actors.order.id}/status",
        {"status": "cancelled", **REASONS, **changes},
    )


@pytest.fixture
def admin(auth, actors):
    login_admin(auth, actors)
    auth.disk = auth.app.state.yandex_disk = MemoryDisk()
    return auth


def bind(auth, actors):
    response = post(auth, f"/api/admin/orders/{actors.order.id}/folder")
    assert response.status_code == 200
    return auth.db.get(DiskFolder, response.json()["id"])


@pytest.mark.parametrize("field", list(REASONS))
@pytest.mark.parametrize("invalid", [None, "", " \t\n"])
def test_invalid_cancellation_preserves_status_and_history(admin, actors, field, invalid):
    assert cancel(admin, actors, **{field: invalid}).status_code == 422
    assert actors.order.status == OrderStatus.AWAITING_AGREEMENT
    assert actors.order.closed_at is None
    assert admin.db.scalar(select(func.count()).select_from(OrderEvent)) == 0
    assert admin.db.scalar(select(func.count()).select_from(DeletionRequest)) == 0


def test_cancellation_without_new_fields_is_rejected(admin, actors):
    assert (
        post(
            admin, f"/api/admin/orders/{actors.order.id}/status", {"status": "cancelled"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("folder_state", ["absent", "live", "deleted"])
def test_cancellation_projects_reasons_and_preserves_disk_access(
    admin, actors, folder_state, caplog
):
    folder = bind(admin, actors) if folder_state != "absent" else None
    if folder:
        folder.folder_url = "https://disk.yandex.ru/invite/synthetic"
        approve(admin, actors)
        if folder_state == "deleted":
            folder.deleted_at = datetime.now(UTC)
        admin.db.commit()
    response = cancel(admin, actors)
    assert response.status_code == 200, response.text
    assert response.json().items() >= REASONS.items()
    assert response.json()["closed_at"]
    for url in ["/api/admin/orders", f"/api/admin/orders/{actors.order.id}"]:
        data = admin.client.get(url).json()
        row = (
            next(x for x in data if x["id"] == str(actors.order.id))
            if isinstance(data, list)
            else data
        )
        assert row.items() >= REASONS.items()
    item = admin.db.scalar(
        select(DeletionRequest).where(DeletionRequest.order_id == actors.order.id)
    )
    if folder_state == "live":
        assert item and item.reason.value == "order_cancelled" and item.status.value == "waiting"
        assert item.due_at <= actors.order.closed_at
    else:
        assert item is None
    assert not any(call[0] == "delete" for call in admin.disk.calls)
    assert cancel(admin, actors, cancellation_internal_reason="Replaced").status_code == 409
    assert actors.order.cancellation_internal_reason == REASONS["cancellation_internal_reason"]
    cancelled = admin.db.scalars(
        select(OrderEvent).where(OrderEvent.event_type == "status_cancelled")
    ).all()
    assert len(cancelled) == 1 and cancelled[0].actor_admin_id == actors.admin.id
    assert "Private" not in str(admin.db.scalars(select(Notification.payload)).all())
    admin.client.cookies.clear()
    login_customer(admin)
    for url in ["/api/customer/orders", f"/api/customer/orders/{actors.order.id}"]:
        response = admin.client.get(url)
        assert response.status_code == 200
        assert (
            "cancellation_internal_reason" not in response.text
            and "Private internal basis" not in response.text
        )
        data = response.json()
        row = data[0] if isinstance(data, list) else data
        assert row["cancellation_customer_reason"] == REASONS["cancellation_customer_reason"]
    assert admin.client.get(f"/api/customer/orders/{actors.other_order.id}").status_code == 404
    folder_response = admin.client.get(f"/api/customer/orders/{actors.order.id}/folder")
    if folder_state == "live":
        assert folder_response.json()["folder_url"] == "https://disk.yandex.ru/invite/synthetic"
    elif folder_state == "deleted":
        assert (
            folder_response.status_code == 404 or folder_response.json().get("folder_url") is None
        )
    assert cancel(admin, actors).status_code == 403
    assert "Private internal basis" not in caplog.text
    assert "Explanation for customer" not in caplog.text


def test_historical_cancelled_order_remains_readable(admin, actors):
    actors.order.status = OrderStatus.CANCELLED
    actors.order.closed_at = datetime.now(UTC)
    admin.db.commit()
    assert (
        admin.client.get(f"/api/admin/orders/{actors.order.id}").json()[
            "cancellation_internal_reason"
        ]
        is None
    )
    admin.client.cookies.clear()
    login_customer(admin)
    response = admin.client.get(f"/api/customer/orders/{actors.order.id}")
    assert response.status_code == 200
    assert response.json()["cancellation_customer_reason"] is None
    assert "cancellation_internal_reason" not in response.json()


def test_cancellation_request_failure_rolls_back_whole_transition(admin, actors):
    bind(admin, actors)

    def fail_request(mapper, connection, target):
        raise RuntimeError("synthetic request write failure")

    event.listen(DeletionRequest, "before_insert", fail_request)
    try:
        assert cancel(admin, actors).status_code == 500
    finally:
        event.remove(DeletionRequest, "before_insert", fail_request)
        admin.db.rollback()
    admin.db.expire_all()
    order = admin.db.get(Order, actors.order.id)
    assert order.status == OrderStatus.AWAITING_AGREEMENT
    assert order.closed_at is None and order.cancellation_internal_reason is None
    assert admin.db.scalar(select(func.count()).select_from(DeletionRequest)) == 0
    assert (
        admin.db.scalar(
            select(func.count())
            .select_from(OrderEvent)
            .where(OrderEvent.event_type == "status_cancelled")
        )
        == 0
    )


def test_service_also_rejects_cancellation_without_reasons(admin, actors):
    with pytest.raises(HTTPException) as caught:
        transition(admin.db, actors.order, OrderStatus.CANCELLED, actors.admin.id)
    assert caught.value.status_code == 422
    assert actors.order.status == OrderStatus.AWAITING_AGREEMENT


def test_cancelled_request_can_be_deferred_and_deleted_only_explicitly(admin, actors):
    bind(admin, actors)
    assert cancel(admin, actors).status_code == 200
    item = admin.db.scalar(select(DeletionRequest))
    now = datetime.now(UTC)
    assert notifications.queue_deletion_reminders(admin.db, now=now) == 1
    assert notifications.queue_deletion_reminders(admin.db, now=now) == 0
    payloads = admin.db.scalars(select(Notification.payload)).all()
    assert "Private internal basis" not in str(payloads)
    telegram = Telegram()
    job = admin.db.scalar(select(Notification))
    assert notifications.deliver_one(
        admin.db,
        admin.settings,
        job.id,
        auth_mailer=admin.mailer,
        order_mailer=admin.app.state.order_mailer,
        mailer=admin.app.state.notification_mailer,
        telegram=telegram,
        force=True,
    )
    assert len(telegram.messages) == 1
    assert "Private internal basis" not in telegram.messages[0]
    assert "Explanation for customer" not in telegram.messages[0]
    assert not any(call[0] == "delete" for call in admin.disk.calls)

    retention.defer(
        admin.db,
        actors.order.id,
        item.id,
        actors.admin.id,
        now + timedelta(days=2),
        "Review requested",
    )
    assert not any(call[0] == "delete" for call in admin.disk.calls)
    assert retention.process_due(admin.db, now=now + timedelta(days=3)) == 1
    assert item.status.value == "waiting"
    item.deferred_until = now - timedelta(seconds=1)
    admin.db.commit()
    confirmed = post(
        admin,
        f"/api/admin/orders/{actors.order.id}/deletion-request/confirm",
        {"confirm": True, "deletion_request_id": str(item.id)},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert not any(call[0] == "delete" for call in admin.disk.calls)
    deleted = post(
        admin,
        f"/api/admin/orders/{actors.order.id}/folder/delete",
        {"confirm": True, "deletion_request_id": str(item.id)},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"]
    assert sum(call[0] == "delete" for call in admin.disk.calls) == 1


def test_cancellation_preserves_csrf_and_origin_protection(admin, actors):
    url = f"/api/admin/orders/{actors.order.id}/status"
    body = {"status": "cancelled", **REASONS}
    assert admin.client.post(url, json=body).status_code == 403
    csrf = admin.client.get("/api/auth/csrf").json()["csrf_token"]
    assert (
        admin.client.post(
            url,
            json=body,
            headers={
                "Origin": "https://foreign.example",
                "X-CSRF-Token": csrf,
            },
        ).status_code
        == 403
    )
    assert actors.order.status == OrderStatus.AWAITING_AGREEMENT


def test_cancellation_preserves_existing_open_request(admin, actors):
    bind(admin, actors)
    now = datetime.now(UTC)
    item = DeletionRequest(
        order_id=actors.order.id,
        reason="order_cancelled",
        status="deferred",
        due_at=now,
        deferred_until=now + timedelta(days=1),
        admin_note="Review",
    )
    admin.db.add(item)
    admin.db.commit()
    request_id = item.id
    assert cancel(admin, actors).status_code == 200
    assert item.id == request_id and item.status.value == "deferred"
    assert item.admin_note == "Review"
    assert admin.db.scalar(select(func.count()).select_from(DeletionRequest)) == 1

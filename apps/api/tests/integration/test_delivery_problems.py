from datetime import UTC, datetime, timedelta

import pytest
import test_notifications as helpers
from test_auth import login_admin, login_customer, post

from sinegor.modules.notifications import service
from sinegor.modules.notifications.models import Notification

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors
channels = helpers.channels
BASE = "/api/admin/notifications/problems"


def job(channels, kind, *, status="pending", age=timedelta(days=2), **kwargs):
    key = service.enqueue(
        channels.db,
        kind,
        recipient="private@example.ru",
        payload={"phone": "+79991234567"},
        **kwargs,
    )
    item = channels.db.get(Notification, key)
    item.created_at = datetime.now(UTC) - age
    item.status = status
    channels.db.commit()
    return item


def test_warning_event_is_visible_without_consultations(channels, actors):
    item = job(
        channels, "materials_deleted", order_id=actors.order.id, customer_id=actors.customer.id
    )
    login_admin(channels, actors)
    assert channels.client.get("/api/admin/consultations").json() == []
    assert channels.client.get("/api/admin/notifications/summary").json() == [
        {"channel": "smtp", "reason": "delayed", "count": 1}
    ]
    response = channels.client.get(BASE)
    assert response.status_code == 200
    row = response.json()[0]
    assert row["id"] == str(item.id)
    assert row["kind"] == "materials_deleted"
    assert row["reason"] == "delayed" and row["status"] == "pending"
    assert row["attempts"] == 0 and row["error_code"] is None
    assert row["order_id"] == str(actors.order.id)
    assert row["customer_id"] == str(actors.customer.id)
    assert response.headers["cache-control"] == "no-store"
    assert "private@example.ru" not in response.text and "+79991234567" not in response.text


def test_problem_view_is_admin_only_and_filters_unsafe_errors(channels, actors):
    item = job(channels, "invitation", status="failed")
    item.last_error_code = "private provider response"
    channels.db.commit()
    assert channels.client.get(BASE).status_code == 401
    login_customer(channels, actors.customer.email)
    assert channels.client.get(BASE).status_code == 403
    login_admin(channels, actors)
    response = channels.client.get(BASE)
    assert response.status_code == 200
    assert response.json()[0]["error_code"] is None
    assert "private provider response" not in response.text
    assert channels.client.get(BASE + "?limit=0").status_code == 422
    assert channels.client.get(BASE + "?offset=-1").status_code == 422


def test_summary_and_paginated_problems_share_channels_reasons_and_boundaries(channels):
    from sinegor.modules.notifications.problems import list_delivery_problems

    now = datetime.now(UTC)
    cases = [
        ("materials_deleted", "pending", timedelta(hours=24), None),
        ("consultation", "pending", timedelta(hours=24) - timedelta(microseconds=1), None),
        ("consultation_telegram", "failed", timedelta(), "telegram_permanent"),
        ("invitation", "expired", timedelta(days=8), "smtp_failed"),
        ("customer_blocked", "pending", timedelta(), "smtp_failed"),
        ("consultation", "pending", timedelta(days=3), "smtp_failed"),
        ("magic_link", "sent", timedelta(days=4), None),
        ("invitation", "cancelled", timedelta(days=4), None),
    ]
    items = []
    for kind, status, age, code in cases:
        item = job(channels, kind, status=status)
        item.created_at = now - age
        item.last_error_code = code
        items.append(item)
    channels.db.commit()
    rows = list_delivery_problems(channels.db, now=now)
    assert {row["id"] for row in rows} == {items[i].id for i in [0, 2, 3, 4, 5]}
    assert service.delivery_summary(channels.db, now=now) == [
        {"channel": "smtp", "reason": "delayed", "count": 1},
        {"channel": "smtp", "reason": "expired", "count": 2},
        {"channel": "smtp", "reason": "temporary", "count": 1},
        {"channel": "telegram", "reason": "permanent", "count": 1},
    ]
    assert [row["id"] for row in rows] == [
        row["id"]
        for start in range(0, 6, 2)
        for row in list_delivery_problems(channels.db, now=now, limit=2, offset=start)
    ]
    assert list_delivery_problems(channels.db, now=now, offset=10) == []
    for item in items:
        item.status = "sent"
    channels.db.commit()
    assert list_delivery_problems(channels.db, now=now) == []
    assert service.delivery_summary(channels.db, now=now) == []


def test_handling_or_delivering_consultation_clears_both_views(channels, actors):
    item = job(channels, "consultation", status="failed")
    item.last_error_code = "smtp_permanent"
    channels.db.commit()
    login_admin(channels, actors)
    assert channels.client.get(BASE).status_code == 200
    assert len(channels.client.get(BASE).json()) == 1
    assert (
        post(
            channels, f"/api/admin/consultations/{item.id}/handle", {"confirmed": True}
        ).status_code
        == 200
    )
    assert channels.client.get(BASE).json() == []
    assert channels.client.get("/api/admin/notifications/summary").json() == []
    other = job(channels, "consultation")
    assert len(channels.client.get(BASE).json()) == 1
    assert helpers.process(channels) == 1
    channels.db.refresh(other)
    assert other.status == "sent"
    assert channels.client.get(BASE).json() == []
    assert channels.client.get("/api/admin/notifications/summary").json() == []

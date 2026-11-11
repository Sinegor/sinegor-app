"""Security facts are independent of order history and contain no credentials."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_auth as helpers
from sqlalchemy import select
from test_auth import PASSWORD, login_admin, login_customer, post

from sinegor.modules.security_events.models import SecurityEvent

pytestmark = pytest.mark.integration
auth = helpers.auth
actors = helpers.actors


def test_security_journal_exists_and_requires_admin(auth, actors):
    assert auth.client.get("/api/admin/security-events").status_code == 401
    login_admin(auth, actors)
    response = auth.client.get("/api/admin/security-events")
    assert response.status_code == 200
    assert any(row["event_type"] == "authentication" for row in response.json())


def events(auth):
    return auth.db.scalars(select(SecurityEvent).order_by(SecurityEvent.recorded_at)).all()


def test_failed_login_does_not_trust_email_or_collect_secrets(auth, actors, caplog):
    response = post(
        auth,
        "/api/auth/admin/login",
        {
            "email": actors.admin.email,
            "password": "wrong-password-marker",
            "code": "123456",
        },
    )
    assert response.status_code == 401
    row = events(auth)[-1]
    assert (row.event_type, row.result, row.reason_code) == (
        "authentication",
        "failure",
        "invalid_credentials",
    )
    assert row.user_id is None and row.user_role is None
    assert row.request_id == response.headers["X-Request-ID"]
    for secret in [actors.admin.email, "wrong-password-marker", "123456"]:
        assert secret not in repr(row.__dict__)
        assert secret not in caplog.text
    login_admin(auth, actors)
    row = next(row for row in events(auth) if row.reason_code == "admin_login")
    assert row.user_id == actors.admin.id and row.user_role == "admin"
    assert row.recorded_at.utcoffset() == timedelta(0)


def test_customer_cannot_read_and_denied_order_does_not_disclose_target(auth, actors):
    token = login_customer(auth)
    response = auth.client.get("/api/admin/security-events")
    assert response.status_code == 403
    row = events(auth)[-1]
    assert (row.reason_code, row.user_id) == ("admin_required", actors.customer.id)
    assert row.request_id == response.headers["X-Request-ID"]
    response = auth.client.get(f"/api/customer/orders/{actors.other_order.id}")
    assert response.status_code == 404
    assert events(auth)[-1].reason_code == "order_not_owned"
    assert token not in repr([r.__dict__ for r in events(auth)])
    assert auth.client.post("/api/auth/logout", json={"token": token}).status_code == 403
    assert events(auth)[-1].reason_code == "csrf_failed"
    assert events(auth)[-1].user_id is None
    assert post(auth, "/api/auth/logout").status_code == 204
    assert events(auth)[-1].reason_code == "logout"
    assert auth.client.get("/api/auth/session").status_code == 401
    assert events(auth)[-1].reason_code == "authentication_required"


def test_rate_limit_and_malformed_login_are_recorded_without_identity(auth, actors):
    for _ in range(auth.settings.auth_account_limit):
        assert post(
            auth,
            "/api/auth/admin/login",
            {
                "email": actors.admin.email,
                "password": PASSWORD,
                "code": "000000",
            },
        ).status_code in (204, 401)
    response = post(
        auth,
        "/api/auth/admin/login",
        {
            "email": actors.admin.email,
            "password": PASSWORD,
            "code": "000000",
        },
    )
    assert response.status_code == 429
    assert events(auth)[-1].reason_code == "attempt_limit"
    assert events(auth)[-1].user_id is None
    response = post(auth, "/api/auth/admin/login", {"email": actors.admin.email})
    assert response.status_code == 422
    assert events(auth)[-1].reason_code == "invalid_request"


def test_credentials_issue_replace_consume_and_email_revocation(auth, actors):
    for _ in range(2):
        assert (
            post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email}).status_code
            == 202
        )
    raw = auth.mailer.token()
    assert post(auth, "/api/auth/magic-link/verify", {"token": raw}).status_code == 204
    assert post(auth, "/api/auth/magic-link/verify", {"token": raw}).status_code == 401
    assert events(auth)[-1].user_id is None
    reasons = [row.reason_code for row in events(auth)]
    assert reasons.count("magic_link_issued") == 2
    assert "link_replaced" in reasons and "link_consumed" in reasons
    assert "magic_link_login" in reasons and "session_created" in reasons
    login_admin(auth, actors)
    csrf = auth.client.get("/api/auth/csrf").json()["csrf_token"]
    response = auth.client.patch(
        f"/api/admin/customers/{actors.customer.id}",
        json={"email": "updated@example.ru", "display_name": "Иван Петров"},
        headers={"Origin": str(auth.settings.public_origin).rstrip("/"), "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    row = events(auth)[-1]
    assert (row.reason_code, row.user_id, row.subject_user_id) == (
        "email_changed",
        actors.admin.id,
        actors.customer.id,
    )


def test_filter_pagination_and_read_only_methods(auth, actors):
    login_admin(auth, actors)
    first, second = uuid4(), uuid4()
    for identifier, stamp, kind, reason in [
        (first, datetime(2026, 1, 1, tzinfo=UTC), "access_denied", "csrf_failed"),
        (second, datetime(2026, 1, 2, tzinfo=UTC), "authentication", "admin_login"),
    ]:
        auth.db.add(
            SecurityEvent(
                id=identifier,
                recorded_at=stamp,
                event_type=kind,
                reason_code=reason,
                result="failure",
                request_id=uuid4().hex,
            )
        )
    auth.db.commit()
    url = "/api/admin/security-events"
    rows = auth.client.get(
        url,
        params={
            "date_from": "2026-01-01",
            "date_to": "2026-01-01",
            "event_type": "access_denied",
        },
    ).json()
    assert [r["id"] for r in rows] == [str(first)]
    assert (
        auth.client.get(
            url, params={"date_from": "2026-01-02", "date_to": "2026-01-01"}
        ).status_code
        == 422
    )
    for params in [
        {"limit": 101},
        {"offset": -1},
        {"event_type": "private-text"},
        {"date_from": "bad"},
    ]:
        assert auth.client.get(url, params=params).status_code == 422
    all_rows = auth.client.get(url).json()
    assert auth.client.get(url, params={"limit": 1, "offset": 1}).json() == all_rows[1:2]
    for method in ["POST", "PATCH", "DELETE", "PUT"]:
        csrf = auth.client.get("/api/auth/csrf").json()["csrf_token"]
        assert (
            auth.client.request(
                method,
                url,
                headers={
                    "Origin": str(auth.settings.public_origin).rstrip("/"),
                    "X-CSRF-Token": csrf,
                },
            ).status_code
            == 405
        )


def test_email_request_identifies_subject_but_does_not_authenticate_requester(auth, actors):
    response = post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email})
    assert response.status_code == 202
    row = events(auth)[-1]
    assert row.reason_code == "magic_link_issued"
    assert row.user_id is None and row.user_role is None
    assert row.subject_user_id == actors.customer.id
    assert row.request_id == response.headers["X-Request-ID"]


def test_failed_delivery_revokes_created_link_and_keeps_security_facts(auth, actors):
    auth.mailer.fail = True
    response = post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email})
    assert response.status_code == 202
    rows = events(auth)
    assert [row.reason_code for row in rows] == ["magic_link_issued", "delivery_failed"]
    assert all(row.user_id is None and row.subject_user_id == actors.customer.id for row in rows)
    assert all(row.request_id == response.headers["X-Request-ID"] for row in rows)


def test_admin_invitation_keeps_verified_actor_and_target_separate(auth, actors):
    login_admin(auth, actors)
    response = post(auth, f"/api/admin/customers/{actors.customer.id}/invite")
    assert response.status_code == 202
    row = next(r for r in reversed(events(auth)) if r.reason_code == "invitation_issued")
    assert row.user_id == actors.admin.id and row.user_role == "admin"
    assert row.subject_user_id == actors.customer.id
    assert row.request_id == response.headers["X-Request-ID"]


def test_admin_link_replacement_and_delivery_revocation_keep_actor(auth, actors):
    login_admin(auth, actors)
    url = f"/api/admin/customers/{actors.customer.id}/invite"
    for _ in range(2):
        assert post(auth, url).status_code == 202
    row = next(r for r in reversed(events(auth)) if r.reason_code == "link_replaced")
    assert row.user_id == actors.admin.id and row.subject_user_id == actors.customer.id
    auth.mailer.fail = True
    assert post(auth, url).status_code == 503
    row = next(r for r in reversed(events(auth)) if r.reason_code == "delivery_failed")
    assert row.user_id == actors.admin.id and row.subject_user_id == actors.customer.id


def test_customer_folder_agreement_access_gate_is_journaled(auth, actors):
    login_customer(auth)
    response = auth.client.get(f"/api/customer/orders/{actors.order.id}/folder")
    assert response.status_code == 404
    row = events(auth)[-1]
    assert row.reason_code == "agreement_required" and row.user_id == actors.customer.id
    assert row.request_id == response.headers["X-Request-ID"]

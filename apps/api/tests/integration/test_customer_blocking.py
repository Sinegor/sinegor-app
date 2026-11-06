"""Blocking revokes access; unblocking never resurrects a credential."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from sinegor.db.types import TokenPurpose
from sinegor.modules.auth.models import AuthToken, Session
from sinegor.modules.auth.security import new_secret, secret_hash
from sinegor.modules.notifications.models import Notification
from sinegor.modules.security_events.models import SecurityEvent
from tests.integration.test_auth import actors as actors_fixture
from tests.integration.test_auth import auth as auth_fixture
from tests.integration.test_auth import login_admin, login_customer, post

auth = auth_fixture
actors = actors_fixture

pytestmark = pytest.mark.integration


def block(auth, actors, reason="Причина <script>alert(1)</script>", comment="Только исполнителю"):
    return post(
        auth,
        f"/api/admin/customers/{actors.customer.id}/block",
        {
            "reason": reason,
            "internal_comment": comment,
        },
    )


def test_block_revokes_all_access_and_unblock_requires_new_link(auth, actors):
    login_customer(auth)
    cookie = auth.client.cookies.get(auth.settings.session_cookie_name)
    raws = [new_secret(), new_secret()]
    now = datetime.now(UTC)
    for raw, purpose in zip(raws, TokenPurpose, strict=True):
        auth.db.add(
            AuthToken(
                customer_id=actors.customer.id,
                token_hash=secret_hash(raw),
                purpose=purpose,
                created_at=now,
                expires_at=now + timedelta(minutes=15),
            )
        )
    auth.db.commit()
    login_admin(auth, actors)
    admin_cookie = auth.client.cookies.get(auth.settings.session_cookie_name)
    response = block(auth, actors)
    assert response.status_code == 200, response.text
    assert response.json()["blocked_at"]
    assert response.json()["block_comment"] == "Только исполнителю"
    session = auth.db.scalar(select(Session).where(Session.session_hash == secret_hash(cookie)))
    assert session.revoked_at
    assert (
        auth.db.scalar(
            select(func.count())
            .select_from(AuthToken)
            .where(AuthToken.customer_id == actors.customer.id, AuthToken.used_at.is_(None))
        )
        == 0
    )
    assert post(auth, f"/api/admin/customers/{actors.customer.id}/invite").status_code == 409
    count = len(auth.mailer.messages)
    response = post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email})
    assert response.status_code == 202
    assert len(auth.mailer.messages) == count
    auth.client.cookies.set(auth.settings.session_cookie_name, cookie)
    assert auth.client.get("/api/customer/orders").status_code == 401
    for raw in raws:
        assert post(auth, "/api/auth/magic-link/verify", {"token": raw}).status_code == 401
    auth.client.cookies.set(auth.settings.session_cookie_name, admin_cookie)
    response = post(auth, f"/api/admin/customers/{actors.customer.id}/unblock")
    assert response.status_code == 200
    assert response.json()["blocked_at"] is None
    assert response.json()["block_reason"] is None
    assert response.json()["block_comment"] is None
    auth.client.cookies.set(auth.settings.session_cookie_name, cookie)
    assert auth.client.get("/api/customer/orders").status_code == 401
    for raw in raws:
        assert post(auth, "/api/auth/magic-link/verify", {"token": raw}).status_code == 401
    auth.client.cookies.clear()
    login_customer(auth)
    assert auth.client.get("/api/customer/orders").status_code == 200
    auth.db.expire_all()
    assert actors.order.status.value == "awaiting_agreement"
    events = auth.db.scalars(
        select(SecurityEvent).where(
            SecurityEvent.event_type == "privilege_changed",
            SecurityEvent.reason_code.in_(["customer_blocked", "customer_unblocked"]),
        )
    ).all()
    assert len(events) == 2
    assert all(
        e.user_id == actors.admin.id and e.subject_user_id == actors.customer.id for e in events
    )
    assert "Только исполнителю" not in repr([e.__dict__ for e in events])


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"reason": "  "},
        {"reason": "x" * 2001},
        {"reason": "ok", "internal_comment": "x" * 2001},
    ],
)
def test_block_requires_valid_reason(auth, actors, payload):
    login_admin(auth, actors)
    assert (
        post(auth, f"/api/admin/customers/{actors.customer.id}/block", payload).status_code == 422
    )


def test_block_idempotent_and_authorized(auth, actors):
    path = f"/api/admin/customers/{actors.customer.id}"
    assert post(auth, path + "/block", {"reason": "reason"}).status_code == 401
    login_customer(auth)
    assert block(auth, actors).status_code == 403
    assert post(auth, path + "/unblock").status_code == 403
    login_admin(auth, actors)
    first = block(auth, actors).json()
    second = block(auth, actors, "replacement").json()
    assert first == second
    assert (
        auth.db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.kind == "customer_blocked")
        )
        == 1
    )
    jobs = auth.db.scalars(
        select(Notification).where(Notification.kind == "customer_blocked")
    ).all()
    assert "Причина" not in repr([j.payload for j in jobs])
    assert "Только исполнителю" not in repr([j.__dict__ for j in jobs])


def test_access_emails_use_only_active_reason_and_smtp_failure_is_visible(
    auth, actors, monkeypatch
):
    from sinegor.integrations.email.smtp import MailDeliveryError, SMTPAuthMailer
    from sinegor.modules.notifications.service import deliver_one

    mailer = SMTPAuthMailer(auth.settings)
    messages = []
    failing = [True]

    def send(message):
        if failing[0]:
            raise MailDeliveryError()
        messages.append(message)

    monkeypatch.setattr(mailer, "_send", send)
    auth.app.state.notification_mailer = mailer
    login_admin(auth, actors)
    assert block(auth, actors).status_code == 200
    summary = auth.client.get("/api/admin/notifications/summary").json()
    assert {"channel": "smtp", "reason": "temporary", "count": 1} in summary
    item = auth.db.scalar(select(Notification).where(Notification.kind == "customer_blocked"))
    assert item.status == "pending" and item.last_error_code == "smtp_failed"
    failing[0] = False
    assert deliver_one(
        auth.db,
        auth.settings,
        item.id,
        auth_mailer=auth.mailer,
        order_mailer=mailer,
        mailer=mailer,
        telegram=None,
        force=True,
    )
    body = messages[0].get_content()
    assert "Причина <script>alert(1)</script>" in body
    assert "Только исполнителю" not in body
    assert messages[0].get_content_type() == "text/plain"
    assert item.payload == {} and item.recipient is None
    assert post(auth, f"/api/admin/customers/{actors.customer.id}/unblock").status_code == 200
    assert "новую одноразовую ссылку" in messages[-1].get_content()
    assert "Причина" not in messages[-1].get_content()
    assert "Только исполнителю" not in messages[-1].as_string()


def test_unblock_cancels_failed_block_notice_and_clears_texts(auth, actors):
    login_admin(auth, actors)
    assert block(auth, actors).status_code == 200
    item = auth.db.scalar(select(Notification).where(Notification.kind == "customer_blocked"))
    assert item.status == "failed"  # SMTP is intentionally unconfigured.
    assert post(auth, f"/api/admin/customers/{actors.customer.id}/unblock").status_code == 200
    auth.db.refresh(item)
    assert item.status == "cancelled" and item.payload == {} and item.recipient is None
    assert actors.customer.block_reason is None and actors.customer.block_comment is None


@pytest.mark.parametrize("unblock_during_upload", [False, True])
def test_upload_rechecks_revoked_access_after_receiving_pdf(
    auth, actors, tmp_path, monkeypatch, unblock_during_upload
):
    from sinegor.modules.agreements import router as agreement_router
    from sinegor.modules.agreements.models import Agreement
    from sinegor.modules.customers.access import change_access
    from sinegor.modules.customers.models import Customer
    from tests.integration.test_agreements import api as api_fixture
    from tests.integration.test_agreements import pdf

    # Use the existing real PDF exchange fixture; its authentication stays real.
    api = api_fixture.__wrapped__(auth, actors, tmp_path)
    assert api.upload("admin", pdf("initial"), 0).status_code == 200
    before = sorted((p.name, p.read_bytes()) for p in api.storage.root.glob("*.pdf"))
    original = agreement_router.pdf_body

    async def delayed_body(request):
        data = await original(request)
        customer = auth.db.scalar(
            select(Customer).where(Customer.id == actors.customer.id).with_for_update()
        )
        change_access(auth.db, customer, actors.admin.id, reason="Синтетическая причина")
        if unblock_during_upload:
            customer = auth.db.scalar(
                select(Customer).where(Customer.id == actors.customer.id).with_for_update()
            )
            change_access(auth.db, customer, actors.admin.id)
        return data

    monkeypatch.setattr(agreement_router, "pdf_body", delayed_body)
    response = api.upload("customer", pdf("returned"), 1)
    assert response.status_code == 401, response.text
    agreement = auth.db.scalar(select(Agreement).where(Agreement.order_id == actors.order.id))
    assert agreement.revision == 1 and agreement.returned_pdf_key is None
    after = sorted((p.name, p.read_bytes()) for p in api.storage.root.glob("*.pdf"))
    assert after == before


@pytest.mark.parametrize("failure", ["journal", "outbox"])
def test_block_and_revocation_rollback_together(auth, actors, monkeypatch, failure):
    from sinegor.modules.customers import access
    from sinegor.modules.customers.models import Customer

    now = datetime.now(UTC)
    raw = new_secret()
    auth.db.add(
        Session(
            customer_id=actors.customer.id,
            session_hash=secret_hash(raw),
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )
    )
    auth.db.commit()

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic atomicity failure")

    monkeypatch.setattr(access, "record" if failure == "journal" else "enqueue", fail)
    customer = auth.db.scalar(
        select(Customer).where(Customer.id == actors.customer.id).with_for_update(key_share=True)
    )
    with pytest.raises(RuntimeError):
        access.change_access(auth.db, customer, actors.admin.id, reason="Синтетическая причина")
    auth.db.rollback()
    auth.db.refresh(customer)
    assert customer.blocked_at is None and customer.block_reason is None
    assert (
        auth.db.scalar(select(Session).where(Session.session_hash == secret_hash(raw))).revoked_at
        is None
    )
    assert not auth.db.scalars(
        select(SecurityEvent).where(SecurityEvent.reason_code == "customer_blocked")
    ).all()
    assert not auth.db.scalars(
        select(Notification).where(Notification.kind == "customer_blocked")
    ).all()

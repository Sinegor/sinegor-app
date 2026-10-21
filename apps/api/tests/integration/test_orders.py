from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_auth as auth_helpers
from sqlalchemy import func, select
from test_auth import login_admin, login_customer, post

from sinegor.db.types import AgreementStatus, OrderStatus, TokenPurpose
from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.modules.agreements.models import Agreement
from sinegor.modules.audit.models import CustomerEvent, OrderEvent
from sinegor.modules.auth.models import AuthToken, Session
from sinegor.modules.auth.security import new_secret, secret_hash
from sinegor.modules.customers.models import Customer
from sinegor.modules.orders.service import process_lifecycle

pytestmark = pytest.mark.integration
auth = auth_helpers.auth
actors = auth_helpers.actors


class ResultMailer:
    fail = False

    def __init__(self):
        self.messages = []

    def send_result_ready(self, recipient, number):
        if self.fail:
            raise MailDeliveryError("simulated failure")
        self.messages.append((recipient, number))


@pytest.fixture
def admin(auth, actors):
    login_admin(auth, actors)
    auth.app.state.order_mailer = ResultMailer()
    return auth


def mutate(auth, method, path, body):
    csrf = auth.client.get("/api/auth/csrf").json()["csrf_token"]
    return auth.client.request(
        method, path, json=body, headers={"Origin": "http://testserver", "X-CSRF-Token": csrf}
    )


def approve(auth, actors, order=None):
    order = order or actors.order
    agreement = Agreement(
        order_id=order.id,
        status=AgreementStatus.APPROVED,
        final_pdf_key="private/final.pdf",
        final_sha256="a" * 64,
        verified_at=datetime.now(UTC),
        verified_by_id=actors.admin.id,
    )
    auth.db.add(agreement)
    auth.db.commit()
    return agreement


def status(auth, order, target, **extra):
    return post(auth, f"/api/admin/orders/{order.id}/status", {"status": target, **extra})


def test_customer_cards_and_audit(admin, actors):
    created = post(admin, "/api/admin/customers", {"email": " New@Example.ru ", "phone": "+7"})
    assert created.status_code == 201
    identifier = created.json()["id"]
    path = f"/api/admin/customers/{identifier}"
    assert admin.client.get(path).json()["email"] == "new@example.ru"
    edited = mutate(admin, "PATCH", path, {"display_name": "Updated", "phone": None})
    assert edited.status_code == 200 and edited.json()["phone"] is None
    assert edited.json()["display_name"] == "Updated"
    assert mutate(admin, "PATCH", path, {"email": None}).status_code == 422
    assert mutate(admin, "PATCH", path, {"email": "not-an-email"}).status_code == 422
    assert mutate(admin, "PATCH", path, {"email": actors.customer.email}).status_code == 409
    assert admin.client.get(path).json()["email"] == "new@example.ru"
    events = admin.client.get(path + "/events").json()
    assert sorted(row["event_type"] for row in events) == ["customer_created", "customer_updated"]
    assert admin.db.scalar(select(func.count()).select_from(CustomerEvent)) == 2
    assert len(admin.client.get("/api/admin/customers?limit=1&offset=1").json()) == 1
    assert admin.client.get("/api/admin/customers?limit=101").status_code == 422
    assert admin.client.get(f"/api/admin/customers/{uuid4()}").status_code == 404


def test_email_edit_revokes_old_credentials(admin, actors):
    raw = new_secret()
    now = datetime.now(UTC)
    admin.db.add_all(
        [
            AuthToken(
                customer_id=actors.customer.id,
                token_hash=secret_hash(raw),
                purpose=TokenPurpose.MAGIC_LINK,
                expires_at=now + timedelta(minutes=10),
            ),
            Session(
                customer_id=actors.customer.id,
                session_hash=secret_hash(new_secret()),
                expires_at=now + timedelta(days=1),
            ),
        ]
    )
    admin.db.commit()
    changed = mutate(
        admin,
        "PATCH",
        f"/api/admin/customers/{actors.customer.id}",
        {"email": " CHANGED@Example.RU "},
    )
    assert changed.status_code == 200 and changed.json()["email"] == "changed@example.ru"
    assert (
        admin.db.scalar(select(AuthToken).where(AuthToken.token_hash == secret_hash(raw))) is None
    )
    assert admin.db.scalar(
        select(Session).where(Session.customer_id == actors.customer.id)
    ).revoked_at
    assert post(admin, "/api/auth/magic-link/verify", {"token": raw}).status_code == 401


def test_order_creation_history_terms_and_customer_view(admin, actors):
    payload = {
        "customer_id": str(actors.customer.id),
        "service_type": "technical_preparation",
        "description": "Agreed scope",
        "agreed_price": "1250.50",
    }
    response = post(admin, "/api/admin/orders", payload)
    assert response.status_code == 201, response.text
    created = response.json()
    path = f"/api/admin/orders/{created['id']}"
    assert created["status"] == "awaiting_agreement" and created["agreed_price"] == "1250.50"
    updated = mutate(
        admin, "PUT", path + "/terms", {"service_type": "analysis", "description": "Revised"}
    )
    assert updated.status_code == 200 and updated.json()["agreed_price"] is None
    orders = admin.client.get(f"/api/admin/orders?customer_id={actors.customer.id}").json()
    assert len(orders) == 2 and all(row["customer_id"] == str(actors.customer.id) for row in orders)
    assert admin.client.get("/api/admin/orders?status=completed").json() == []
    assert len(admin.client.get(path + "/events").json()) == 2
    assert admin.client.get(f"/api/admin/orders/{uuid4()}").status_code == 404
    payload["customer_id"] = str(uuid4())
    assert post(admin, "/api/admin/orders", payload).status_code == 404
    login_customer(admin)
    own = admin.client.get(f"/api/customer/orders/{created['id']}").json()
    assert own["description"] == "Revised"
    assert admin.client.get(f"/api/customer/orders/{actors.other_order.id}").status_code == 404
    assert admin.client.get("/api/admin/customers").status_code == 403
    assert admin.client.get(path).status_code == 403
    assert post(admin, path + "/payment", {}).status_code == 403
    assert (
        mutate(
            admin, "PATCH", f"/api/admin/customers/{actors.customer.id}", {"phone": "123"}
        ).status_code
        == 403
    )


def test_legacy_long_description_can_be_read_but_not_submitted(auth, actors):
    description = "x" * 10001
    actors.order.description = description
    auth.db.commit()
    login_customer(auth)
    detail = auth.client.get(f"/api/customer/orders/{actors.order.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["description"] == description
    listing = auth.client.get("/api/customer/orders")
    assert listing.status_code == 200, listing.text
    assert listing.json()[0]["description"] == description
    login_admin(auth, actors)
    detail = auth.client.get(f"/api/admin/orders/{actors.order.id}")
    assert detail.status_code == 200 and detail.json()["description"] == description
    assert auth.client.get("/api/admin/orders").status_code == 200
    assert (
        post(
            auth,
            "/api/admin/orders",
            {
                "customer_id": str(actors.customer.id),
                "service_type": "analysis",
                "description": description,
            },
        ).status_code
        == 422
    )
    assert (
        mutate(
            auth,
            "PUT",
            f"/api/admin/orders/{actors.order.id}/terms",
            {
                "service_type": "analysis",
                "description": description,
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1", "0.001", "10000000000"])
def test_order_rejects_invalid_money(admin, actors, price):
    result = post(
        admin,
        "/api/admin/orders",
        {"customer_id": str(actors.customer.id), "service_type": "analysis", "agreed_price": price},
    )
    assert result.status_code == 422


def test_agreement_guard_skips_and_frozen_terms(admin, actors):
    for target in ("awaiting_materials", "in_progress", "completed"):
        assert status(admin, actors.order, target).status_code == 409
    agreement = Agreement(order_id=actors.order.id, status=AgreementStatus.UNDER_REVIEW)
    admin.db.add(agreement)
    admin.db.commit()
    assert status(admin, actors.order, "awaiting_materials").status_code == 409
    assert (
        mutate(
            admin,
            "PUT",
            f"/api/admin/orders/{actors.order.id}/terms",
            {"service_type": "technical_preparation"},
        ).status_code
        == 409
    )
    assert process_lifecycle(admin.db) == 0
    assert actors.order.status == OrderStatus.AWAITING_AGREEMENT


def test_full_lifecycle_email_failure_and_fourteen_day_boundary(admin, actors):
    agreement = approve(admin, actors)
    assert process_lifecycle(admin.db) == 1
    assert process_lifecycle(admin.db) == 0
    assert actors.order.status == OrderStatus.AWAITING_MATERIALS
    assert status(admin, actors.order, "in_progress").status_code == 200
    assert status(admin, actors.order, "result_ready").status_code == 422
    mailer = admin.app.state.order_mailer
    mailer.fail = True
    response = status(
        admin, actors.order, "result_ready", result_uploaded=True, access_read_only=True
    )
    assert response.status_code == 503
    admin.db.refresh(actors.order)
    assert actors.order.status == OrderStatus.IN_PROGRESS
    assert actors.order.ready_at is None and actors.order.result_notified_at is None
    mailer.fail = False
    response = status(
        admin, actors.order, "result_ready", result_uploaded=True, access_read_only=True
    )
    assert response.status_code == 200, response.text
    assert mailer.messages == [(actors.customer.email, actors.order.number)]
    notification = actors.order.result_notified_at
    assert actors.order.ready_at <= notification
    assert status(admin, actors.order, "completed").status_code == 409
    assert (
        status(
            admin, actors.order, "result_ready", result_uploaded=True, access_read_only=True
        ).status_code
        == 409
    )
    assert len(mailer.messages) == 1
    assert process_lifecycle(admin.db, now=notification + timedelta(days=14, microseconds=-1)) == 0
    assert process_lifecycle(admin.db, now=notification + timedelta(days=14)) == 1
    assert process_lifecycle(admin.db, now=notification + timedelta(days=20)) == 0
    assert actors.order.status == OrderStatus.COMPLETED
    assert actors.order.closed_at == notification + timedelta(days=14)
    assert admin.db.get(Agreement, agreement.id).final_pdf_key == "private/final.pdf"
    events = admin.client.get(f"/api/admin/orders/{actors.order.id}/events").json()
    types = [row["event_type"] for row in events]
    assert types.count("status_completed") == 1
    assert types.count("result_notification_sent") == 1


def test_manual_payment_is_idempotent_and_separate_from_status(admin, actors):
    path = f"/api/admin/orders/{actors.order.id}/payment"
    assert admin.client.get(path).json()["status"] == "unpaid"
    first = post(admin, path, {"note": "Bank transfer received"})
    assert first.status_code == 200, first.text
    assert first.json()["confirmed_by_id"] == str(actors.admin.id)
    assert first.json()["note"] == "Bank transfer received"
    assert post(admin, path, {"note": "retry"}).json() == first.json()
    assert actors.order.status == OrderStatus.AWAITING_AGREEMENT
    assert (
        admin.db.scalar(
            select(func.count())
            .select_from(OrderEvent)
            .where(OrderEvent.event_type == "payment_confirmed")
        )
        == 1
    )


@pytest.mark.parametrize("initial", ["awaiting_agreement", "awaiting_materials", "in_progress"])
def test_cancellation_is_terminal(admin, actors, initial):
    if initial != "awaiting_agreement":
        approve(admin, actors)
        process_lifecycle(admin.db)
        if initial == "in_progress":
            assert status(admin, actors.order, initial).status_code == 200
    assert status(admin, actors.order, "cancelled").status_code == 200
    assert actors.order.closed_at is not None
    assert status(admin, actors.order, "awaiting_materials").status_code == 409
    assert post(admin, f"/api/admin/orders/{actors.order.id}/payment", {}).status_code == 409
    assert process_lifecycle(admin.db) == 0


def test_material_handover_checks_owner_and_does_not_start_work(auth, actors):
    approve(auth, actors)
    process_lifecycle(auth.db)
    login_customer(auth)
    path = f"/api/customer/orders/{actors.order.id}/materials"
    first = post(auth, path, {"note": "All materials uploaded externally"})
    assert first.status_code == 200, first.text
    assert post(auth, path, {}).json() == first.json()
    assert actors.order.status == OrderStatus.AWAITING_MATERIALS
    assert (
        post(auth, f"/api/customer/orders/{actors.other_order.id}/materials", {}).status_code == 404
    )
    login_admin(auth, actors)
    assert auth.client.get(f"/api/admin/orders/{actors.order.id}/materials").json() == first.json()


def test_private_mutations_require_authentication_and_csrf(auth, actors):
    assert (
        post(
            auth,
            "/api/admin/orders",
            {"customer_id": str(actors.customer.id), "service_type": "analysis"},
        ).status_code
        == 401
    )
    assert auth.client.get("/api/admin/customers").status_code == 401
    login_admin(auth, actors)
    assert (
        auth.client.post(f"/api/admin/orders/{actors.order.id}/payment", json={}).status_code == 403
    )
    assert (
        mutate(auth, "PATCH", f"/api/admin/customers/{uuid4()}", {"phone": "123"}).status_code
        == 404
    )


def test_customer_search_covers_fields_and_filters_before_pagination(admin, actors):
    actors.customer.display_name = "Иван Петров"
    actors.customer.phone = "+7 900 123-45-67"
    actors.other.display_name = "Иван Сидоров"
    literal = Customer(email="literal@example.ru", display_name="Code %_ / literal")
    admin.db.add(literal)
    admin.db.commit()
    path = "/api/admin/customers"

    def search(query, **params):
        response = admin.client.get(path, params={"q": query, **params})
        assert response.status_code == 200
        return response.json()

    assert [row["id"] for row in search("  CLIENT@EXAMPLE  ")] == [str(actors.customer.id)]
    assert [row["id"] for row in search("123-45")] == [str(actors.customer.id)]
    matches = search("иван")
    assert {row["id"] for row in matches} == {str(actors.customer.id), str(actors.other.id)}
    assert search("иван", limit=1, offset=0) == matches[:1]
    assert search("иван", limit=1, offset=1) == matches[1:2]
    assert [row["id"] for row in search("%_")] == [str(literal.id)]
    assert search("no-match") == []
    assert len(search(" ")) == 3
    assert admin.client.get(path, params={"q": "a" * 321}).status_code == 422
    login_customer(admin)
    assert admin.client.get(path, params={"q": "иван"}).status_code == 403

import pytest
import test_auth as auth_helpers
import test_orders as order_helpers
from sqlalchemy import func, select
from test_auth import post
from test_orders import mutate

from sinegor.modules.audit.models import CustomerEvent
from sinegor.modules.customers.models import Customer

pytestmark = pytest.mark.integration
auth = auth_helpers.auth
actors = auth_helpers.actors
admin = order_helpers.admin


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"display_name": None},
        {"display_name": ""},
        {"display_name": " \t\n"},
        {"display_name": "\u00a0\u2003"},
    ],
)
def test_create_rejects_missing_name_without_writes_or_invitation(admin, fields):
    before = admin.db.scalar(select(func.count()).select_from(Customer))
    response = post(admin, "/api/admin/customers", {"email": "new@example.ru", **fields})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "customer_name_invalid"
    assert "ФИО заказчика" in response.json()["error"]["message"]
    assert admin.db.scalar(select(func.count()).select_from(Customer)) == before
    assert not admin.mailer.messages


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"email": None},
        {"email": ""},
        {"email": "invalid"},
        {"email": "client@example.ru"},
        {"email": " CLIENT@EXAMPLE.RU "},
    ],
)
def test_create_keeps_email_requirements_and_uniqueness(admin, fields):
    response = post(admin, "/api/admin/customers", {"display_name": "Иван Петров", **fields})
    assert response.status_code == (409 if "@" in (fields.get("email") or "") else 422)


def test_create_valid_customer_and_duplicate_email(admin):
    body = {"email": " New@Example.ru ", "display_name": "Иван Петров"}
    created = post(admin, "/api/admin/customers", body)
    assert created.status_code == 201
    assert created.json()["email"] == "new@example.ru"
    assert created.json()["display_name"] == body["display_name"]
    assert admin.mailer.messages[-1][0] == "new@example.ru"
    assert post(admin, "/api/admin/customers", body).status_code == 409


@pytest.mark.parametrize("original", [None, "", " \t\n"])
@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"phone": "+7"},
        {"email": "changed@example.ru"},
        {"display_name": None},
        {"display_name": ""},
        {"display_name": " \t\n"},
    ],
)
def test_legacy_customer_requires_name_before_any_card_save(admin, actors, original, changes):
    actors.customer.display_name = original
    admin.db.commit()
    path = f"/api/admin/customers/{actors.customer.id}"
    assert admin.client.get(path).json()["display_name"] == original
    before = admin.db.scalar(select(func.count()).select_from(CustomerEvent))
    response = mutate(admin, "PATCH", path, changes)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "customer_name_invalid"
    admin.db.refresh(actors.customer)
    assert actors.customer.display_name == original
    assert actors.customer.email == "client@example.ru" and actors.customer.phone is None
    assert admin.db.scalar(select(func.count()).select_from(CustomerEvent)) == before
    saved = mutate(admin, "PATCH", path, {"display_name": "Иван Петров", "phone": "+7"})
    assert saved.status_code == 200
    assert saved.json()["display_name"] == "Иван Петров"
    assert mutate(admin, "PATCH", path, {"phone": None}).status_code == 200


@pytest.mark.parametrize("name", [None, "", " \t\n"])
def test_existing_customer_name_cannot_be_cleared(admin, actors, name):
    actors.customer.display_name = "Иван Петров"
    admin.db.commit()
    path = f"/api/admin/customers/{actors.customer.id}"
    assert mutate(admin, "PATCH", path, {"display_name": name}).status_code == 422
    assert admin.client.get(path).json()["display_name"] == "Иван Петров"


def test_legacy_customer_other_operations_remain_available(admin, actors):
    path = f"/api/admin/customers/{actors.customer.id}"
    assert actors.customer.display_name is None
    assert admin.client.get("/api/admin/customers").status_code == 200
    assert admin.client.get(path + "/events").status_code == 200
    assert (
        admin.client.get(
            "/api/admin/orders", params={"customer_id": str(actors.customer.id)}
        ).status_code
        == 200
    )
    assert post(admin, path + "/invite").status_code == 202
    assert (
        post(
            admin,
            "/api/admin/orders",
            {"customer_id": str(actors.customer.id), "service_type": "analysis"},
        ).status_code
        == 201
    )
    assert post(admin, path + "/block", {"reason": "Test reason"}).status_code == 200
    assert post(admin, path + "/unblock").status_code == 200
    admin.db.refresh(actors.customer)
    assert actors.customer.display_name is None
    assert Customer.__table__.c.display_name.nullable

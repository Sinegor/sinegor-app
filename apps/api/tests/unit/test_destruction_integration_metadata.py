"""Deletion metadata is a bounded snapshot, never a copy of deleted documents."""

from sinegor.db.models import Customer


def test_customer_snapshot_prefers_existing_fio_and_contains_only_actual_categories():
    from sinegor.modules.destruction.metadata import customer_metadata

    customer = Customer(email="synthetic@example.ru", display_name="Иванов Иван", phone="+7999")
    data = customer_metadata(
        customer,
        categories=["Номер телефона"],
        entity={"customer_id": "synthetic-id"},
        source="customers.phone",
        basis=None,
        method="Очистка поля в PostgreSQL",
        initiator="admin:synthetic",
        executor="FastAPI",
    )
    assert data["subjects"] == [
        {
            "identity": "Иванов Иван",
            "categories": ["Номер телефона"],
            "source": "customers.display_name",
        }
    ]
    assert data["basis"] is None
    assert customer.phone not in str(data)
    assert customer.email not in str(data)


def test_customer_snapshot_without_fio_uses_known_email():
    from sinegor.modules.destruction.metadata import customer_metadata

    customer = Customer(email="synthetic@example.ru")
    data = customer_metadata(
        customer,
        categories=["История заказа"],
        entity={},
        source="orders",
        basis="Истечение срока хранения",
        method="DELETE",
        initiator="scheduler",
        executor="FastAPI",
    )
    assert data["subjects"][0]["identity"] == customer.email
    assert data["subjects"][0]["source"] == "customers.email"

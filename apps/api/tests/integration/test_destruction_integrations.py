"""The seven business deletion paths preserve proof independently of source rows."""

from datetime import UTC, datetime, timedelta

import pytest
import test_business_retention as business_helpers
import test_disk as disk_helpers
import test_notifications as notification_helpers
import test_orders as order_helpers
from sqlalchemy import select
from test_auth import post
from test_orders import mutate

from sinegor.modules.agreements.models import Agreement
from sinegor.modules.agreements.storage import AgreementStorage, AgreementStorageError
from sinegor.modules.notifications import consultations, service
from sinegor.modules.notifications.models import Notification

pytestmark = pytest.mark.integration
auth = notification_helpers.auth
actors = notification_helpers.actors
channels = notification_helpers.channels
admin = disk_helpers.admin
graph = business_helpers.graph


def operations(db, kind):
    from sinegor.modules.destruction.models import DestructionOperation

    return db.scalars(select(DestructionOperation).where(DestructionOperation.kind == kind)).all()


def test_phone_patch_snapshots_fio_and_never_clears_name(admin, actors):
    actors.customer.display_name = "Иванов Иван Иванович"
    actors.customer.phone = "+79991234567"
    admin.db.commit()
    path = f"/api/admin/customers/{actors.customer.id}"
    assert mutate(admin, "PATCH", path, {"phone": None}).status_code == 200
    rows = operations(admin.db, "customer_fields")
    assert len(rows) == 1
    row = rows[0]
    assert row.destroyed_at is not None
    assert row.metadata_json["subjects"] == [
        {
            "identity": "Иванов Иван Иванович",
            "categories": ["Номер телефона"],
            "source": "customers.display_name",
        }
    ]
    assert row.metadata_json["initiator"] == f"admin:{actors.admin.id}"
    assert row.metadata_json["basis"] is None
    assert actors.customer.display_name == "Иванов Иван Иванович"
    assert mutate(admin, "PATCH", path, {"phone": None}).status_code == 200
    assert len(operations(admin.db, "customer_fields")) == 1
    assert mutate(admin, "PATCH", path, {"display_name": None}).status_code == 422
    assert len(operations(admin.db, "customer_fields")) == 1


def consultation_pair(channels):
    identifier = service.enqueue(
        channels.db, "consultation", recipient="known@example.ru", payload={"phone": "+79991234567"}
    )
    partner = service.enqueue(
        channels.db, "consultation_telegram", dedup_key=f"consultation_telegram:{identifier}"
    )
    root = channels.db.get(Notification, identifier)
    root.created_at = datetime.now(UTC) - timedelta(days=8)
    channels.db.commit()
    return root, channels.db.get(Notification, partner)


def test_auto_consultation_cleanup_has_exact_categories_and_real_completion(channels):
    root, partner = consultation_pair(channels)
    future = datetime.now(UTC) + timedelta(days=90)
    consultations.purge_expired_consultations(channels.db, now=future)
    rows = operations(channels.db, "consultation_auto")
    assert len(rows) == 1
    assert rows[0].destroyed_at < future - timedelta(days=80)
    assert rows[0].metadata_json["subjects"] == [
        {
            "identity": "known@example.ru",
            "categories": ["Адрес электронной почты", "Номер телефона"],
            "source": "notifications.recipient",
        }
    ]
    assert root.recipient is None and root.payload == {}
    assert consultations.purge_expired_consultations(channels.db, now=future) == 0
    assert len(operations(channels.db, "consultation_auto")) == 1


def test_manual_consultation_cleanup_attributes_admin_and_pair(channels, actors):
    root, partner = consultation_pair(channels)
    order_helpers.login_admin(channels, actors)
    response = post(channels, f"/api/admin/consultations/{root.id}/handle", {"confirmed": True})
    assert response.status_code == 200
    (row,) = operations(channels.db, "consultation_manual")
    assert row.metadata_json["initiator"] == f"admin:{actors.admin.id}"
    assert set(row.metadata_json["entity"]["notification_ids"].split(",")) == {
        str(root.id),
        str(partner.id),
    }
    assert root.recipient is None and partner.recipient is None
    assert (
        post(
            channels, f"/api/admin/consultations/{root.id}/handle", {"confirmed": True}
        ).status_code
        == 200
    )
    assert len(operations(channels.db, "consultation_manual")) == 1


def test_disk_only_confirms_after_verified_success_and_retries_once(admin, actors):
    actors.customer.display_name = "Заказчик Синтетический"
    disk_helpers.create(admin, actors)
    request = disk_helpers.eligible(admin, actors)
    admin.disk.pending = True
    assert disk_helpers.delete(admin, actors, request).status_code == 202
    (row,) = operations(admin.db, "disk_folder")
    assert row.destroyed_at is None
    admin.disk.status = "success"
    assert disk_helpers.delete(admin, actors, request).status_code == 200
    assert row.destroyed_at is not None
    assert row.metadata_json["subjects"][0]["identity"] == "Заказчик Синтетический"
    assert row.metadata_json["entity"]["resource_id"]
    assert disk_helpers.delete(admin, actors, request).status_code == 200
    assert len(operations(admin.db, "disk_folder")) == 1


def test_uncertain_disk_never_gets_success_documents(admin, actors):
    disk_helpers.create(admin, actors)
    request = disk_helpers.eligible(admin, actors)

    def lost_response(*args):
        from sinegor.integrations.yandex_disk.client import DiskError

        raise DiskError("synthetic timeout")

    admin.disk.delete = lost_response
    assert disk_helpers.delete(admin, actors, request).status_code == 503
    (row,) = operations(admin.db, "disk_folder")
    assert row.destroyed_at is None
    assert row.state in {"error", "uncertain"}


def test_disk_retry_records_administrator_who_confirmed_success(admin, actors):
    from sinegor.modules.disk.service import delete_folder

    disk_helpers.create(admin, actors)
    request = disk_helpers.eligible(admin, actors)
    admin.disk.pending = True
    assert disk_helpers.delete(admin, actors, request).status_code == 202
    admin.disk.status = "success"
    from sinegor.modules.auth.models import AdminUser

    other = AdminUser(email="verifier@example.ru", password_hash="synthetic")
    admin.db.add(other)
    admin.db.commit()
    verifier = other.id
    delete_folder(admin.db, admin.disk, actors.order.id, request.id, verifier)
    (row,) = operations(admin.db, "disk_folder")
    assert row.metadata_json["initiator"] == f"admin:{actors.admin.id}"
    assert row.metadata_json["executor"] == f"FastAPI; admin:{verifier}"


def test_business_documents_outlive_graph_and_wait_for_all_pdf_intents(graph):
    db, storage, _, customer = graph
    customer.display_name = "Удаляемый Заказчик"
    customer.phone = "+79991234567"
    item = business_helpers.order(graph)
    agreement = db.scalar(select(Agreement).where(Agreement.order_id == item.id))
    second_key, _ = storage.put(b"%PDF-second-synthetic")
    agreement.initial_pdf_key = second_key
    db.commit()

    class Broken(AgreementStorage):
        def delete(self, key):
            if key == second_key:
                raise AgreementStorageError("synthetic")
            return super().delete(key)

    result = business_helpers.cleaner(
        db, Broken(storage.root), now=business_helpers.NOW, dry_run=False
    )
    assert result.orders == 1 and result.customers == 1 and result.pending_files == 1
    (agreement_op,) = operations(db, "agreement")
    (history_op,) = operations(db, "order_history")
    (customer_op,) = operations(db, "customer")
    assert agreement_op.destroyed_at is None
    assert history_op.destroyed_at is not None and customer_op.destroyed_at is not None
    assert "файлов" not in history_op.metadata_json["method"]
    assert "файлов" not in customer_op.metadata_json["method"]
    assert history_op.destroyed_at < business_helpers.NOW
    assert customer_op.metadata_json["subjects"][0]["identity"] == "Удаляемый Заказчик"
    assert (
        business_helpers.cleaner(db, storage, now=business_helpers.NOW, dry_run=False).pending_files
        == 0
    )
    assert agreement_op.destroyed_at is not None
    for kind in ("agreement", "order_history", "customer"):
        assert len(operations(db, kind)) == 1


def test_business_commit_failure_rolls_back_prepared_and_confirmed_records(graph, monkeypatch):
    db, storage, _, _ = graph
    business_helpers.order(graph)
    db.commit()
    original = db.commit
    calls = 0

    def broken():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic commit failure")
        original()

    monkeypatch.setattr(db, "commit", broken)
    assert (
        business_helpers.cleaner(db, storage, now=business_helpers.NOW, dry_run=False).failed == 1
    )
    for kind in ("agreement", "order_history", "customer"):
        assert operations(db, kind) == []

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from sinegor.db.models import (
    AdminUser,
    Agreement,
    AuthToken,
    Customer,
    CustomerEvent,
    DeletionRequest,
    DiskFolder,
    MaterialHandover,
    Notification,
    Order,
    OrderEvent,
    PaymentRecord,
    Session,
)
from sinegor.db.session import create_db_engine
from sinegor.db.types import (
    AgreementStatus,
    DeletionReason,
    DeletionStatus,
    OrderStatus,
    ServiceType,
    TokenPurpose,
)
from sinegor.modules.agreements.storage import AgreementStorage, AgreementStorageError
from sinegor.modules.orders.service import locked_order, transition

pytestmark = pytest.mark.integration
NOW = datetime(2032, 3, 1, 12, tzinfo=UTC)
START = datetime(2020, 1, 1, tzinfo=UTC)
DUE = datetime(2027, 3, 1, 12, tzinfo=UTC)


def cleaner(*args, **kwargs):
    from sinegor.modules.retention.business import cleanup_business

    return cleanup_business(*args, **kwargs)


@pytest.fixture
def graph(db_session, tmp_path):
    db_session.expire_on_commit = False
    storage = AgreementStorage(tmp_path / "pdf")
    admin = AdminUser(
        email=f"{uuid4().hex}@example.ru", password_hash="synthetic", created_at=START
    )
    customer = Customer(email=f"{uuid4().hex}@example.ru", created_at=START)
    db_session.add_all([admin, customer])
    db_session.flush()
    return db_session, storage, admin, customer


def order(graph, *, fulfilled=DUE, signed=True, status=OrderStatus.COMPLETED, closed=None):
    db, storage, admin, customer = graph
    item = Order(
        customer_id=customer.id,
        service_type=ServiceType.ANALYSIS,
        created_at=START,
        status=status,
        fulfilled_at=fulfilled,
    )
    if status in {OrderStatus.COMPLETED, OrderStatus.RESULT_READY}:
        item.ready_at = item.result_notified_at = fulfilled or DUE
    if status in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
        item.closed_at = closed or NOW - timedelta(days=1)
    db.add(item)
    db.flush()
    if signed:
        key, digest = storage.put(b"%PDF-synthetic")
        db.add(
            Agreement(
                order_id=item.id,
                status=AgreementStatus.APPROVED,
                final_pdf_key=key,
                final_sha256=digest,
                verified_at=START,
                verified_by_id=admin.id,
                created_at=START,
            )
        )
    db.add(OrderEvent(order_id=item.id, event_type="order_created", actor_admin_id=admin.id))
    db.flush()
    return item


def test_fulfillment_clock_only_after_smtp_success_and_never_moves(graph):
    db, storage, admin, customer = graph
    item = order(graph, fulfilled=None, status=OrderStatus.IN_PROGRESS)

    class Mailer:
        def send_result_ready(self, *args):
            raise RuntimeError("synthetic SMTP failure")

    with pytest.raises(RuntimeError):
        transition(db, item, OrderStatus.RESULT_READY, admin.id, mailer=Mailer())
    assert item.fulfilled_at is None

    class Success:
        def send_result_ready(self, *args):
            pass

    transition(db, item, OrderStatus.RESULT_READY, admin.id, mailer=Success())
    db.flush()
    stamp = item.fulfilled_at
    assert stamp == item.result_notified_at
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE orders SET fulfilled_at = fulfilled_at + interval '1 day' WHERE id = :id"),
            {"id": item.id},
        )
    assert db.get(Order, item.id).fulfilled_at == stamp


def test_exact_five_year_boundary_dry_run_graph_and_other_order(graph):
    db, storage, admin, customer = graph
    expired = order(graph)
    younger = order(graph, fulfilled=DUE + timedelta(microseconds=1))
    key = db.scalar(select(Agreement.final_pdf_key).where(Agreement.order_id == expired.id))
    db.add_all(
        [
            DiskFolder(order_id=expired.id, disk_path="disk:/expired", deleted_at=DUE),
            DeletionRequest(
                order_id=expired.id,
                reason=DeletionReason.RETENTION_EXPIRED,
                status=DeletionStatus.PERFORMED,
                due_at=DUE,
                confirmed_at=DUE,
                confirmed_by_id=admin.id,
                performed_at=DUE,
            ),
            MaterialHandover(order_id=expired.id),
            PaymentRecord(order_id=expired.id),
            Notification(
                kind="materials_deleted",
                order_id=expired.id,
                customer_id=customer.id,
                status="sent",
                payload={},
                recipient=None,
            ),
        ]
    )
    db.commit()
    result = cleaner(db, storage, now=NOW, dry_run=True)
    assert result.orders == 1 and result.customers == 0
    assert db.get(Order, expired.id) is not None and (storage.root / key).exists()
    result = cleaner(db, storage, now=NOW, dry_run=False)
    assert result.orders == 1 and result.pending_files == 0
    assert db.get(Order, expired.id) is None and not (storage.root / key).exists()
    assert db.get(Order, younger.id) is not None and db.get(Customer, customer.id) is not None
    for model in (
        OrderEvent,
        DiskFolder,
        DeletionRequest,
        MaterialHandover,
        PaymentRecord,
        Notification,
    ):
        assert not db.scalar(
            select(func.count()).select_from(model).where(model.order_id == expired.id)
        )
    assert cleaner(db, storage, now=NOW, dry_run=False).orders == 0


def test_last_agreement_and_customer_credentials_removed_together(graph):
    db, storage, admin, customer = graph
    order(graph)
    db.add_all(
        [
            CustomerEvent(
                customer_id=customer.id, actor_admin_id=admin.id, event_type="customer_created"
            ),
            Session(
                customer_id=customer.id,
                session_hash="a" * 64,
                created_at=START,
                expires_at=NOW + timedelta(days=1),
            ),
            AuthToken(
                customer_id=customer.id,
                token_hash="b" * 64,
                purpose=TokenPurpose.INVITATION,
                created_at=START,
                expires_at=NOW + timedelta(days=1),
            ),
            Notification(kind="invitation", customer_id=customer.id, recipient=customer.email),
        ]
    )
    db.commit()
    result = cleaner(db, storage, now=NOW, dry_run=False)
    assert result.orders == 1 and result.customers == 1
    assert db.get(Customer, customer.id) is None
    for model in (Session, AuthToken, CustomerEvent, Notification):
        assert not db.scalar(
            select(func.count()).select_from(model).where(model.customer_id == customer.id)
        )


@pytest.mark.parametrize("days,expected", [(13, 0), (14, 1), (15, 1)])
def test_unsigned_customer_fourteen_day_boundary(graph, days, expected):
    db, storage, _, customer = graph
    customer.created_at = NOW - timedelta(days=days)
    db.commit()
    assert cleaner(db, storage, now=NOW, dry_run=False).customers == expected


@pytest.mark.parametrize("state", list(AgreementStatus))
def test_signing_and_active_orders_block_customer_purge(graph, state):
    db, storage, admin, customer = graph
    item = order(graph, fulfilled=None, signed=False, status=OrderStatus.AWAITING_AGREEMENT)
    if state == AgreementStatus.APPROVED:
        key, digest = storage.put(b"%PDF-signed")
        agreement = Agreement(
            order_id=item.id,
            status=state,
            final_pdf_key=key,
            final_sha256=digest,
            verified_at=START,
            verified_by_id=admin.id,
            created_at=START,
        )
    else:
        agreement = Agreement(order_id=item.id, status=state, created_at=START)
    db.add(agreement)
    db.commit()
    assert cleaner(db, storage, now=NOW, dry_run=False).customers == 0
    item = locked_order(db, item.id)
    item.status = OrderStatus.CANCELLED
    item.closed_at = NOW
    db.commit()
    result = cleaner(db, storage, now=NOW, dry_run=False)
    assert result.customers == (0 if state == AgreementStatus.APPROVED else 1)


def test_live_disk_materials_and_processing_delivery_block_cleanup(graph):
    db, storage, _, customer = graph
    item = order(graph)
    folder = DiskFolder(order_id=item.id, disk_path="disk:/live")
    db.add(folder)
    db.commit()
    assert cleaner(db, storage, now=NOW, dry_run=False).orders == 0
    folder.deleted_at = DUE
    db.add(
        Notification(
            kind="result_ready",
            order_id=item.id,
            status="processing",
            lease_id=uuid4(),
            lease_until=NOW + timedelta(hours=1),
        )
    )
    db.commit()
    assert cleaner(db, storage, now=NOW, dry_run=False).orders == 0


def test_file_failure_is_durable_inaccessible_and_retried(graph):
    db, storage, _, _ = graph
    item = order(graph)
    key = db.scalar(select(Agreement.final_pdf_key).where(Agreement.order_id == item.id))

    class Broken(AgreementStorage):
        def delete(self, key):
            raise AgreementStorageError("synthetic")

    db.commit()
    result = cleaner(db, Broken(storage.root), now=NOW, dry_run=False)
    assert result.pending_files == 1
    assert db.get(Order, item.id) is None and (storage.root / key).exists()
    assert cleaner(db, storage, now=NOW, dry_run=False).pending_files == 0
    assert not (storage.root / key).exists()


def test_parallel_workers_do_not_double_delete(database_settings, alembic_config, tmp_path):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    storage = AgreementStorage(tmp_path / "pdf")
    customer_id = uuid4()
    with DBSession(engine) as db:
        db.add(Customer(id=customer_id, email=f"{customer_id.hex}@example.ru", created_at=START))
        db.commit()
    barrier = Barrier(2)

    def run():
        with DBSession(engine) as db:
            barrier.wait(timeout=10)
            return cleaner(db, storage, now=NOW, dry_run=False)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        assert sum(r.customers for r in results) == 1
    finally:
        engine.dispose()


def test_null_clock_never_uses_updated_closed_or_pdf_dates(graph):
    db, storage, _, customer = graph
    item = order(graph, fulfilled=None)
    db.commit()
    assert cleaner(db, storage, now=NOW, dry_run=False).orders == 0
    assert db.get(Order, item.id) is not None


def test_database_failure_before_intent_commit_never_unlinks_pdf(graph, monkeypatch):
    db, storage, _, _ = graph
    item = order(graph)
    key = db.scalar(select(Agreement.final_pdf_key).where(Agreement.order_id == item.id))
    identifier = item.id
    db.commit()
    real_commit = db.commit

    calls = 0

    def fail_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic commit failure")
        return real_commit()

    with monkeypatch.context() as m:
        m.setattr(db, "commit", fail_once)
        result = cleaner(db, storage, now=NOW, dry_run=False)
    assert result.failed == 1 and db.get(Order, identifier) is not None
    assert (storage.root / key).exists()
    assert cleaner(db, storage, now=NOW, dry_run=False).orders == 1


def test_one_invalid_graph_does_not_stop_other_customer(graph):
    db, storage, admin, customer = graph
    item = order(graph)
    other = Customer(email=f"{uuid4().hex}@example.ru", created_at=START)
    db.add(other)
    db.flush()
    other_id = other.id
    key = db.scalar(select(Agreement.final_pdf_key).where(Agreement.order_id == item.id))
    # Malformed storage keys must be retained for investigation, without file traversal.
    agreement = db.scalar(select(Agreement).where(Agreement.order_id == item.id))
    agreement.final_pdf_key = "../outside.pdf"
    db.commit()
    result = cleaner(db, storage, now=NOW, dry_run=False)
    assert result.failed == 1
    assert db.get(Order, item.id) is not None
    assert db.get(Customer, other_id) is None
    assert (storage.root / key).exists()


def test_signed_cancellation_uses_five_years_from_cancellation(graph):
    db, storage, _, customer = graph
    expired = order(graph, fulfilled=None, status=OrderStatus.CANCELLED, closed=DUE)
    younger = order(
        graph, fulfilled=None, status=OrderStatus.CANCELLED, closed=DUE + timedelta(microseconds=1)
    )
    db.commit()
    result = cleaner(db, storage, now=NOW, dry_run=False)
    assert result.orders == 1 and result.customers == 0
    assert db.get(Order, expired.id) is None
    assert db.get(Order, younger.id) is not None


def test_expired_ready_order_does_not_wait_for_late_automatic_closure(graph):
    db, storage, _, _ = graph
    item = order(graph, status=OrderStatus.RESULT_READY)
    identifier = item.id
    db.commit()
    result = cleaner(db, storage, now=NOW, dry_run=False)
    assert result.orders == 1
    assert db.get(Order, identifier) is None


def test_dry_run_identifies_candidates_without_erasing_them(graph):
    db, storage, _, customer = graph
    item = order(graph)
    db.commit()
    result = cleaner(db, storage, now=NOW, dry_run=True)
    assert result.candidates == [
        {"customer_id": str(customer.id), "order_ids": [str(item.id)], "delete_customer": True}
    ]
    assert db.get(Order, item.id) is not None


def test_fsync_failure_after_unlink_keeps_durable_retry(graph, monkeypatch):
    import os

    db, storage, _, _ = graph
    order(graph)
    db.commit()

    def broken(fd):
        raise OSError("synthetic durability failure")

    with monkeypatch.context() as m:
        m.setattr(os, "fsync", broken)
        result = cleaner(db, storage, now=NOW, dry_run=False)
    assert result.pending_files == 1
    assert cleaner(db, storage, now=NOW, dry_run=False).pending_files == 0


def test_failed_pdf_prefix_cannot_starve_later_deletion(graph):
    from uuid import UUID

    from sinegor.modules.retention.models import RetentionFileDeletion

    db, storage, _, _ = graph
    first, _ = storage.put(b"blocked")
    second, _ = storage.put(b"removable")
    db.add_all(
        [
            RetentionFileDeletion(id=UUID(int=1), file_key=first),
            RetentionFileDeletion(id=UUID(int=2), file_key=second),
        ]
    )
    db.commit()

    class PartlyBroken(AgreementStorage):
        def delete(self, key):
            if key == first:
                raise AgreementStorageError("synthetic permanent failure")
            return super().delete(key)

    for _ in range(3):
        cleaner(db, PartlyBroken(storage.root), now=NOW, dry_run=False, limit=1)
    assert (storage.root / first).exists()
    assert not (storage.root / second).exists()
    assert db.scalar(select(func.count()).select_from(RetentionFileDeletion)) == 1

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from test_disk import MemoryDisk

from sinegor.db.session import create_db_engine
from sinegor.db.types import DeletionReason, DeletionStatus, OrderStatus, ServiceType
from sinegor.integrations.yandex_disk.client import Resource
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.auth.models import AdminUser
from sinegor.modules.customers.models import Customer
from sinegor.modules.disk import service as disk_service
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications.models import Notification
from sinegor.modules.orders.models import Order
from sinegor.modules.orders.service import locked_order
from sinegor.modules.retention import service
from sinegor.modules.retention.models import DeletionRequest

pytestmark = pytest.mark.integration


@pytest.fixture
def persisted(database_settings, alembic_config):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    customer_id, order_id, admin_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    Customer(id=customer_id, email=f"{customer_id.hex}@example.ru"),
                    AdminUser(
                        id=admin_id, email=f"{admin_id.hex}@example.ru", password_hash="test"
                    ),
                ]
            )
            db.flush()
            db.add(
                Order(
                    id=order_id,
                    customer_id=customer_id,
                    service_type=ServiceType.ANALYSIS,
                    status=OrderStatus.RESULT_READY,
                    created_at=now - timedelta(days=20),
                    ready_at=now - timedelta(days=15),
                    result_notified_at=now - timedelta(days=15),
                )
            )
            db.commit()
        yield SimpleNamespace(
            engine=engine, customer_id=customer_id, order_id=order_id, admin_id=admin_id, now=now
        )
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Notification).where(Notification.order_id == order_id))
            connection.execute(delete(DeletionRequest).where(DeletionRequest.order_id == order_id))
            connection.execute(delete(DiskFolder).where(DiskFolder.order_id == order_id))
            connection.execute(delete(OrderEvent).where(OrderEvent.order_id == order_id))
            connection.execute(delete(Order).where(Order.id == order_id))
            connection.execute(delete(Customer).where(Customer.id == customer_id))
            connection.execute(delete(AdminUser).where(AdminUser.id == admin_id))
        engine.dispose()


@pytest.mark.parametrize("operation", ["due", "permission", "confirm", "defer"])
def test_competing_retention_actions_create_one_request_and_event(persisted, operation):
    request_id = None
    if operation in {"confirm", "defer"}:
        with Session(persisted.engine) as db:
            item = DeletionRequest(
                order_id=persisted.order_id,
                reason=DeletionReason.RETENTION_EXPIRED,
                due_at=persisted.now - timedelta(days=1),
            )
            db.add(item)
            db.commit()
            request_id = item.id
    barrier = Barrier(2)

    def attempt():
        with Session(persisted.engine) as db:
            barrier.wait(timeout=10)
            if operation == "due":
                return service.process_due(db)
            if operation == "permission":
                return service.authorize_early(db, persisted.order_id, persisted.customer_id).id
            if operation == "confirm":
                return service.confirm(db, persisted.order_id, request_id, persisted.admin_id).id
            return service.defer(
                db,
                persisted.order_id,
                request_id,
                persisted.admin_id,
                persisted.now + timedelta(days=2),
                "Accepted clarification",
            ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt) for _ in range(2)]
        results = [f.result(timeout=20) for f in futures]
    if operation == "due":
        assert sorted(results) == [0, 1]
    else:
        assert results[0] == results[1]
    expected = {
        "due": "deletion_requested",
        "permission": "deletion_early_authorized",
        "confirm": "deletion_confirmed",
        "defer": "deletion_deferred",
    }[operation]
    with Session(persisted.engine) as db:
        assert db.scalar(select(func.count()).select_from(DeletionRequest)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(OrderEvent)
                .where(OrderEvent.event_type == expected)
            )
            == 1
        )


def test_orders_cli_completes_and_creates_request_without_external_services(
    persisted, database_settings
):
    environment = dict(os.environ)
    environment.update(
        DATABASE_URL=database_settings.database_url.get_secret_value(),
        SINEGOR_ENV_FILE="/dev/null",
        APP_ENV="test",
        LOG_LEVEL="WARNING",
    )
    for expected in [(1, 1), (0, 0)]:
        result = subprocess.run(
            [sys.executable, "-m", "sinegor.jobs.process_orders"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0
        assert f"Orders advanced: {expected[0]}" in result.stdout
        assert f"Deletion requests updated: {expected[1]}" in result.stdout
    with Session(persisted.engine) as db:
        assert db.get(Order, persisted.order_id).status == OrderStatus.COMPLETED
        item = db.scalar(select(DeletionRequest))
        assert item.status == DeletionStatus.WAITING
        assert item.confirmed_at is None and item.performed_at is None


@pytest.mark.parametrize("first_action", ["delete", "defer"])
def test_deferral_and_deletion_cannot_overtake_each_other(persisted, first_action):
    disk = MemoryDisk()
    folder_path = f"{disk.root}/order-{persisted.order_id}"
    disk.resources[folder_path] = Resource(folder_path, "b8-test-resource")
    with Session(persisted.engine) as db:
        item = DeletionRequest(
            order_id=persisted.order_id,
            reason=DeletionReason.RETENTION_EXPIRED,
            due_at=persisted.now - timedelta(days=1),
            status=DeletionStatus.CONFIRMED,
            confirmed_at=persisted.now,
            confirmed_by_id=persisted.admin_id,
        )
        db.add_all(
            [
                item,
                DiskFolder(
                    order_id=persisted.order_id,
                    disk_path=folder_path,
                    resource_id="b8-test-resource",
                ),
            ]
        )
        db.commit()
        request_id = item.id
    acquired, release = Event(), Event()

    def attempt(action, first=False):
        with Session(persisted.engine) as db:
            if first:
                locked_order(db, persisted.order_id)
                acquired.set()
                assert release.wait(timeout=10)
            try:
                if action == "delete":
                    disk_service.delete_folder(
                        db, disk, persisted.order_id, request_id, persisted.admin_id
                    )
                else:
                    service.defer(
                        db,
                        persisted.order_id,
                        request_id,
                        persisted.admin_id,
                        persisted.now + timedelta(days=2),
                        "Accepted clarification",
                    )
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(attempt, first_action, True)
        try:
            assert acquired.wait(timeout=10)
            second = executor.submit(attempt, "defer" if first_action == "delete" else "delete")
        finally:
            release.set()
        assert first.result(timeout=20) == 200
        assert second.result(timeout=20) == (409 if first_action == "delete" else 200)
    with Session(persisted.engine) as db:
        item = db.get(DeletionRequest, request_id)
        assert item.status == DeletionStatus.PERFORMED
    assert len([call for call in disk.calls if call[0] == "delete"]) == 1


def test_competing_single_action_deletions_send_one_delete_and_one_email(persisted):
    disk = MemoryDisk()
    path = f"{disk.root}/order-{persisted.order_id}"
    disk.resources[path] = Resource(path, "unified-race-resource")
    with Session(persisted.engine) as db:
        item = DeletionRequest(
            order_id=persisted.order_id,
            reason=DeletionReason.RETENTION_EXPIRED,
            due_at=persisted.now - timedelta(days=1),
        )
        db.add_all(
            [
                item,
                DiskFolder(
                    order_id=persisted.order_id, disk_path=path, resource_id="unified-race-resource"
                ),
            ]
        )
        db.commit()
        request_id = item.id
    barrier = Barrier(2)

    def attempt():
        with Session(persisted.engine) as db:
            barrier.wait(timeout=10)
            return disk_service.delete_folder(
                db, disk, persisted.order_id, request_id, persisted.admin_id
            ).deleted_at

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt) for _ in range(2)]
        results = [f.result(timeout=20) for f in futures]
    assert results[0] == results[1] and results[0] is not None
    assert len([c for c in disk.calls if c[0] == "delete"]) == 1
    with Session(persisted.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.kind == "materials_deleted",
                    Notification.order_id == persisted.order_id,
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(OrderEvent)
                .where(
                    OrderEvent.event_type == "deletion_confirmed",
                    OrderEvent.order_id == persisted.order_id,
                )
            )
            == 1
        )

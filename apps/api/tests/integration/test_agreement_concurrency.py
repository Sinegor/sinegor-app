from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from test_agreements import pdf

from sinegor.db.session import create_db_engine
from sinegor.db.types import AgreementStatus, OrderStatus, ServiceType
from sinegor.modules.agreements import service
from sinegor.modules.agreements.models import Agreement, AgreementFileDeletion
from sinegor.modules.agreements.storage import AgreementStorage
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.auth.models import AdminUser
from sinegor.modules.customers.models import Customer
from sinegor.modules.orders.models import Order

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("operation", ["two_approvals", "replacement_and_approval"])
def test_competing_agreement_decisions_are_serialized(
    database_settings, alembic_config, tmp_path, operation
):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    storage = AgreementStorage(tmp_path / "agreements")
    customer_id, admin_id, order_id = uuid4(), uuid4(), uuid4()
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    Customer(id=customer_id, email=f"{customer_id.hex}@example.ru"),
                    AdminUser(
                        id=admin_id, email=f"{admin_id.hex}@example.ru", password_hash="test-only"
                    ),
                ]
            )
            db.flush()
            db.add(Order(id=order_id, customer_id=customer_id, service_type=ServiceType.ANALYSIS))
            db.commit()
            service.upload(db, storage, order_id, pdf("initial"), 0, admin_id, initial=True)
            service.upload(db, storage, order_id, pdf("signed A"), 1, customer_id, initial=False)
        barrier = Barrier(2)

        def attempt(replace):
            with Session(engine) as db:
                barrier.wait(timeout=10)
                try:
                    if replace:
                        service.upload(
                            db, storage, order_id, pdf("signed B"), 2, customer_id, initial=False
                        )
                    else:
                        service.review(db, storage, order_id, 2, admin_id)
                    return 200
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, False),
                executor.submit(attempt, operation == "replacement_and_approval"),
            ]
            assert sorted(f.result(timeout=20) for f in futures) == [200, 409]
        with Session(engine) as db:
            agreement = db.scalar(select(Agreement).where(Agreement.order_id == order_id))
            if agreement.status == AgreementStatus.APPROVED:
                assert storage.read(agreement.final_pdf_key, agreement.final_sha256)[0] == pdf(
                    "signed A"
                )
                assert db.get(Order, order_id).status == OrderStatus.AWAITING_MATERIALS
                assert not agreement.initial_pdf_key and not agreement.returned_pdf_key
            else:
                assert storage.read(agreement.returned_pdf_key, agreement.returned_sha256)[
                    0
                ] == pdf("signed B")
                assert db.get(Order, order_id).status == OrderStatus.AWAITING_AGREEMENT
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(OrderEvent)
                    .where(
                        OrderEvent.order_id == order_id,
                        OrderEvent.event_type == "agreement_approved",
                    )
                )
                <= 1
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(AgreementFileDeletion).where(AgreementFileDeletion.order_id == order_id)
            )
            connection.execute(delete(OrderEvent).where(OrderEvent.order_id == order_id))
            connection.execute(delete(Agreement).where(Agreement.order_id == order_id))
            connection.execute(delete(Order).where(Order.id == order_id))
            connection.execute(delete(AdminUser).where(AdminUser.id == admin_id))
            connection.execute(delete(Customer).where(Customer.id == customer_id))
        engine.dispose()

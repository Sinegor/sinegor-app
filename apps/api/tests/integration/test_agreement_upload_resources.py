import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import httpx2
import pytest
from alembic import command
from sqlalchemy import create_engine, delete
from test_agreements import pdf

import sinegor.main as application
from sinegor.core.config import Settings
from sinegor.db.types import OrderStatus, ServiceType
from sinegor.modules.agreements import service
from sinegor.modules.agreements.models import Agreement, AgreementFileDeletion
from sinegor.modules.agreements.storage import AgreementStorage
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.auth.models import AdminUser, Session
from sinegor.modules.auth.security import new_secret, secret_hash
from sinegor.modules.customers.models import Customer
from sinegor.modules.notifications.models import Notification
from sinegor.modules.orders.models import Order

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "role,phase,cancel",
    [
        ("admin", "body", False),
        ("customer", "body", False),
        ("admin", "validation", False),
        ("customer", "validation", False),
        ("customer", "body", True),
    ],
)
def test_upload_releases_database_while_receiving_and_validating(
    database_settings, alembic_config, tmp_path, monkeypatch, role, phase, cancel
):
    command.upgrade(alembic_config, "head")
    engine = create_engine(
        database_settings.database_url.get_secret_value(),
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
        hide_parameters=True,
    )
    monkeypatch.setattr(application, "create_db_engine", lambda settings: engine)
    settings = Settings(
        _env_file=None,
        database_url=database_settings.database_url,
        app_env="test",
        public_origin="http://testserver",
        log_level="CRITICAL",
    )
    app = application.create_app(settings)
    app.state.agreement_storage = AgreementStorage(tmp_path / "agreements")
    customer_id, admin_id, order_id = uuid4(), uuid4(), uuid4()
    raw = new_secret()
    validation_started, validation_release = Event(), Event()
    validate = service.validate_pdf

    async def scenario():
        async with app.router.lifespan_context(app):
            factory = app.state.session_factory
            with factory() as db:
                db.add_all(
                    [
                        Customer(id=customer_id, email=f"{customer_id.hex}@example.ru"),
                        AdminUser(
                            id=admin_id,
                            email=f"{admin_id.hex}@example.ru",
                            password_hash="test-only",
                        ),
                    ]
                )
                db.flush()
                db.add_all(
                    [
                        Order(
                            id=order_id, customer_id=customer_id, service_type=ServiceType.ANALYSIS
                        ),
                        Session(
                            session_hash=secret_hash(raw),
                            customer_id=customer_id if role == "customer" else None,
                            admin_id=admin_id if role == "admin" else None,
                            expires_at=datetime.now(UTC) + timedelta(hours=1),
                        ),
                    ]
                )
                db.commit()
                service.upload(
                    db,
                    app.state.agreement_storage,
                    order_id,
                    pdf("initial"),
                    0,
                    admin_id,
                    initial=True,
                )

            def paused_validation(data):
                validation_started.set()
                assert validation_release.wait(timeout=10)
                validate(data)

            if phase == "validation":
                monkeypatch.setattr(service, "validate_pdf", paused_validation)
            body_started, body_release = asyncio.Event(), asyncio.Event()
            payload = pdf("new document")

            async def slow_body():
                yield payload[:5]
                body_started.set()
                if phase == "body":
                    await body_release.wait()
                yield payload[5:]

            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://testserver",
                cookies={settings.session_cookie_name: raw},
            ) as client:
                csrf = (await client.get("/api/auth/csrf")).json()["csrf_token"]
                kind = "initial" if role == "admin" else "returned"
                task = asyncio.create_task(
                    client.post(
                        f"/api/{role}/orders/{order_id}/agreement/{kind}",
                        content=slow_body(),
                        headers={
                            "Origin": "http://testserver",
                            "X-CSRF-Token": csrf,
                            "Content-Type": "application/pdf",
                            "X-Agreement-Revision": "1",
                        },
                    )
                )
                try:
                    if phase == "body":
                        await asyncio.wait_for(body_started.wait(), timeout=10)
                    else:
                        assert await asyncio.to_thread(validation_started.wait, 10)
                    assert engine.pool.checkedout() == 0
                    assert (await client.get("/api/health/ready")).status_code == 200
                    if cancel:
                        with factory() as db:
                            order = db.get(Order, order_id)
                            order.status, order.closed_at = OrderStatus.CANCELLED, datetime.now(UTC)
                            db.commit()
                finally:
                    body_release.set()
                    validation_release.set()
                    response = await asyncio.wait_for(task, timeout=10)
                assert response.status_code == (409 if cancel else 200), response.text

    try:
        asyncio.run(scenario())
    finally:
        validation_release.set()
        with engine.begin() as connection:
            connection.execute(delete(Notification).where(Notification.order_id == order_id))
            connection.execute(
                delete(AgreementFileDeletion).where(AgreementFileDeletion.order_id == order_id)
            )
            connection.execute(delete(OrderEvent).where(OrderEvent.order_id == order_id))
            connection.execute(delete(Agreement).where(Agreement.order_id == order_id))
            connection.execute(delete(Session).where(Session.session_hash == secret_hash(raw)))
            connection.execute(delete(Order).where(Order.id == order_id))
            connection.execute(delete(AdminUser).where(AdminUser.id == admin_id))
            connection.execute(delete(Customer).where(Customer.id == customer_id))
        engine.dispose()

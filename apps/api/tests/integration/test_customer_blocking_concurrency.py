"""Real PostgreSQL waiters cannot bypass a committed block with stale ORM state."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, or_, select
from sqlalchemy.orm import Session as DBSession
from starlette.requests import Request

from sinegor.db.session import create_db_engine
from sinegor.db.types import TokenPurpose
from sinegor.modules.auth.dependencies import current_principal
from sinegor.modules.auth.models import AuthToken, Session
from sinegor.modules.auth.security import new_secret, secret_hash
from sinegor.modules.auth.service import consume_link, create_session, issue_and_send_link
from sinegor.modules.customers.access import change_access
from sinegor.modules.customers.models import Customer
from sinegor.modules.notifications.models import Notification
from sinegor.modules.notifications.service import _deliver, queue_invitation
from sinegor.modules.security_events.models import SecurityEvent

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "operation",
    [
        "consume_magic",
        "consume_invitation",
        "issue",
        "session",
        "protected",
        "invite_queue",
        "delayed_invite",
    ],
)
def test_block_wins_over_waiting_access(database_settings, alembic_config, operation):
    from alembic import command

    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    identifier, admin_id = uuid4(), uuid4()
    raw, cookie = new_secret(), new_secret()
    reached, preloaded, start = Event(), Event(), Event()
    now = datetime.now(UTC)
    sent = []
    mailer = SimpleNamespace(send_login_link=lambda *args: sent.append(True))

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FROM customers" in statement and (
            "FOR UPDATE" in statement or "FOR NO KEY UPDATE" in statement
        ):
            reached.set()

    def attempt():
        with DBSession(engine, expire_on_commit=False) as db:
            customer = db.get(Customer, identifier)
            job = db.scalar(select(Notification).where(Notification.customer_id == identifier))
            preloaded.set()
            assert start.wait(10)
            try:
                if operation.startswith("consume"):
                    consume_link(db, database_settings, raw, "")
                elif operation == "issue":
                    issue_and_send_link(
                        db, database_settings, mailer, customer, TokenPurpose.MAGIC_LINK
                    )
                elif operation == "session":
                    create_session(db, database_settings, "", customer_id=identifier)
                elif operation == "invite_queue":
                    queue_invitation(db, customer)
                elif operation == "delayed_invite":
                    result = _deliver(db, job, database_settings, mailer, None, None, None)
                    db.commit()
                    return 200 if result else 401
                else:
                    app = SimpleNamespace(state=SimpleNamespace(settings=database_settings))
                    request = Request(
                        {
                            "type": "http",
                            "app": app,
                            "headers": [
                                (
                                    b"cookie",
                                    f"{database_settings.session_cookie_name}={cookie}".encode(),
                                )
                            ],
                        }
                    )
                    current_principal(request, db)
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    try:
        with DBSession(engine) as db:
            db.add(Customer(id=identifier, email=f"{identifier.hex}@example.ru"))
            db.flush()
            db.add_all(
                [
                    AuthToken(
                        customer_id=identifier,
                        token_hash=secret_hash(raw),
                        purpose=TokenPurpose.INVITATION
                        if operation == "consume_invitation"
                        else TokenPurpose.MAGIC_LINK,
                        created_at=now,
                        expires_at=now + timedelta(minutes=15),
                    ),
                    Session(
                        customer_id=identifier,
                        session_hash=secret_hash(cookie),
                        created_at=now,
                        expires_at=now + timedelta(minutes=15),
                    ),
                    Notification(
                        kind="invitation",
                        customer_id=identifier,
                        recipient=f"{identifier.hex}@example.ru",
                        status="processing",
                        lease_id=uuid4(),
                        lease_until=now + timedelta(minutes=5),
                    ),
                ]
            )
            db.commit()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(attempt)
            assert preloaded.wait(10)
            with DBSession(engine) as editor:
                customer = editor.scalar(
                    select(Customer).where(Customer.id == identifier).with_for_update()
                )
                event.listen(engine, "before_cursor_execute", observe)
                start.set()
                assert reached.wait(10)
                change_access(
                    editor,
                    customer,
                    admin_id,
                    reason="Синтетическая причина",
                    comment="Не для письма",
                )
                if operation == "delayed_invite":
                    # Even after unblock, this previously claimed invitation is invalid.
                    customer = editor.scalar(
                        select(Customer).where(Customer.id == identifier).with_for_update()
                    )
                    change_access(editor, customer, admin_id)
            assert future.result(10) in {401, 409}
        assert not sent
        with DBSession(engine) as db:
            assert not db.scalars(
                select(Session).where(
                    Session.customer_id == identifier, Session.revoked_at.is_(None)
                )
            ).all()
            assert not db.scalars(
                select(AuthToken).where(
                    AuthToken.customer_id == identifier, AuthToken.used_at.is_(None)
                )
            ).all()
    finally:
        with engine.begin() as conn:
            conn.execute(
                delete(SecurityEvent).where(
                    or_(
                        SecurityEvent.user_id == identifier,
                        SecurityEvent.subject_user_id == identifier,
                    )
                )
            )
            conn.execute(delete(Notification).where(Notification.customer_id == identifier))
            conn.execute(delete(Session).where(Session.customer_id == identifier))
            conn.execute(delete(AuthToken).where(AuthToken.customer_id == identifier))
            conn.execute(delete(Customer).where(Customer.id == identifier))
        engine.dispose()


def test_authorization_lock_allows_admin_order_notification(database_settings, alembic_config):
    """Customer auth must serialize with blocks without deadlocking order notifications."""
    from alembic import command
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from sinegor.db.types import ServiceType
    from sinegor.modules.notifications.service import enqueue
    from sinegor.modules.orders.models import Order

    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    identifier, order_id = uuid4(), uuid4()
    cookie = new_secret()
    ready = Event()
    now = datetime.now(UTC)
    try:
        with DBSession(engine) as db:
            db.add(Customer(id=identifier, email=f"{identifier.hex}@example.ru"))
            db.flush()
            db.add_all(
                [
                    Order(id=order_id, customer_id=identifier, service_type=ServiceType.ANALYSIS),
                    Session(
                        customer_id=identifier,
                        session_hash=secret_hash(cookie),
                        created_at=now,
                        expires_at=now + timedelta(minutes=15),
                    ),
                ]
            )
            db.commit()

        def customer_request():
            with DBSession(engine) as db:
                app = SimpleNamespace(state=SimpleNamespace(settings=database_settings))
                req = Request(
                    {
                        "type": "http",
                        "app": app,
                        "headers": [
                            (
                                b"cookie",
                                f"{database_settings.session_cookie_name}={cookie}".encode(),
                            )
                        ],
                    }
                )
                current_principal(req, db)
                ready.set()
                db.scalar(select(Order).where(Order.id == order_id).with_for_update())
                db.commit()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with DBSession(engine) as admin:
                admin.scalar(select(Order).where(Order.id == order_id).with_for_update())
                future = pool.submit(customer_request)
                assert ready.wait(10)
                admin.execute(text("SET LOCAL lock_timeout = '500ms'"))
                error = None
                try:
                    enqueue(admin, "agreement_initial", order_id=order_id, customer_id=identifier)
                    admin.commit()
                except OperationalError:
                    error = "notification insert blocked by authorization customer lock"
                    admin.rollback()
            future.result(10)
            assert error is None, error
    finally:
        with engine.begin() as conn:
            conn.execute(delete(Notification).where(Notification.customer_id == identifier))
            conn.execute(delete(Session).where(Session.customer_id == identifier))
            conn.execute(delete(Order).where(Order.id == order_id))
            conn.execute(delete(Customer).where(Customer.id == identifier))
        engine.dispose()


@pytest.mark.parametrize("operation", ["issue", "consume"])
def test_block_revokes_access_when_issuance_or_login_wins(
    database_settings, alembic_config, operation
):
    from alembic import command

    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    identifier, admin_id = uuid4(), uuid4()
    raw = new_secret()
    entered_smtp, release_smtp = Event(), Event()
    now = datetime.now(UTC)

    def smtp_send(recipient, link):
        entered_smtp.set()
        assert release_smtp.wait(10)

    def issue():
        with DBSession(engine, expire_on_commit=False) as db:
            customer = db.get(Customer, identifier)
            issue_and_send_link(
                db,
                database_settings,
                SimpleNamespace(send_login_link=smtp_send),
                customer,
                TokenPurpose.MAGIC_LINK,
            )

    try:
        with DBSession(engine) as db:
            db.add(Customer(id=identifier, email=f"{identifier.hex}@example.ru"))
            db.flush()
            db.add(
                AuthToken(
                    customer_id=identifier,
                    token_hash=secret_hash(raw),
                    purpose=TokenPurpose.INVITATION,
                    created_at=now,
                    expires_at=now + timedelta(minutes=15),
                )
            )
            db.commit()
        if operation == "consume":
            with DBSession(engine) as db:
                cookie = consume_link(db, database_settings, raw, "")
                create_session(db, database_settings, "", customer_id=identifier)
                assert (
                    len(
                        db.scalars(
                            select(Session).where(
                                Session.customer_id == identifier, Session.revoked_at.is_(None)
                            )
                        ).all()
                    )
                    == 2
                )
                customer = db.scalar(
                    select(Customer)
                    .where(Customer.id == identifier)
                    .with_for_update(key_share=True)
                )
                change_access(db, customer, admin_id, reason="Синтетическая причина")
                req = Request(
                    {
                        "type": "http",
                        "app": SimpleNamespace(state=SimpleNamespace(settings=database_settings)),
                        "headers": [
                            (
                                b"cookie",
                                f"{database_settings.session_cookie_name}={cookie}".encode(),
                            )
                        ],
                    }
                )
                with pytest.raises(HTTPException) as exc:
                    current_principal(req, db)
                assert exc.value.status_code == 401
        else:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(issue)
                try:
                    assert entered_smtp.wait(10), "Link was not committed before SMTP"
                    with DBSession(engine) as db:
                        customer = db.scalar(
                            select(Customer)
                            .where(Customer.id == identifier)
                            .with_for_update(key_share=True)
                        )
                        change_access(db, customer, admin_id, reason="Синтетическая причина")
                finally:
                    release_smtp.set()
                future.result(10)
        with DBSession(engine) as db:
            assert not db.scalars(
                select(AuthToken).where(
                    AuthToken.customer_id == identifier, AuthToken.used_at.is_(None)
                )
            ).all()
            assert not db.scalars(
                select(Session).where(
                    Session.customer_id == identifier, Session.revoked_at.is_(None)
                )
            ).all()
    finally:
        with engine.begin() as conn:
            conn.execute(
                delete(SecurityEvent).where(
                    or_(
                        SecurityEvent.user_id == identifier,
                        SecurityEvent.subject_user_id == identifier,
                    )
                )
            )
            conn.execute(delete(Notification).where(Notification.customer_id == identifier))
            conn.execute(delete(Session).where(Session.customer_id == identifier))
            conn.execute(delete(AuthToken).where(AuthToken.customer_id == identifier))
            conn.execute(delete(Customer).where(Customer.id == identifier))
        engine.dispose()

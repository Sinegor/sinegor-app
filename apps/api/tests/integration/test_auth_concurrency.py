from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session as DBSession

from sinegor.core.config import Settings
from sinegor.db.session import create_db_engine
from sinegor.db.types import TokenPurpose
from sinegor.modules.auth import service as auth_service
from sinegor.modules.auth.models import AdminUser, AuthToken, Session
from sinegor.modules.auth.security import HASHER, new_secret, secret_hash
from sinegor.modules.auth.service import admin_login, consume_link
from sinegor.modules.customers.models import Customer

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("kind", ["magic", "admin"])
def test_concurrent_credential_use_creates_only_one_session(
    database_settings, alembic_config, kind
):
    from alembic import command

    command.upgrade(alembic_config, "head")
    key = Fernet.generate_key().decode()
    settings = Settings(
        _env_file=None, database_url=database_settings.database_url, auth_encryption_key=key
    )
    engine = create_db_engine(settings)
    identifier = uuid4()
    raw = new_secret()
    secret = pyotp.random_base32()
    password = "concurrent-test-password"
    email = f"{identifier.hex}@example.ru"
    now = datetime.now(UTC)
    try:
        with DBSession(engine) as db:
            if kind == "magic":
                db.add(Customer(id=identifier, email=email))
                db.flush()
                db.add(
                    AuthToken(
                        customer_id=identifier,
                        token_hash=secret_hash(raw),
                        purpose=TokenPurpose.MAGIC_LINK,
                        created_at=now,
                        expires_at=now + timedelta(minutes=15),
                    )
                )
            else:
                db.add(
                    AdminUser(
                        id=identifier,
                        email=email,
                        password_hash=HASHER.hash(password),
                        totp_secret_encrypted=Fernet(key.encode())
                        .encrypt(secret.encode())
                        .decode(),
                    )
                )
            db.commit()
        code = pyotp.TOTP(secret).now()
        barrier = Barrier(2)

        def attempt():
            with DBSession(engine) as db:
                barrier.wait(timeout=10)
                try:
                    if kind == "magic":
                        consume_link(db, settings, raw, "")
                    else:
                        admin_login(db, settings, email, password, code, "")
                    return 200
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt), executor.submit(attempt)]
            results = [future.result(timeout=20) for future in futures]
        assert sorted(results) == [200, 401]
        with DBSession(engine) as db:
            column = Session.customer_id if kind == "magic" else Session.admin_id
            assert (
                db.scalar(select(func.count()).select_from(Session).where(column == identifier))
                == 1
            )
    finally:
        with engine.begin() as connection:
            column = Session.customer_id if kind == "magic" else Session.admin_id
            connection.execute(delete(Session).where(column == identifier))
            connection.execute(delete(AuthToken).where(AuthToken.customer_id == identifier))
            connection.execute(delete(AdminUser).where(AdminUser.id == identifier))
            connection.execute(delete(Customer).where(Customer.id == identifier))
        engine.dispose()


def test_link_expiring_while_waiting_for_customer_lock_is_rejected(
    database_settings, alembic_config, monkeypatch
):
    from alembic import command

    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    identifier = uuid4()
    raw = new_secret()
    now = datetime.now(UTC)
    waiting = Event()
    started_at = now

    class Clock:
        value = started_at

        @classmethod
        def now(cls, tz):
            return cls.value

    monkeypatch.setattr(auth_service, "datetime", Clock)

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FROM customers" in statement and "FOR UPDATE" in statement:
            waiting.set()

    try:
        with DBSession(engine) as db:
            db.add(Customer(id=identifier, email=f"{identifier.hex}@example.ru"))
            db.flush()
            db.add(
                AuthToken(
                    customer_id=identifier,
                    token_hash=secret_hash(raw),
                    purpose=TokenPurpose.MAGIC_LINK,
                    created_at=now,
                    expires_at=now + timedelta(seconds=1),
                )
            )
            db.commit()

        def attempt():
            with DBSession(engine) as db:
                try:
                    consume_link(db, database_settings, raw, "")
                    return 200
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code

        with ThreadPoolExecutor(max_workers=1) as executor:
            with DBSession(engine) as editor:
                editor.scalar(select(Customer).where(Customer.id == identifier).with_for_update())
                event.listen(engine, "before_cursor_execute", observe)
                future = executor.submit(attempt)
                try:
                    assert waiting.wait(timeout=10), "Verifier did not reach the customer lock"
                    Clock.value = now + timedelta(seconds=2)
                finally:
                    editor.commit()
            assert future.result(timeout=10) == 401
        with DBSession(engine) as db:
            assert (
                db.scalar(select(AuthToken).where(AuthToken.customer_id == identifier)).used_at
                is None
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Session)
                    .where(Session.customer_id == identifier)
                )
                == 0
            )
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Session).where(Session.customer_id == identifier))
            connection.execute(delete(AuthToken).where(AuthToken.customer_id == identifier))
            connection.execute(delete(Customer).where(Customer.id == identifier))
        engine.dispose()

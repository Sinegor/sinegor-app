"""Purge must work without application imports and preserve unexpired/business records."""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DBSession

from sinegor.db.models import AuthRateLimit, AuthToken, Customer, Order, OrderEvent, Session
from sinegor.db.session import create_db_engine
from sinegor.db.types import ServiceType, TokenPurpose
from sinegor.modules.auth.security import new_secret, secret_hash

pytestmark = pytest.mark.integration


def test_purge_auth_cli_fresh_process_removes_only_expired_state(database_settings, alembic_config):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    customer_id, order_id = uuid4(), uuid4()
    expired_token, active_token = secret_hash(new_secret()), secret_hash(new_secret())
    expired_session, active_session = secret_hash(new_secret()), secret_hash(new_secret())
    old_limit, active_limit = secret_hash(new_secret()), secret_hash(new_secret())
    now = datetime.now(UTC)
    environment = dict(os.environ)
    environment.update(
        DATABASE_URL=database_settings.database_url.get_secret_value(),
        APP_ENV="test",
        SINEGOR_ENV_FILE="/dev/null",
        AUTH_RATE_WINDOW_SECONDS=str(database_settings.auth_rate_window_seconds),
    )
    try:
        with DBSession(engine) as db:
            db.add(Customer(id=customer_id, email=f"purge-{customer_id.hex}@example.ru"))
            db.flush()
            db.add(Order(id=order_id, customer_id=customer_id, service_type=ServiceType.ANALYSIS))
            db.flush()
            db.add(OrderEvent(order_id=order_id, event_type="order_created"))
            for token_hash, session_hash, expired in (
                (expired_token, expired_session, True),
                (active_token, active_session, False),
            ):
                created = now - timedelta(days=2)
                expires = now - timedelta(days=1) if expired else now + timedelta(hours=1)
                db.add_all(
                    [
                        AuthToken(
                            customer_id=customer_id,
                            token_hash=token_hash,
                            purpose=TokenPurpose.MAGIC_LINK,
                            created_at=created,
                            expires_at=expires,
                        ),
                        Session(
                            customer_id=customer_id,
                            session_hash=session_hash,
                            created_at=created,
                            expires_at=expires,
                        ),
                    ]
                )
            db.add_all(
                [
                    AuthRateLimit(key_hash=old_limit, window_started_at=now - timedelta(days=1)),
                    AuthRateLimit(key_hash=active_limit, window_started_at=now),
                ]
            )
            db.commit()

        for _ in range(2):
            result = subprocess.run(
                [sys.executable, "-m", "sinegor.jobs.purge_auth"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            assert result.returncode == 0, f"purge_auth process exit code: {result.returncode}"
            assert "Expired authentication state removed" in result.stdout

        with DBSession(engine) as db:
            assert set(
                db.scalars(select(AuthToken.token_hash).where(AuthToken.customer_id == customer_id))
            ) == {active_token}
            assert set(
                db.scalars(select(Session.session_hash).where(Session.customer_id == customer_id))
            ) == {active_session}
            assert set(
                db.scalars(
                    select(AuthRateLimit.key_hash).where(
                        AuthRateLimit.key_hash.in_([old_limit, active_limit])
                    )
                )
            ) == {active_limit}
            assert db.get(Customer, customer_id) is not None
            assert db.get(Order, order_id) is not None
            assert db.scalar(select(OrderEvent).where(OrderEvent.order_id == order_id)) is not None
    finally:
        with engine.begin() as connection:
            connection.execute(delete(AuthToken).where(AuthToken.customer_id == customer_id))
            connection.execute(delete(Session).where(Session.customer_id == customer_id))
            connection.execute(
                delete(AuthRateLimit).where(AuthRateLimit.key_hash.in_([old_limit, active_limit]))
            )
            connection.execute(delete(OrderEvent).where(OrderEvent.order_id == order_id))
            connection.execute(delete(Order).where(Order.id == order_id))
            connection.execute(delete(Customer).where(Customer.id == customer_id))
        engine.dispose()

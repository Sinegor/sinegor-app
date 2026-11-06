"""A journal failure must not leave usable access without its security fact."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from sinegor.db.types import TokenPurpose
from sinegor.modules.auth import service
from sinegor.modules.auth.models import AuthToken, Session
from sinegor.modules.auth.security import new_secret, secret_hash
from sinegor.modules.customers.models import Customer
from sinegor.modules.security_events.models import SecurityEvent

pytestmark = pytest.mark.integration


def test_session_and_token_consumption_rollback_if_journal_insert_fails(
    db_session, database_settings, monkeypatch
):
    customer = Customer(email="atomic-security@example.ru")
    db_session.add(customer)
    db_session.flush()
    raw = new_secret()
    token = AuthToken(
        customer_id=customer.id,
        token_hash=secret_hash(raw),
        purpose=TokenPurpose.MAGIC_LINK,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db_session.add(token)
    db_session.commit()
    original = service.record

    def failing_record(db, event_type, reason, **kwargs):
        if reason == "session_created":
            raise RuntimeError("simulated journal failure")
        return original(db, event_type, reason, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(service, "record", failing_record)
        with pytest.raises(RuntimeError):
            service.consume_link(db_session, database_settings, raw, "")
        db_session.rollback()
    assert db_session.get(AuthToken, token.id).used_at is None
    assert db_session.scalar(select(func.count()).select_from(Session)) == 0
    assert db_session.scalar(select(func.count()).select_from(SecurityEvent)) == 0
    service.consume_link(db_session, database_settings, raw, "")
    assert db_session.get(AuthToken, token.id).used_at is not None
    assert db_session.scalar(select(func.count()).select_from(Session)) == 1
    assert set(db_session.scalars(select(SecurityEvent.reason_code))) == {
        "link_consumed",
        "magic_link_login",
        "session_created",
    }

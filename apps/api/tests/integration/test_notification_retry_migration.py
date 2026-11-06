from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sinegor.db.session import create_db_engine
from sinegor.modules.notifications.models import Notification

pytestmark = pytest.mark.integration


def test_retry_migration_preserves_legacy_jobs_and_refuses_lossy_downgrade(
    database_settings, alembic_config
):
    engine = create_db_engine(database_settings)
    identifier = uuid4()
    created = datetime.now(UTC) - timedelta(days=2)
    try:
        command.upgrade(alembic_config, "head")
        command.downgrade(alembic_config, "0009_notifications")
        with Session(engine) as db:
            db.add(
                Notification(
                    id=identifier,
                    kind="consultation",
                    recipient="synthetic@example.ru",
                    payload={"phone": "+79991234567"},
                    created_at=created,
                    attempts=12,
                )
            )
            db.commit()
        command.upgrade(alembic_config, "head")
        with Session(engine) as db:
            job = db.get(Notification, identifier)
            assert (
                job.created_at == created
                and job.attempts == 12
                and job.recipient == "synthetic@example.ru"
            )
            job.status = "failed"
            db.commit()
        with pytest.raises(IntegrityError):
            command.downgrade(alembic_config, "0009_notifications")
        with Session(engine) as db:
            job = db.get(Notification, identifier)
            assert job.status == "failed" and job.payload == {"phone": "+79991234567"}
            job.status = "pending"
            db.commit()
        command.downgrade(alembic_config, "0009_notifications")
        command.upgrade(alembic_config, "head")
        with Session(engine) as db:
            assert db.get(Notification, identifier).attempts == 12
    finally:
        command.upgrade(alembic_config, "head")
        with engine.begin() as connection:
            connection.execute(delete(Notification).where(Notification.id == identifier))
        engine.dispose()

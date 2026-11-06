"""The existing scheduler command must clean contacts in a fresh interpreter."""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import delete
from sqlalchemy.orm import Session

from sinegor.db.session import create_db_engine
from sinegor.modules.notifications import service
from sinegor.modules.notifications.models import Notification

pytestmark = pytest.mark.integration


def test_notification_cli_cleans_stopped_consultations_without_external_delivery(
    database_settings, alembic_config
):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    ids = []
    now = datetime.now(UTC)
    environment = dict(os.environ)
    environment.update(
        DATABASE_URL=database_settings.database_url.get_secret_value(),
        APP_ENV="test",
        SINEGOR_ENV_FILE="/dev/null",
    )
    script = """
import runpy
from unittest.mock import patch

external_calls = []

def forbidden(*args, **kwargs):
    external_calls.append(True)
    raise AssertionError('Unexpected external delivery during contact cleanup')

with patch('smtplib.SMTP', forbidden), patch('smtplib.SMTP_SSL', forbidden), \\
     patch('http.client.HTTPSConnection.request', forbidden):
    runpy.run_module('sinegor.jobs.process_notifications', run_name='__main__')
assert not external_calls, 'Cleanup attempted external delivery'
"""
    try:
        with Session(engine) as db:
            for kind, state, days in [
                ("consultation", "expired", 8),
                ("consultation_telegram", "failed", 8),
                ("consultation", "failed", 6),
                ("invitation", "failed", 8),
            ]:
                identifier = service.enqueue(
                    db, kind, recipient="cli@example.ru", payload={"phone": "+79991234567"}
                )
                item = db.get(Notification, identifier)
                item.created_at, item.status = now - timedelta(days=days), state
                ids.append(identifier)
            db.commit()
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, "-c", script],
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            assert result.returncode == 0, f"Notification CLI exit code: {result.returncode}"
            assert result.stdout.strip() == "Notifications delivered: 0"
            assert "cli@example.ru" not in result.stderr and "+79991234567" not in result.stderr
        with Session(engine) as db:
            for identifier in ids[:2]:
                item = db.get(Notification, identifier)
                assert item.recipient is None and item.payload == {}
                assert item.status == "expired" and item.last_error_code == "contacts_expired"
            for identifier in ids[2:]:
                item = db.get(Notification, identifier)
                assert item.recipient == "cli@example.ru" and item.payload["phone"]
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Notification).where(Notification.id.in_(ids)))
        engine.dispose()

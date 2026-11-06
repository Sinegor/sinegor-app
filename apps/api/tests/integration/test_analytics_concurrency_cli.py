"""Independent connections verify receipts really survive transaction boundaries."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from sinegor.db.session import create_db_engine
from sinegor.modules.analytics.models import AnalyticsConsentEvent
from sinegor.modules.analytics.schemas import ConsentInput
from sinegor.modules.analytics.service import record_event

pytestmark = pytest.mark.integration


def test_concurrent_duplicate_event_receipts_are_stable(database_settings, alembic_config):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    payload = ConsentInput(
        event_id=uuid4(), browser_id=uuid4(), event_type="grant", text_version="1"
    )
    barrier = Barrier(2)

    def attempt():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            event = record_event(db, payload)
            return event.recorded_at

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt) for _ in range(2)]
            times = [future.result(timeout=20) for future in futures]
        assert times[0] == times[1]
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(AnalyticsConsentEvent)) == 1
            assert db.get(AnalyticsConsentEvent, payload.event_id).recorded_at == times[0]
    finally:
        with engine.begin() as conn:
            conn.execute(
                delete(AnalyticsConsentEvent).where(
                    AnalyticsConsentEvent.event_id == payload.event_id
                )
            )
        engine.dispose()


def test_cleanup_cli_is_standalone_idempotent_and_retains_recent_events(
    database_settings, alembic_config
):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    old_id, new_id = uuid4(), uuid4()
    env = os.environ | {
        "DATABASE_URL": database_settings.database_url.get_secret_value(),
        "APP_ENV": "test",
        "SINEGOR_ENV_FILE": "/dev/null",
    }
    try:
        with Session(engine) as db:
            for identifier, days in [(old_id, 181), (new_id, 179)]:
                db.add(
                    AnalyticsConsentEvent(
                        event_id=identifier,
                        browser_id=uuid4(),
                        event_type="withdraw",
                        text_version="1",
                        recorded_at=datetime.now(UTC) - timedelta(days=days),
                    )
                )
            db.commit()
        for count in (1, 0):
            result = subprocess.run(
                [sys.executable, "-m", "sinegor.jobs.purge_analytics"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0
            assert result.stdout.strip() == f"Expired analytics consent events removed: {count}"
        with Session(engine) as db:
            assert db.get(AnalyticsConsentEvent, old_id) is None
            assert db.get(AnalyticsConsentEvent, new_id) is not None
    finally:
        with engine.begin() as conn:
            conn.execute(
                delete(AnalyticsConsentEvent).where(
                    AnalyticsConsentEvent.event_id.in_([old_id, new_id])
                )
            )
        engine.dispose()

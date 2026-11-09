import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy.orm import Session

from sinegor.db.session import create_db_engine
from sinegor.modules.customers.models import Customer

pytestmark = pytest.mark.integration


def test_cli_defaults_to_preview_executes_and_repeats(database_settings, alembic_config, tmp_path):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    identifier = uuid4()
    with Session(engine) as db:
        db.add(
            Customer(
                id=identifier,
                email=f"{identifier.hex}@example.ru",
                created_at=datetime.now(UTC) - timedelta(days=15),
            )
        )
        db.commit()
    env = os.environ | {
        "DATABASE_URL": database_settings.database_url.get_secret_value(),
        "APP_ENV": "test",
        "SINEGOR_ENV_FILE": "/dev/null",
        "PYTHONDONTWRITEBYTECODE": "1",
        "AGREEMENT_STORAGE_DIR": str(tmp_path / "agreements"),
        "DESTRUCTION_ARCHIVE_DIR": str(tmp_path / "archive"),
    }

    def run(*args):
        result = subprocess.run(
            [sys.executable, "-m", "sinegor.jobs.cleanup_business", *args],
            env=env,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode()
        return json.loads(result.stdout)

    try:
        assert run()["business"]["customers"] == 1
        with Session(engine) as db:
            assert db.get(Customer, identifier) is not None
        assert run("--execute")["business"]["customers"] == 1
        assert run("--execute")["business"]["customers"] == 0
    finally:
        engine.dispose()

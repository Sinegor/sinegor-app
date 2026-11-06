"""Run bootstrap in a fresh interpreter so application imports cannot mask missing models."""

import os
import subprocess
import sys
from uuid import uuid4

import pyotp
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from sinegor.db.models import AdminUser, SecurityEvent
from sinegor.db.session import create_db_engine
from sinegor.modules.auth.security import verify_password

pytestmark = pytest.mark.integration


def test_review_create_admin_cli_fresh_process(database_settings, alembic_config):
    from alembic import command

    command.upgrade(alembic_config, "head")
    email = f"bootstrap-{uuid4().hex}@example.ru"
    password = "review-regression-password"
    secret = pyotp.random_base32()
    key = Fernet.generate_key().decode()
    env = os.environ.copy()
    env.update(
        DATABASE_URL=database_settings.database_url.get_secret_value(),
        APP_ENV="test",
        SINEGOR_ENV_FILE="/dev/null",
        AUTH_ENCRYPTION_KEY=key,
        REVIEW_TEST_PASSWORD=password,
        REVIEW_TEST_TOTP=secret,
        REVIEW_TEST_EMAIL=email,
    )
    script = """
import os
import sys
from unittest.mock import patch
import pyotp
from sinegor.jobs.create_admin import main
secret = os.environ['REVIEW_TEST_TOTP']
password = os.environ['REVIEW_TEST_PASSWORD']
with patch.object(sys, 'argv', ['create_admin', '--email', os.environ['REVIEW_TEST_EMAIL']]), \
     patch('getpass.getpass', side_effect=[password, password, pyotp.TOTP(secret).now()]), \
     patch('pyotp.random_base32', return_value=secret):
    main()
"""
    engine = create_db_engine(database_settings)
    try:
        result = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30
        )
        # Do not include stderr: bootstrap deliberately emits its private enrollment URI there.
        assert result.returncode == 0, f"bootstrap process exit code: {result.returncode}"
        with Session(engine) as db:
            admin = db.scalar(select(AdminUser).where(AdminUser.email == email))
            assert admin is not None
            assert verify_password(password, admin.password_hash)
            assert (
                Fernet(key.encode()).decrypt(admin.totp_secret_encrypted.encode()).decode()
                == secret
            )
            assert admin.last_totp_step is not None
    finally:
        with engine.begin() as connection:
            ids = select(AdminUser.id).where(AdminUser.email == email)
            connection.execute(delete(SecurityEvent).where(SecurityEvent.subject_user_id.in_(ids)))
            connection.execute(delete(AdminUser).where(AdminUser.email == email))
        engine.dispose()

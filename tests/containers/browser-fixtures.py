"""Prepare only synthetic browser credentials in the isolated API database."""

import os
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.db.types import TokenPurpose
from sinegor.modules.auth.models import AdminUser, AuthToken
from sinegor.modules.auth.security import HASHER, secret_hash
from sinegor.modules.customers.models import Customer
from sqlalchemy import select

assert os.environ.get("LOCAL_CONTAINER_CHECK") == "yes"
settings = load_settings()
assert settings.app_env == "production" and settings.public_origin.host == "localhost"
email = os.environ["BROWSER_ADMIN_EMAIL"]
assert email.startswith("vi0-browser-") and email.endswith("@example.org")
engine = create_db_engine(settings)
try:
    with create_session_factory(engine)() as db:
        admin = db.scalar(select(AdminUser).where(AdminUser.email == email))
        if admin is None:
            admin = AdminUser(email=email)
            db.add(admin)
        admin.password_hash = HASHER.hash(os.environ["BROWSER_ADMIN_PASSWORD"])
        admin.totp_secret_encrypted = (
            Fernet(settings.auth_encryption_key.get_secret_value().encode())
            .encrypt(os.environ["BROWSER_ADMIN_TOTP"].encode())
            .decode()
        )
        admin.last_totp_step = None
        customer = db.scalar(
            select(Customer).where(Customer.email == os.environ["BROWSER_CUSTOMER_EMAIL"])
        )
        assert customer is not None
        db.add(
            AuthToken(
                customer_id=customer.id,
                token_hash=secret_hash(os.environ["BROWSER_CUSTOMER_TOKEN"]),
                purpose=TokenPurpose.MAGIC_LINK,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        db.commit()
    print("PASS: isolated synthetic browser account and customer token prepared")
except Exception as error:
    print(f"FAIL: browser fixture ({type(error).__name__})")
    raise SystemExit(1) from None
finally:
    engine.dispose()

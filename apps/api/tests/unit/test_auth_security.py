import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from sinegor.core.config import Settings
from sinegor.modules.auth.security import (
    HASHER,
    csrf_token,
    secret_hash,
    valid_csrf,
    verify_password,
)


def test_argon2id_password_and_opaque_hashes():
    stored = HASHER.hash("a sufficiently long password")
    assert stored.startswith("$argon2id$")
    assert verify_password("a sufficiently long password", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("wrong", "invalid_hash")
    assert len(secret_hash("opaque secret")) == 64
    assert "opaque secret" not in secret_hash("opaque secret")


def test_csrf_is_signed_expiring_and_bound_to_session():
    token = csrf_token("key", "session1", now=100)
    assert valid_csrf(token, "key", "session1", ttl=60, now=159)
    assert not valid_csrf(token, "key", "session1", ttl=60, now=160)
    assert not valid_csrf(token, "wrong_key", "session1", ttl=60, now=100)
    assert not valid_csrf(token, "key", "session2", ttl=60, now=100)
    assert not valid_csrf(token, "key", "session1", ttl=60, now=99)
    assert not valid_csrf("forged", "key", "session1", ttl=60, now=100)


@pytest.mark.parametrize(
    "values",
    [
        {"session_secret": "short"},
        {"auth_encryption_key": "not-a-fernet-key"},
        {"public_origin": "https://example.ru/path"},
        {"app_env": "production", "public_origin": "https://example.ru"},
    ],
)
def test_invalid_auth_configuration_rejected(values):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, database_url="postgresql+psycopg://u:secure@localhost/db", **values
        )


def test_valid_production_auth_configuration():
    settings = Settings(
        _env_file=None,
        app_env="production",
        public_origin="https://example.ru",
        database_url="postgresql+psycopg://u:secure@localhost/db",
        session_secret="random-session-key-" * 4,
        auth_encryption_key=Fernet.generate_key().decode(),
    )
    assert settings.session_cookie_name.startswith("__Host-")


def test_blank_optional_auth_settings_allow_development_templates():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        session_secret="",
        auth_encryption_key="",
        smtp_from="",
        smtp_password="",
    )
    assert settings.session_secret is None and settings.auth_encryption_key is None
    assert settings.smtp_from is None and settings.smtp_password is None

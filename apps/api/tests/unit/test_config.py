import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from sinegor.core.config import Settings, load_settings

URL = "postgresql+psycopg://user:private_password@localhost:5432/sinegor_test"


def test_env_file_and_environment_precedence(tmp_path, monkeypatch):
    env = tmp_path / "api.env"
    env.write_text(f"APP_ENV=test\nDATABASE_URL={URL}\nLOG_LEVEL=WARNING\n")
    monkeypatch.setenv("SINEGOR_ENV_FILE", str(env))
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = load_settings()
    assert settings.app_env == "test"
    assert settings.log_level == "ERROR"
    assert "private_password" not in repr(settings)


@pytest.mark.parametrize("url", ["sqlite:///test.db", "postgresql://localhost/test", "invalid"])
def test_non_postgres_or_wrong_driver_rejected(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


def test_invalid_secret_is_not_in_error():
    secret = "invalid://private_password"
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, database_url=secret)
    assert secret not in str(exc.value)


def test_database_url_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "changes",
    [
        {"public_origin": "http://example.ru"},
        {"log_level": "DEBUG"},
        {"database_url": "postgresql+psycopg://u:CHANGE_ME@localhost/test"},
    ],
)
def test_unsafe_production_configuration_rejected(changes):
    values = dict(
        app_env="production",
        database_url=URL,
        public_origin="https://example.ru",
        session_secret="test-secret-" * 4,
        auth_encryption_key=Fernet.generate_key().decode(),
    )
    values.update(changes)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """Developer dotenv and shell variables must not change unit test behaviour."""
    for name in (
        "DATABASE_URL",
        "APP_ENV",
        "PUBLIC_ORIGIN",
        "LOG_LEVEL",
        "DB_CONNECT_TIMEOUT",
        "SESSION_SECRET",
        "AUTH_ENCRYPTION_KEY",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "AUTH_IP_LIMIT",
        "AUTH_ACCOUNT_LIMIT",
        "MAGIC_LINK_TTL_SECONDS",
        "SESSION_TTL_SECONDS",
        "ADMIN_SESSION_TTL_SECONDS",
        "CSRF_TTL_SECONDS",
        "AUTH_RATE_WINDOW_SECONDS",
        "AGREEMENT_STORAGE_DIR",
        "AGREEMENT_MAX_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SINEGOR_ENV_FILE", "/dev/null")

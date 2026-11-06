import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """Developer dotenv and shell variables must not change unit test behaviour."""
    for name in (
        "YANDEX_DISK_TOKEN",
        "YANDEX_DISK_ROOT",
        "YANDEX_DISK_TIMEOUT",
        "YANDEX_DISK_TEST_ROOT",
        "DATABASE_URL",
        "APP_ENV",
        "PUBLIC_ORIGIN",
        "LOG_LEVEL",
        "DB_CONNECT_TIMEOUT",
        "SESSION_SECRET",
        "AUTH_ENCRYPTION_KEY",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USE_SSL",
        "SMTP_TIMEOUT",
        "SMTP_FROM_EMAIL",
        "SMTP_FROM_NAME",
        "NOTIFICATION_ADMIN_EMAIL",
        "NOTIFICATION_RETRY_BASE_SECONDS",
        "NOTIFICATION_RETRY_MAX_SECONDS",
        "NOTIFICATION_RETRY_JITTER",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ADMIN_CHAT_ID",
        "TELEGRAM_TIMEOUT",
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

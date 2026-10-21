import json

import pytest

from sinegor.core.config import Settings
from sinegor.integrations.telegram.client import TelegramDeliveryError, TelegramNotifier


def settings():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        telegram_bot_token="123:private-token",
        telegram_admin_chat_id="123456",
        telegram_timeout=7,
    )


def test_telegram_plain_text_and_disabled_preview():
    calls = []

    def transport(target, payload, timeout):
        calls.append((target, json.loads(payload), timeout))
        return 200, b'{"ok":true}'

    TelegramNotifier(settings(), transport).send("Email: a@example.ru <script>")
    target, payload, timeout = calls[0]
    assert target == "/bot123:private-token/sendMessage" and timeout == 7
    assert payload["chat_id"] == "123456"
    assert payload["text"] == "Email: a@example.ru <script>"
    assert "parse_mode" not in payload
    assert payload["link_preview_options"] == {"is_disabled": True}
    assert "private-token" not in repr(settings())
    assert "123456" not in repr(settings())


@pytest.mark.parametrize(
    "status,body",
    [
        (401, b'{"ok":false,"description":"private-token"}'),
        (500, b"private-token"),
        (302, b"{}"),
        (200, b"[]"),
        (200, b'{"ok":false}'),
    ],
)
def test_telegram_errors_never_expose_server_response(status, body):
    with pytest.raises(TelegramDeliveryError) as error:
        TelegramNotifier(settings(), lambda *args: (status, body)).send("request")
    assert "private-token" not in str(error.value)


def test_telegram_rate_limit_is_available_for_retry():
    notifier = TelegramNotifier(
        settings(),
        lambda *args: (
            429,
            b'{"ok":false,"parameters":{"retry_after":120}}',
        ),
    )
    with pytest.raises(TelegramDeliveryError) as error:
        notifier.send("request")
    assert error.value.retry_after == 120


def test_telegram_transport_exception_is_sanitized():
    def failed(*args):
        raise OSError("private-token")

    with pytest.raises(TelegramDeliveryError) as error:
        TelegramNotifier(settings(), failed).send("request")
    assert "private-token" not in str(error.value)


def test_telegram_missing_configuration_and_oversize_fail_without_network():
    empty = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@localhost/db")

    def unexpected(*args):
        pytest.fail("Unexpected network call")

    for config, text in [(empty, "request"), (settings(), "x" * 4097)]:
        with pytest.raises(TelegramDeliveryError):
            TelegramNotifier(config, unexpected).send(text)

import json
import smtplib
from unittest.mock import patch

import pytest

from sinegor.core.config import Settings
from sinegor.integrations.email.smtp import MailDeliveryError, SMTPAuthMailer
from sinegor.integrations.telegram.client import TelegramDeliveryError, TelegramNotifier


def settings():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        smtp_username="synthetic",
        smtp_password="synthetic",
        smtp_from="sender@example.ru",
        telegram_bot_token="123:synthetic",
        telegram_admin_chat_id="123",
    )


@pytest.mark.parametrize(
    "code,permanent",
    [(421, False), (450, False), (451, False), (535, True), (550, True), (554, True)],
)
@pytest.mark.parametrize("operation", ["connect", "recipient", "data", "refused"])
def test_smtp_classifies_protocol_codes_without_leaking_response(code, permanent, operation):
    private = b"private@example.ru synthetic-secret"
    with patch("sinegor.integrations.email.smtp.smtplib.SMTP_SSL") as smtp:
        connection = smtp.return_value.__enter__.return_value
        connection.send_message.return_value = {}
        if operation == "connect":
            smtp.side_effect = smtplib.SMTPConnectError(code, private)
        elif operation == "recipient":
            connection.send_message.side_effect = smtplib.SMTPRecipientsRefused(
                {"private@example.ru": (code, private)}
            )
        elif operation == "data":
            connection.send_message.side_effect = smtplib.SMTPDataError(code, private)
        else:
            connection.send_message.return_value = {"private@example.ru": (code, private)}
        with pytest.raises(MailDeliveryError) as error:
            SMTPAuthMailer(settings()).send_result_ready("private@example.ru", 217)
    assert error.value.permanent is permanent
    assert "private@example.ru" not in str(error.value)
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize(
    "code,permanent",
    [
        (400, True),
        (401, True),
        (403, True),
        (404, True),
        (408, False),
        (429, False),
        (500, False),
        (503, False),
    ],
)
def test_telegram_classifies_codes_and_keeps_long_retry_after(code, permanent):
    body = json.dumps(
        {
            "ok": False,
            "error_code": code,
            "description": "private@example.ru",
            "parameters": {"retry_after": 172800},
        }
    ).encode()
    with pytest.raises(TelegramDeliveryError) as error:
        TelegramNotifier(settings(), lambda *a: (code, body)).send("notice")
    assert error.value.permanent is permanent
    assert error.value.retry_after == 172800
    assert "private@example.ru" not in str(error.value)

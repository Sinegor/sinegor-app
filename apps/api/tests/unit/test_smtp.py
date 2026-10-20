from unittest.mock import patch

import pytest

from sinegor.core.config import Settings
from sinegor.integrations.email.smtp import MailDeliveryError, SMTPAuthMailer


def test_smtp_auth_message_and_tls():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        smtp_username="sender@example.ru",
        smtp_password="app_password",
        smtp_from="sender@example.ru",
    )
    with patch("sinegor.integrations.email.smtp.smtplib.SMTP_SSL") as smtp:
        connection = smtp.return_value.__enter__.return_value
        connection.send_message.return_value = {}
        SMTPAuthMailer(settings).send_login_link(
            "client@example.ru", "https://example.ru/auth#token=secret"
        )
        assert smtp.call_args.args == ("smtp.yandex.ru", 465)
        assert smtp.call_args.kwargs["context"].check_hostname
        connection.login.assert_called_once_with("sender@example.ru", "app_password")
        message = connection.send_message.call_args.args[0]
        assert message["To"] == "client@example.ru"
        assert "#token=secret" in message.get_content()


def test_smtp_is_fail_closed_without_credentials():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@localhost/db")
    with pytest.raises(MailDeliveryError):
        SMTPAuthMailer(settings).send_login_link(
            "client@example.ru", "https://example.ru/auth#token=secret"
        )

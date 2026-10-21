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


def test_result_notification_uses_tls_and_contains_order_reference():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        public_origin="https://example.ru",
        smtp_username="sender@example.ru",
        smtp_password="app_password",
        smtp_from="sender@example.ru",
    )
    with patch("sinegor.integrations.email.smtp.smtplib.SMTP_SSL") as smtp:
        connection = smtp.return_value.__enter__.return_value
        connection.send_message.return_value = {}
        SMTPAuthMailer(settings).send_result_ready("client@example.ru", 217)
        message = connection.send_message.call_args.args[0]
        assert message["To"] == "client@example.ru"
        assert "217" in message["Subject"]
        assert "14 календарных дней" in message.get_content()
        assert "https://example.ru/customer/orders" in message.get_content()
        assert smtp.call_args.kwargs["context"].check_hostname


def test_result_notification_refused_recipient_is_a_delivery_failure():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        smtp_username="sender@example.ru",
        smtp_password="app_password",
        smtp_from="sender@example.ru",
    )
    with patch("sinegor.integrations.email.smtp.smtplib.SMTP_SSL") as smtp:
        smtp.return_value.__enter__.return_value.send_message.return_value = {
            "client@example.ru": (550, b"refused")
        }
        with pytest.raises(MailDeliveryError):
            SMTPAuthMailer(settings).send_result_ready("client@example.ru", 217)


def test_smtp_starttls_and_configurable_sender_are_account_independent(monkeypatch):
    monkeypatch.setenv("SMTP_FROM_EMAIL", "personal@yandex.ru")
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        smtp_host="mail.example.ru",
        smtp_port=587,
        smtp_use_ssl=False,
        smtp_timeout=8,
        smtp_username="login",
        smtp_password="password",
        smtp_from_name="Имя исполнителя",
    )
    with patch("sinegor.integrations.email.smtp.smtplib.SMTP") as smtp:
        connection = smtp.return_value.__enter__.return_value
        connection.send_message.return_value = {}
        SMTPAuthMailer(settings).send_agreement_notice(
            "client@example.ru", 217, "agreement_initial"
        )
        assert smtp.call_args.args == ("mail.example.ru", 587)
        assert smtp.call_args.kwargs["timeout"] == 8
        assert connection.starttls.call_args.kwargs["context"].check_hostname
        names = [call[0] for call in connection.method_calls]
        assert names.index("starttls") < names.index("login") < names.index("send_message")
        message = connection.send_message.call_args.args[0]
        assert message["From"].addresses[0].addr_spec == "personal@yandex.ru"
        assert message["From"].addresses[0].display_name == "Имя исполнителя"
        assert "217" in message["Subject"]
    monkeypatch.setenv("SMTP_FROM_EMAIL", "corporate@example.ru")
    corporate = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@localhost/db")
    assert corporate.smtp_from == "corporate@example.ru"


def test_smtp_legacy_sender_and_safe_errors(monkeypatch):
    monkeypatch.setenv("SMTP_FROM", "legacy@example.ru")
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        smtp_username="user",
        smtp_password="private-password",
    )
    assert settings.smtp_from == "legacy@example.ru"
    with patch(
        "sinegor.integrations.email.smtp.smtplib.SMTP_SSL", side_effect=OSError("private-password")
    ):
        with pytest.raises(MailDeliveryError) as error:
            SMTPAuthMailer(settings).send_result_ready("client@example.ru", 217)
    assert "private-password" not in str(error.value)


@pytest.mark.parametrize("field", ["smtp_host", "smtp_from_name", "smtp_username"])
def test_smtp_rejects_control_characters(field):
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://u:p@localhost/db",
            **{field: "injected\r\nheader"},
        )

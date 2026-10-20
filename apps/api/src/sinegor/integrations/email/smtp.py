"""Minimal outgoing authentication mail adapter; no logging of message content."""

import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from sinegor.core.config import Settings


class MailDeliveryError(Exception):
    pass


class AuthMailer(Protocol):
    def send_login_link(self, recipient: str, link: str) -> None: ...


class SMTPAuthMailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send_login_link(self, recipient: str, link: str) -> None:
        settings = self.settings
        if not all((settings.smtp_username, settings.smtp_password, settings.smtp_from)):
            raise MailDeliveryError("SMTP is not configured")
        message = EmailMessage()
        message["From"] = str(settings.smtp_from)
        message["To"] = recipient
        message["Subject"] = "SINEGOR — вход в личный кабинет"
        message.set_content(
            "Для входа откройте одноразовую ссылку:\n"
            + link
            + f"\nСсылка действует {settings.magic_link_ttl_seconds // 60} мин. "
            "Если вы не запрашивали вход, проигнорируйте письмо."
        )
        try:
            with smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                context=ssl.create_default_context(),
                timeout=10,
            ) as smtp:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
                if smtp.send_message(message):
                    raise MailDeliveryError("SMTP refused the recipient")
        except (smtplib.SMTPException, OSError) as exc:
            raise MailDeliveryError("SMTP delivery failed") from exc

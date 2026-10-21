"""Account-independent SMTP adapter; credentials and sender come only from settings."""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol

from sinegor.core.config import Settings


class MailDeliveryError(Exception):
    pass


class AuthMailer(Protocol):
    def send_login_link(self, recipient: str, link: str) -> None: ...


class OrderMailer(Protocol):
    def send_result_ready(self, recipient: str, order_number: int) -> None: ...


class SMTPAuthMailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send_login_link(self, recipient: str, link: str) -> None:
        settings = self.settings
        message = EmailMessage()
        message["From"] = self._sender()
        message["To"] = recipient
        message["Subject"] = "SINEGOR — вход в личный кабинет"
        message.set_content(
            "Для входа откройте одноразовую ссылку:\n"
            + link
            + f"\nСсылка действует {settings.magic_link_ttl_seconds // 60} мин. "
            "Если вы не запрашивали вход, проигнорируйте письмо."
        )
        self._send(message)

    def send_result_ready(self, recipient: str, order_number: int) -> None:
        message = EmailMessage()
        message["From"] = self._sender()
        message["To"] = recipient
        message["Subject"] = f"SINEGOR — результат заказа №{order_number} готов"
        message.set_content(
            f"Результат заказа №{order_number} размещён в папке заказа на Яндекс Диске.\n"
            f"Личный кабинет: {str(self.settings.public_origin).rstrip('/')}/customer/orders\n"
            "Заказ будет завершён через 14 календарных дней после этого уведомления.\n"
            "Для уточнений ответьте исполнителю по электронной почте."
        )
        self._send(message)

    def _sender(self) -> str:
        return formataddr((self.settings.smtp_from_name, str(self.settings.smtp_from or "")))

    def send_agreement_notice(self, recipient: str, order_number: int, kind: str) -> None:
        notices = {
            "agreement_initial": "Соглашение доступно для подписания",
            "agreement_returned": "Подписанное соглашение поступило на проверку",
            "agreement_approved": "Подписанное соглашение подтверждено",
            "agreement_rejected": "Соглашение требует повторного подписания",
        }
        message = EmailMessage()
        message["From"] = self._sender()
        message["To"] = recipient
        message["Subject"] = f"SINEGOR — {notices[kind]}, заказ №{order_number}"
        section = "admin/orders" if kind == "agreement_returned" else "customer/orders"
        message.set_content(
            f"{notices[kind]}. Заказ №{order_number}.\n"
            "Подробности в личном кабинете: "
            f"{str(self.settings.public_origin).rstrip('/')}/{section}\n"
        )
        self._send(message)

    def _send(self, message: EmailMessage) -> None:
        settings = self.settings
        if not all((settings.smtp_username, settings.smtp_password, settings.smtp_from)):
            raise MailDeliveryError("SMTP is not configured")
        try:
            context = ssl.create_default_context()
            if settings.smtp_use_ssl:
                connection = smtplib.SMTP_SSL(
                    settings.smtp_host,
                    settings.smtp_port,
                    context=context,
                    timeout=settings.smtp_timeout,
                )
            else:
                connection = smtplib.SMTP(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.smtp_timeout,
                )
            with connection as smtp:
                if not settings.smtp_use_ssl:
                    smtp.ehlo()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
                if smtp.send_message(message):
                    raise MailDeliveryError("SMTP refused the recipient")
        except (smtplib.SMTPException, OSError, ValueError):
            raise MailDeliveryError("SMTP delivery failed") from None

"""Account-independent SMTP adapter; credentials and sender come only from settings."""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol

from sinegor.core.config import Settings


class MailDeliveryError(Exception):
    def __init__(self, message="SMTP delivery failed", *, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


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

    def send_materials_deleted(self, recipient: str, order_number: int) -> None:
        message = EmailMessage()
        message["From"] = self._sender()
        message["To"] = recipient
        message["Subject"] = f"SINEGOR — материалы заказа №{order_number} удалены"
        message.set_content(
            f"Папка заказа №{order_number} на Яндекс Диске удалена окончательно, "
            "без перемещения в корзину. Исходные материалы и результаты удалены.\n"
            "Подписанное соглашение и история заказа сохранены.\n"
            f"Личный кабинет: {str(self.settings.public_origin).rstrip('/')}/customer/orders\n"
        )
        self._send(message)

    def send_access_notice(self, recipient: str, reason: str | None) -> None:
        message = EmailMessage()
        message["From"] = self._sender()
        message["To"] = recipient
        blocked = reason is not None
        message["Subject"] = "SINEGOR — " + (
            "доступ заблокирован" if blocked else "доступ восстановлен"
        )
        message.set_content(
            "Доступ к личному кабинету заблокирован.\nПричина: " + reason
            if blocked
            else "Доступ к личному кабинету восстановлен. "
            "Для входа запросите новую одноразовую ссылку.\n"
            + str(self.settings.public_origin).rstrip("/")
            + "/auth/login"
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

    def send_consultation_notice(
        self, recipient: str, email: str, phone: str | None = None
    ) -> None:
        message = EmailMessage()
        message["From"] = self._sender()
        message["To"] = recipient
        message["Subject"] = "SINEGOR — заявка на консультацию"
        text = "Поступила новая заявка на консультацию.\nEmail: " + email
        if phone:
            text += "\nТелефон: " + phone
        message.set_content(text)
        self._send(message)

    def _send(self, message: EmailMessage) -> None:
        settings = self.settings
        if not all((settings.smtp_username, settings.smtp_password, settings.smtp_from)):
            raise MailDeliveryError("SMTP is not configured", permanent=True)
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
                refused = smtp.send_message(message)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
        except smtplib.SMTPRecipientsRefused as exc:
            # Keep only the reply class; server text and recipient keys are private.
            permanent = bool(exc.recipients) and all(
                500 <= reply[0] < 600 for reply in exc.recipients.values()
            )
            raise MailDeliveryError(permanent=permanent) from None
        except smtplib.SMTPResponseException as exc:
            raise MailDeliveryError(permanent=500 <= exc.smtp_code < 600) from None
        except (smtplib.SMTPNotSupportedError, ValueError):
            raise MailDeliveryError(permanent=True) from None
        except (smtplib.SMTPException, OSError):
            # A timeout may follow provider acceptance: the outcome is unknown.
            raise MailDeliveryError() from None

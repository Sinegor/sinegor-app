"""Server-only Telegram calls. Never log the token-bearing request URL or response."""

import json
from http.client import HTTPException, HTTPSConnection

from sinegor.core.config import Settings


class TelegramDeliveryError(Exception):
    def __init__(self, retry_after: int | None = None, *, permanent: bool = False):
        super().__init__("Telegram delivery failed")
        self.retry_after = retry_after
        self.permanent = permanent


def https_request(target: str, payload: bytes, timeout: int) -> tuple[int, bytes]:
    connection = HTTPSConnection("api.telegram.org", timeout=timeout)
    try:
        connection.request("POST", target, payload, {"Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read(65537)
        if len(body) > 65536:
            raise TelegramDeliveryError()
        return response.status, body
    except (OSError, HTTPException, ValueError):
        raise TelegramDeliveryError() from None
    finally:
        connection.close()


class TelegramNotifier:
    def __init__(self, settings: Settings, transport=https_request):
        self.settings = settings
        self._transport = transport

    def send(self, text: str) -> None:
        token = self.settings.telegram_bot_token
        chat = self.settings.telegram_admin_chat_id
        if token is None or chat is None:
            raise TelegramDeliveryError(permanent=True)
        if len(text) > 4096:
            raise TelegramDeliveryError(permanent=True)
        try:
            status, body = self._transport(
                "/bot" + token.get_secret_value() + "/sendMessage",
                json.dumps(
                    {
                        "chat_id": chat.get_secret_value(),
                        "text": text,
                        "link_preview_options": {"is_disabled": True},
                    }
                ).encode(),
                self.settings.telegram_timeout,
            )
            try:
                data = json.loads(body)
            except (ValueError, UnicodeError):
                raise TelegramDeliveryError(
                    permanent=400 <= status < 500 and status not in {408, 429}
                ) from None
            if not isinstance(data, dict):
                raise ValueError
            if status == 200 and data.get("ok") is True:
                return
            parameters = data.get("parameters")
            delay = parameters.get("retry_after") if isinstance(parameters, dict) else None
            code = data.get("error_code", status)
            if type(code) is not int:
                code = status
            raise TelegramDeliveryError(
                delay if type(delay) is int and 0 < delay <= 2147483647 else None,
                permanent=400 <= code < 500 and code not in {408, 429},
            )
        except TelegramDeliveryError:
            raise
        except Exception:
            raise TelegramDeliveryError() from None

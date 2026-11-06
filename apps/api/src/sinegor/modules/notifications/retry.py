"""Retry policy for the existing outbox; dates are anchored to the original event."""

import random
from datetime import timedelta

from sqlalchemy import case

from sinegor.core.config import Settings
from sinegor.modules.notifications.models import Notification

CONSULTATION_KINDS = ("consultation", "consultation_telegram")
TELEGRAM_KINDS = ("consultation_telegram", "deletion_due")


def deadline(item: Notification):
    return item.created_at + timedelta(days=3 if item.kind in CONSULTATION_KINDS else 7)


def deadline_expression():
    return Notification.created_at + case(
        (Notification.kind.in_(CONSULTATION_KINDS), timedelta(days=3)),
        else_=timedelta(days=7),
    )


def retry_delay(settings: Settings, attempt: int) -> float:
    # Bounded exponent avoids overflow for old rows with many attempts.
    base = min(
        settings.notification_retry_max_seconds,
        settings.notification_retry_base_seconds * 2 ** min(attempt - 1, 17),
    )
    return min(
        settings.notification_retry_max_seconds,
        base
        * random.uniform(
            1 - settings.notification_retry_jitter, 1 + settings.notification_retry_jitter
        ),
    )

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sinegor.core.config import Settings
from sinegor.modules.notifications.models import Notification
from sinegor.modules.notifications.retry import deadline, retry_delay


def settings(**values):
    return Settings(_env_file=None, database_url="postgresql+psycopg://u:p@localhost/db", **values)


@pytest.mark.parametrize("fraction", [0, 0.5, 1])
@pytest.mark.parametrize(
    "attempt,base", [(1, 1800), (2, 3600), (3, 7200), (8, 86400), (5000, 86400)]
)
def test_default_jitter_bounds_and_cap(monkeypatch, fraction, attempt, base):
    monkeypatch.setattr(
        "sinegor.modules.notifications.retry.random.uniform",
        lambda low, high: low + (high - low) * fraction,
    )
    value = retry_delay(settings(), attempt)
    assert value == pytest.approx(min(86400, base * (0.8 + 0.4 * fraction)))


def test_configurable_retry_schedule(monkeypatch):
    config = settings(
        notification_retry_base_seconds=60,
        notification_retry_max_seconds=600,
        notification_retry_jitter=0,
    )
    assert [retry_delay(config, n) for n in range(1, 7)] == [60, 120, 240, 480, 600, 600]


@pytest.mark.parametrize(
    "key,value",
    [
        ("notification_retry_base_seconds", 0),
        ("notification_retry_max_seconds", 86401),
        ("notification_retry_jitter", 0.21),
        ("notification_retry_jitter", -0.01),
    ],
)
def test_retry_config_validation(key, value):
    with pytest.raises(ValidationError):
        settings(**{key: value})


@pytest.mark.parametrize(
    "kind,days",
    [
        ("consultation", 3),
        ("consultation_telegram", 3),
        ("magic_link", 7),
        ("result_ready", 7),
        ("deletion_due", 7),
    ],
)
def test_retry_lifetime_anchored_to_original_event(kind, days):
    created = datetime(2026, 11, 1, tzinfo=UTC)
    assert deadline(Notification(kind=kind, created_at=created)) == created + timedelta(days=days)

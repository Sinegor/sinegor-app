"""Calendar retention anniversaries, independent of scheduler execution dates."""

from calendar import monthrange
from datetime import UTC, datetime


def anniversary(start: datetime, years: int) -> datetime:
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("Retention timestamps must include a timezone")
    start = start.astimezone(UTC)
    year = start.year + years
    return start.replace(year=year, day=min(start.day, monthrange(year, start.month)[1]))

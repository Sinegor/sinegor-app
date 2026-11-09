from datetime import UTC, datetime

import pytest


def test_calendar_anniversaries_keep_time_and_clamp_leap_day():
    from sinegor.modules.retention.calendar import anniversary

    assert anniversary(datetime(2024, 2, 29, 12, 30, tzinfo=UTC), 5) == datetime(
        2029, 2, 28, 12, 30, tzinfo=UTC
    )
    assert anniversary(datetime(2023, 3, 1, tzinfo=UTC), 5) == datetime(2028, 3, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        anniversary(datetime(2024, 2, 29), 3)

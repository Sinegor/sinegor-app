from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import test_auth as helpers
from sqlalchemy import func, inspect, select
from test_auth import post

pytestmark = pytest.mark.integration
auth = helpers.auth
URL = "/api/analytics/consent"


def event(**changes):
    return (
        dict(event_id=str(uuid4()), browser_id=str(uuid4()), event_type="grant", text_version="1")
        | changes
    )


def test_grant_and_withdraw_are_committed_idempotently_with_server_time(auth):
    payload = event()
    before = datetime.now(UTC)
    response = post(auth, URL, payload)
    assert response.status_code == 200
    body = response.json()
    recorded = datetime.fromisoformat(body["recorded_at"])
    assert before <= recorded <= datetime.now(UTC)
    assert body == dict(
        event_id=payload["event_id"],
        recorded_at=body["recorded_at"],
        event_type="grant",
        text_version="1",
    )
    from sinegor.modules.analytics.models import AnalyticsConsentEvent

    assert auth.db.get(AnalyticsConsentEvent, payload["event_id"]).browser_id == UUID(
        payload["browser_id"]
    )
    assert post(auth, URL, payload).json() == body
    assert post(auth, URL, payload | {"event_type": "withdraw"}).status_code == 409
    withdrawal = event(
        browser_id=payload["browser_id"], event_type="withdraw", text_version="old-1"
    )
    assert post(auth, URL, withdrawal).status_code == 200
    assert auth.db.scalar(select(func.count()).select_from(AnalyticsConsentEvent)) == 2
    columns = {c["name"] for c in inspect(auth.db.bind).get_columns("analytics_consent_events")}
    assert columns == {"event_id", "browser_id", "event_type", "text_version", "recorded_at"}
    assert auth.client.get(URL).status_code == 405
    assert auth.client.get("/api/admin/analytics/consent").status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"text_version": "0"},
        {"text_version": ""},
        {"text_version": "x" * 65},
        {"event_type": "rejected"},
        {"event_id": "invalid"},
        {"browser_id": "invalid"},
        {"browser_id": "00000000-0000-0000-0000-000000000000"},
        {"email": "private@example.test"},
        {"ip": "192.0.2.1"},
        {"user_id": str(uuid4())},
        {"recorded_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_reject_invalid_or_excess_personal_fields(auth, change):
    assert post(auth, URL, event(**change)).status_code == 422


def test_origin_and_csrf_are_required(auth):
    payload = event()
    assert auth.client.post(URL, json=payload).status_code == 403
    csrf = auth.client.get("/api/auth/csrf").json()["csrf_token"]
    assert (
        auth.client.post(
            URL, json=payload, headers={"Origin": "https://other.test", "X-CSRF-Token": csrf}
        ).status_code
        == 403
    )
    assert post(auth, URL, payload).status_code == 200


def test_rate_limit_survives_browser_rotation_and_is_not_a_journal_read(auth):
    auth.app.state.settings = auth.settings.model_copy(
        update={"auth_ip_limit": 2, "auth_account_limit": 2}
    )
    assert post(auth, URL, event()).status_code == 200
    assert post(auth, URL, event()).status_code == 200
    response = post(auth, URL, event())
    assert response.status_code == 429 and "retry-after" in response.headers


def test_cleanup_180_day_boundary_preserves_new_events(auth):
    assert post(auth, URL, event()).status_code == 200
    from sinegor.modules.analytics.models import AnalyticsConsentEvent
    from sinegor.modules.analytics.service import purge_events

    now = datetime(2026, 11, 5, 12, tzinfo=UTC)
    cutoff = now - timedelta(days=180)
    old = AnalyticsConsentEvent(
        event_id=uuid4(),
        browser_id=uuid4(),
        event_type="grant",
        text_version="1",
        recorded_at=cutoff - timedelta(microseconds=1),
    )
    boundary = AnalyticsConsentEvent(
        event_id=uuid4(),
        browser_id=uuid4(),
        event_type="withdraw",
        text_version="1",
        recorded_at=cutoff,
    )
    auth.db.add_all([old, boundary])
    auth.db.commit()
    old_id = old.event_id
    assert purge_events(auth.db, now=now) == 1
    auth.db.expire_all()
    assert auth.db.get(AnalyticsConsentEvent, old_id) is None
    assert auth.db.get(AnalyticsConsentEvent, boundary.event_id) is not None

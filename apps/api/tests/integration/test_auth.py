from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from sinegor.core.config import Settings
from sinegor.db.session import get_session
from sinegor.db.types import ServiceType, TokenPurpose
from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.main import create_app
from sinegor.modules.auth.models import AdminUser, AuthRateLimit, AuthToken, Session
from sinegor.modules.auth.security import HASHER, new_secret, secret_hash
from sinegor.modules.auth.service import provision_admin
from sinegor.modules.customers.models import Customer
from sinegor.modules.orders.models import Order

pytestmark = pytest.mark.integration
PASSWORD = "testing-password-only-123"


class MemoryMailer:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send_login_link(self, recipient, link):
        if self.fail:
            raise MailDeliveryError("test SMTP failure")
        self.messages.append((recipient, link))

    def token(self):
        return parse_qs(urlsplit(self.messages[-1][1]).fragment)["token"][0]


@pytest.fixture
def auth(db_session, database_settings, request, monkeypatch):
    production = getattr(request, "param", "test") == "production"
    origin = "https://testserver" if production else "http://testserver"
    settings = Settings(
        _env_file=None,
        database_url=database_settings.database_url,
        app_env="production" if production else "test",
        log_level="INFO",
        public_origin=origin,
        session_secret="test-session-signing-key-" * 3,
        auth_encryption_key=Fernet.generate_key().decode(),
    )
    if production:
        # Cookie fixture owns the disposable schema; runtime SQL roles are tested separately.
        monkeypatch.setattr("sinegor.main.verify_runtime_permissions", lambda connection: None)
    app = create_app(settings)

    def override_db():
        yield db_session

    @contextmanager
    def background_db():
        yield db_session

    app.dependency_overrides[get_session] = override_db
    mailer = MemoryMailer()
    app.state.auth_mailer = mailer
    with TestClient(app, base_url=origin) as client:
        app.state.session_factory = background_db
        yield SimpleNamespace(
            client=client, db=db_session, settings=settings, mailer=mailer, app=app
        )


def post(auth, url, payload=None, **kwargs):
    csrf = auth.client.get("/api/auth/csrf").json()["csrf_token"]
    return auth.client.post(
        url,
        json=payload,
        headers={"Origin": str(auth.settings.public_origin).rstrip("/"), "X-CSRF-Token": csrf},
        **kwargs,
    )


@pytest.fixture
def actors(auth):
    customer = Customer(email="client@example.ru")
    other = Customer(email="other@example.ru")
    secret = pyotp.random_base32()
    admin = AdminUser(
        email="admin@example.ru",
        password_hash=HASHER.hash(PASSWORD),
        totp_secret_encrypted=Fernet(auth.settings.auth_encryption_key.get_secret_value().encode())
        .encrypt(secret.encode())
        .decode(),
    )
    order = Order(customer=customer, service_type=ServiceType.ANALYSIS)
    other_order = Order(customer=other, service_type=ServiceType.ANALYSIS)
    auth.db.add_all([admin, order, other_order])
    auth.db.commit()
    return SimpleNamespace(
        customer=customer,
        other=other,
        admin=admin,
        order=order,
        other_order=other_order,
        secret=secret,
    )


def login_customer(auth, email="client@example.ru"):
    response = post(auth, "/api/auth/magic-link/request", {"email": email})
    assert response.status_code == 202
    raw = auth.mailer.token()
    response = post(auth, "/api/auth/magic-link/verify", {"token": raw})
    assert response.status_code == 204, response.text
    return raw


def login_admin(auth, actors, code=None):
    response = post(
        auth,
        "/api/auth/admin/login",
        {
            "email": "admin@example.ru",
            "password": PASSWORD,
            "code": code or pyotp.TOTP(actors.secret).now(),
        },
    )
    assert response.status_code == 204, response.text
    return response


def test_customer_login_only_own_orders_and_logout(auth, actors):
    raw_link = login_customer(auth)
    session_cookie = auth.client.cookies.get(auth.settings.session_cookie_name)
    session = auth.db.scalar(
        select(Session).where(Session.session_hash == secret_hash(session_cookie))
    )
    token = auth.db.scalar(select(AuthToken).where(AuthToken.token_hash == secret_hash(raw_link)))
    assert token.used_at is not None
    assert session.customer_id == actors.customer.id and session.admin_id is None
    assert raw_link not in repr(token.__dict__)
    assert session_cookie not in repr(session.__dict__)
    principal = auth.client.get("/api/auth/session")
    assert principal.json()["role"] == "customer"
    own_orders = auth.client.get("/api/customer/orders").json()
    assert [row["id"] for row in own_orders] == [str(actors.order.id)]
    assert auth.client.get(f"/api/customer/orders/{actors.order.id}").status_code == 200
    assert auth.client.get(f"/api/customer/orders/{actors.other_order.id}").status_code == 404
    assert auth.client.get(f"/api/customer/orders/{uuid4()}").status_code == 404
    assert post(auth, "/api/admin/customers", {"email": "forbidden@example.ru"}).status_code == 403
    assert post(auth, "/api/auth/logout").status_code == 204
    assert auth.client.get("/api/auth/session").status_code == 401
    auth.client.cookies.set(auth.settings.session_cookie_name, session_cookie)
    assert auth.client.get("/api/auth/session").status_code == 401


def test_link_cannot_be_reused(auth, actors):
    token = login_customer(auth)
    assert post(auth, "/api/auth/magic-link/verify", {"token": token}).status_code == 401


def test_expired_and_unknown_links_rejected(auth, actors):
    raw = new_secret()
    now = datetime.now(UTC)
    auth.db.add(
        AuthToken(
            customer_id=actors.customer.id,
            token_hash=secret_hash(raw),
            purpose=TokenPurpose.MAGIC_LINK,
            created_at=now - timedelta(hours=1),
            expires_at=now - timedelta(seconds=1),
        )
    )
    auth.db.commit()
    for value in (raw, new_secret()):
        assert post(auth, "/api/auth/magic-link/verify", {"token": value}).status_code == 401
    assert auth.client.get("/api/auth/session").status_code == 401


def test_request_does_not_enumerate_accounts_or_register_unknown_email(auth, actors):
    known = post(auth, "/api/auth/magic-link/request", {"email": " CLIENT@Example.RU "})
    unknown = post(auth, "/api/auth/magic-link/request", {"email": "unknown@example.ru"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(auth.mailer.messages) == 1
    assert auth.db.scalar(select(Customer).where(Customer.email == "unknown@example.ru")) is None
    assert "token" not in known.text.lower()


def test_resend_replaces_previous_unused_link(auth, actors):
    post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email})
    previous = auth.mailer.token()
    post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email})
    current = auth.mailer.token()
    assert previous != current
    assert post(auth, "/api/auth/magic-link/verify", {"token": previous}).status_code == 401
    assert post(auth, "/api/auth/magic-link/verify", {"token": current}).status_code == 204


def test_admin_login_invitation_and_client_cannot_escalate(auth, actors):
    login_admin(auth, actors)
    assert auth.client.get("/api/auth/session").json()["role"] == "admin"
    created = post(auth, "/api/admin/customers", {"email": "new@example.ru", "display_name": "New"})
    assert created.status_code == 201, created.text
    customer_id = created.json()["id"]
    invitation = auth.mailer.token()
    assert auth.mailer.messages[-1][0] == "new@example.ru"
    assert post(auth, f"/api/admin/customers/{customer_id}/invite").status_code == 202
    assert invitation != auth.mailer.token()
    assert (
        post(auth, "/api/auth/magic-link/verify", {"token": auth.mailer.token()}).status_code == 204
    )
    assert auth.client.get("/api/auth/session").json()["role"] == "customer"
    assert post(auth, f"/api/admin/customers/{customer_id}/invite").status_code == 403


@pytest.mark.parametrize(
    "change",
    [
        {"password": "wrong"},
        {"code": "000000"},
        {"email": "unknown@example.ru"},
    ],
)
def test_admin_wrong_credentials_denied(auth, actors, change):
    payload = {
        "email": actors.admin.email,
        "password": PASSWORD,
        "code": pyotp.TOTP(actors.secret).now(),
    }
    if change.get("code") == payload["code"]:
        change = {"code": "111111"}
    payload.update(change)
    assert post(auth, "/api/auth/admin/login", payload).status_code == 401
    assert auth.client.get("/api/auth/session").status_code == 401


def test_admin_totp_cannot_be_replayed(auth, actors):
    code = pyotp.TOTP(actors.secret).now()
    login_admin(auth, actors, code=code)
    response = post(
        auth,
        "/api/auth/admin/login",
        {
            "email": actors.admin.email,
            "password": PASSWORD,
            "code": code,
        },
    )
    assert response.status_code == 401


def test_disabled_admin_and_expired_session_denied(auth, actors):
    login_admin(auth, actors)
    actors.admin.is_active = False
    auth.db.commit()
    assert auth.client.get("/api/auth/session").status_code == 401
    actors.admin.is_active = True
    login_customer(auth)
    auth.db.execute(
        update(Session).values(
            created_at=datetime.now(UTC) - timedelta(hours=2),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    auth.db.commit()
    assert auth.client.get("/api/auth/session").status_code == 401


def test_login_rotates_and_revokes_existing_session(auth, actors):
    login_customer(auth)
    previous = auth.client.cookies.get(auth.settings.session_cookie_name)
    login_customer(auth)
    current = auth.client.cookies.get(auth.settings.session_cookie_name)
    assert previous != current
    assert auth.db.scalar(
        select(Session).where(Session.session_hash == secret_hash(previous))
    ).revoked_at


@pytest.mark.parametrize("path", ["/api/customer/orders", "/api/auth/session"])
def test_anonymous_cannot_access_private_routes(auth, path):
    assert auth.client.get(path).status_code == 401


def test_csrf_missing_origin_wrong_origin_and_forgery_denied(auth, actors):
    url = "/api/auth/magic-link/request"
    body = {"email": actors.customer.email}
    assert auth.client.post(url, json=body).status_code == 403
    csrf = auth.client.get("/api/auth/csrf").json()["csrf_token"]
    for headers in (
        {"X-CSRF-Token": csrf},
        {"Origin": "https://evil.example", "X-CSRF-Token": csrf},
        {"Origin": "http://testserver", "X-CSRF-Token": "forged"},
    ):
        assert auth.client.post(url, json=body, headers=headers).status_code == 403
    assert auth.mailer.messages == []


def test_pre_login_csrf_token_does_not_authorize_authenticated_action(auth, actors):
    old_csrf = auth.client.get("/api/auth/csrf").json()["csrf_token"]
    login_customer(auth)
    auth.client.cookies.set(auth.settings.csrf_cookie_name, old_csrf)
    response = auth.client.post(
        "/api/auth/logout", headers={"Origin": "http://testserver", "X-CSRF-Token": old_csrf}
    )
    assert response.status_code == 403


def test_failed_login_attempts_remain_rate_limited(auth, actors):
    payload = {"email": actors.admin.email, "password": "wrong", "code": "000000"}
    for _ in range(auth.settings.auth_account_limit):
        assert post(auth, "/api/auth/admin/login", payload).status_code == 401
    response = post(auth, "/api/auth/admin/login", payload)
    assert response.status_code == 429 and response.headers["Retry-After"]
    assert auth.db.scalar(select(func.count()).select_from(AuthRateLimit)) == 2


def test_ip_rate_limit_ignores_forged_forwarded_header(auth, actors):
    auth.settings.auth_ip_limit = 2
    for email in ("first@example.ru", "second@example.ru", "third@example.ru"):
        csrf = auth.client.get("/api/auth/csrf").json()["csrf_token"]
        response = auth.client.post(
            "/api/auth/magic-link/request",
            json={"email": email},
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": csrf,
                "X-Forwarded-For": str(uuid4()),
            },
        )
    assert response.status_code == 429


def test_smtp_failure_keeps_public_response_generic_and_invalidates_token(auth, actors):
    auth.mailer.fail = True
    response = post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email})
    assert response.status_code == 202
    assert auth.db.scalar(select(func.count()).select_from(AuthToken)) == 0


def test_invitation_failure_can_be_retried_without_recreating_customer(auth, actors):
    login_admin(auth, actors)
    auth.mailer.fail = True
    response = post(auth, "/api/admin/customers", {"email": "retry@example.ru"})
    assert response.status_code == 503
    customer = auth.db.scalar(select(Customer).where(Customer.email == "retry@example.ru"))
    assert customer is not None
    auth.mailer.fail = False
    assert post(auth, f"/api/admin/customers/{customer.id}/invite").status_code == 202


def test_bootstrap_hashes_password_and_encrypts_verified_totp(auth):
    secret = pyotp.random_base32()
    admin = provision_admin(
        auth.db, auth.settings, "bootstrap@example.ru", PASSWORD, secret, pyotp.TOTP(secret).now()
    )
    assert admin.password_hash.startswith("$argon2id$")
    assert secret not in admin.totp_secret_encrypted
    assert admin.last_totp_step is not None


def test_cookie_flags_and_private_response_cache_control(auth, actors):
    response = login_admin(auth, actors)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("auth", ["production"], indirect=True)
def test_production_auth_uses_host_secure_cookies(auth, actors):
    response = login_admin(auth, actors)
    assert auth.settings.session_cookie_name == "__Host-sinegor_session"
    for cookie in response.headers.get_list("set-cookie"):
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert "Domain=" not in cookie and "Path=/" in cookie
    assert auth.client.get("/api/auth/session").json()["role"] == "admin"


def test_authentication_logs_never_contain_secrets_or_identity(auth, actors):
    import logging
    from io import StringIO

    from sinegor.core.logging import JsonFormatter

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("sinegor")
    logger.addHandler(handler)
    try:
        login_admin(auth, actors)
        raw_link = login_customer(auth)
        raw_cookie = auth.client.cookies.get(auth.settings.session_cookie_name)
        output = stream.getvalue()
        assert "request_completed" in output
        for secret in (PASSWORD, actors.secret, raw_link, raw_cookie, actors.customer.email):
            assert secret not in output
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_review_csrf_survives_second_tab_fetch(auth, actors):
    first = auth.client.get("/api/auth/csrf").json()["csrf_token"]
    second = auth.client.get("/api/auth/csrf")
    assert second.json()["csrf_token"] == first
    assert "set-cookie" not in second.headers
    response = auth.client.post(
        "/api/auth/magic-link/request",
        json={"email": actors.customer.email},
        headers={"Origin": "http://testserver", "X-CSRF-Token": first},
    )
    assert response.status_code == 202


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("reverse_responses", [False, True])
def test_initial_csrf_requests_allow_both_tabs(auth, actors, authenticated, reverse_responses):
    if authenticated:
        login_customer(auth)
    # Both in-flight requests contain the same cookie snapshot, without a CSRF cookie.
    pending = [auth.client.build_request("GET", "/api/auth/csrf") for _ in range(2)]
    responses = [None, None]
    for index in (1, 0) if reverse_responses else (0, 1):
        responses[index] = auth.client.send(pending[index])
    tokens = [response.json()["csrf_token"] for response in responses]
    assert tokens[0] != tokens[1]
    winner = tokens[0 if reverse_responses else 1]
    assert auth.client.cookies.get(auth.settings.csrf_cookie_name) == winner
    for token in tokens:
        response = auth.client.post(
            "/api/auth/magic-link/request",
            json={"email": actors.customer.email},
            headers={"Origin": "http://testserver", "X-CSRF-Token": token},
        )
        assert response.status_code == 202, response.text


def test_review_failed_resend_preserves_delivered_link(auth, actors):
    assert (
        post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email}).status_code
        == 202
    )
    delivered = auth.mailer.token()
    auth.mailer.fail = True
    assert (
        post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email}).status_code
        == 202
    )
    response = post(auth, "/api/auth/magic-link/verify", {"token": delivered})
    assert response.status_code == 204


def test_review_failed_creation_returns_customer_id_for_api_retry(auth, actors):
    login_admin(auth, actors)
    auth.mailer.fail = True
    created = post(auth, "/api/admin/customers", {"email": "api-retry@example.ru"})
    assert created.status_code == 503
    customer_id = created.headers["X-Customer-ID"]
    auth.mailer.fail = False
    invited = post(auth, f"/api/admin/customers/{customer_id}/invite")
    assert invited.status_code == 202
    assert auth.mailer.messages[-1][0] == "api-retry@example.ru"
    assert (
        post(auth, "/api/auth/magic-link/verify", {"token": auth.mailer.token()}).status_code == 204
    )
    assert auth.client.get("/api/auth/session").json()["id"] == customer_id


@pytest.mark.parametrize("kind", ["invalid", "expired", "another_session"])
def test_review_csrf_renews_unusable_cookie(auth, kind):
    import time

    from sinegor.modules.auth.security import csrf_token, valid_csrf

    if kind == "invalid":
        old = "forged"
    elif kind == "expired":
        old = csrf_token(
            auth.app.state.csrf_key,
            "",
            now=int(time.time()) - auth.settings.csrf_ttl_seconds,
        )
    else:
        old = csrf_token(auth.app.state.csrf_key, "another_session")
    auth.client.cookies.set(auth.settings.csrf_cookie_name, old)
    response = auth.client.get("/api/auth/csrf")
    token = response.json()["csrf_token"]
    assert token != old
    assert "set-cookie" in response.headers
    assert valid_csrf(token, auth.app.state.csrf_key, "", auth.settings.csrf_ttl_seconds)


def test_review_delayed_send_preserves_newer_delivered_link(auth, actors):
    from sinegor.modules.auth.service import issue_and_send_link

    post(auth, "/api/auth/magic-link/request", {"email": actors.customer.email})

    class DelayedMailer:
        link = None

        def send_login_link(self, recipient, link):
            self.link = link
            # Interleave a complete newer send while the earlier SMTP call is pending.
            issue_and_send_link(
                auth.db,
                auth.settings,
                auth.mailer,
                actors.customer,
                TokenPurpose.MAGIC_LINK,
            )

    delayed = DelayedMailer()
    issue_and_send_link(auth.db, auth.settings, delayed, actors.customer, TokenPurpose.MAGIC_LINK)
    earlier = parse_qs(urlsplit(delayed.link).fragment)["token"][0]
    latest = auth.mailer.token()
    assert post(auth, "/api/auth/magic-link/verify", {"token": earlier}).status_code == 401
    assert post(auth, "/api/auth/magic-link/verify", {"token": latest}).status_code == 204

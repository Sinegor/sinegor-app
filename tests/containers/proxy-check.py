"""Verify forwarded IP handling in the local Compose API container (via stdin).

Uses failed synthetic logins and aggregate counter deltas; never prints credentials,
CSRF/session cookies, rate-limit keys or SQL values.
"""

import hashlib
import hmac
import json
import os
import socket
import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.modules.auth.models import AuthRateLimit

assert os.environ.get("LOCAL_CONTAINER_CHECK") == "yes"
settings = load_settings()
assert settings.public_origin.host == "localhost" and settings.app_env == "production"
proxy = socket.gethostbyname("proxy")
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
    route.connect((proxy, 8443))
    client_ip = route.getsockname()[0]
forged_ip = "198.51.100.88"
engine = create_db_engine(settings)
factory = create_session_factory(engine)
key = settings.session_secret.get_secret_value()


def count(ip):
    digest = hmac.new(key.encode(), f"admin_login:ip:{ip}".encode(), hashlib.sha256).hexdigest()
    with factory() as db:
        row = db.get(AuthRateLimit, digest)
        cutoff = datetime.now(UTC) - timedelta(seconds=settings.auth_rate_window_seconds)
        return row.attempts if row and row.window_started_at > cutoff else 0


def failed_login(origin, email):
    client = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
    )
    with client.open(origin + "/api/auth/csrf", timeout=10) as response:
        csrf = json.load(response)["csrf_token"]
        cookie = response.headers["Set-Cookie"].split(";", 1)[0]
    request = urllib.request.Request(
        origin + "/api/auth/admin/login",
        data=json.dumps(
            {"email": email, "password": "synthetic-invalid", "code": "000000"}
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "Origin": str(settings.public_origin).rstrip("/"),
            "Cookie": cookie,
            "X-CSRF-Token": csrf,
            "X-Forwarded-For": forged_ip,
            "X-Forwarded-Proto": "https",
        },
    )
    try:
        client.open(request, timeout=10)
        raise AssertionError("Synthetic invalid login accepted")
    except urllib.error.HTTPError as response:
        assert response.status == 401


try:
    before = {ip: count(ip) for ip in (client_ip, proxy, forged_ip, "127.0.0.1")}
    failed_login("https://proxy:8443", "proxy-check@example.org")
    assert count(client_ip) == before[client_ip] + 1
    assert count(proxy) == before[proxy]
    assert count(forged_ip) == before[forged_ip]
    print("PASS: proxy replaces forged X-Forwarded-For; API counts the real client IP")
    failed_login("http://127.0.0.1:8000", "direct-check@example.org")
    assert count("127.0.0.1") == before["127.0.0.1"] + 1
    assert count(forged_ip) == before[forged_ip]
    print("PASS: API ignores forwarded headers from an untrusted direct peer")
except Exception as error:
    print(f"FAIL: forwarded-IP check ({type(error).__name__})")
    raise SystemExit(1) from None
finally:
    engine.dispose()

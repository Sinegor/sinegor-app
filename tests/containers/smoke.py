"""Run via stdin in the isolated API container; never run against working databases.

LOCAL_CONTAINER_CHECK=yes is required in the private test API env, plus the local
override that disables API egress. No credentials, tokens, PDF bytes or SQL are printed.
Use --persist after container recreation to check the original synthetic final PDF.
"""

import hashlib
import html
import http.cookiejar
import io
import json
import os
import re
import secrets
import ssl
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

import pyotp
from cryptography.fernet import Fernet
from pypdf import PdfWriter
from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.db.types import TokenPurpose
from sinegor.modules.agreements.models import Agreement
from sinegor.modules.agreements.storage import AgreementStorage
from sinegor.modules.auth.models import AdminUser, AuthToken
from sinegor.modules.auth.security import HASHER, secret_hash
from sinegor.modules.customers.models import Customer
from sinegor.modules.orders.models import Order
from sinegor.modules.security_events.permissions import verify_runtime_permissions
from sqlalchemy import select

assert os.environ.get("LOCAL_CONTAINER_CHECK") == "yes", "Not a local check environment"
settings = load_settings()
assert settings.app_env == "production"
assert str(settings.public_origin).startswith("https://localhost:"), "Not a local origin"
assert settings.smtp_password is None and settings.yandex_disk_token is None
assert settings.telegram_bot_token is None, "Real integrations must be disabled"
run_name = os.environ.get("SINEGOR_CONTAINER_CHECK_RUN", "vi0")
assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", run_name), "Invalid synthetic run name"
admin_email = f"{run_name}-admin@example.org"
customer_email = f"{run_name}@example.org"
engine = create_db_engine(settings)
factory = create_session_factory(engine)
with engine.connect() as connection:
    verify_runtime_permissions(connection)


class Browser:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        # The isolated proxy uses a disposable self-signed test certificate.
        self.client = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
        )

    def request(self, path, data=None, *, method=None, headers=None, status=200):
        headers = dict(headers or {})
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        if data is not None or method == "POST":
            token = self.request("/api/auth/csrf")[1]["csrf_token"]
            headers |= {
                "Origin": str(settings.public_origin).rstrip("/"),
                "X-CSRF-Token": token,
            }
        request = urllib.request.Request(
            "https://proxy:8443" + path, data=data, headers=headers, method=method
        )
        try:
            response = self.client.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        if response.status != status:
            template = re.sub(r"[0-9a-f-]{36}", ":id", path)
            print(f"FAIL: {template} HTTP {response.status}; expected {status}", file=sys.stderr)
            raise AssertionError("Unexpected HTTP status")
        body = response.read()
        if body and "application/json" in response.headers.get("Content-Type", ""):
            body = json.loads(body)
        return response.headers, body

    def check_cookies(self):
        cookie = next(c for c in self.cookies if c.name == "__Host-sinegor_session")
        assert cookie.secure and cookie.path == "/" and not cookie.domain_specified
        assert "HttpOnly" in cookie._rest and cookie._rest.get("SameSite") == "strict"


def synthetic_pdf(title):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": title})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def public_checks():
    anonymous = Browser()
    anonymous.request("/api/health/ready")
    anonymous.request("/api/admin/orders", status=401)
    anonymous.request("/api/customer/orders", status=401)
    anonymous.request("/api/openapi.json", status=404)
    for path in ("/", "/documents", "/auth/admin", "/auth/login"):
        _, body = anonymous.request(path)
        assert b"<!DOCTYPE html>" in body or b"<!doctype html>" in body
    print("PASS: production API readiness, closed routes/docs, SSR public/login pages")

    with urllib.request.urlopen("http://cms:1337/api/public-content/pages/home") as response:
        home = json.load(response)["data"]
    body = anonymous.request("/")[1].decode()
    assert home and html.escape(home["title"]) in body
    print("PASS: SSR contains the copied published Strapi home title")

    urls = set()

    def collect(value):
        if isinstance(value, dict):
            if isinstance(value.get("url"), str) and value["url"].startswith("/uploads/"):
                urls.add(value["url"])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    for kind in ("pages", "services", "documents", "publications"):
        with urllib.request.urlopen(f"http://cms:1337/api/public-content/{kind}") as response:
            collect(json.load(response)["data"])
    assert urls, "Expected existing published media in the copied CMS"
    for url in urls:
        with urllib.request.urlopen("http://cms:1337" + url) as response:
            expected = response.read()
        assert anonymous.request(url)[1] == expected
    print(f"PASS: {len(urls)} published media files served byte-for-byte via public proxy")


def main():
    if "--persist" in sys.argv:
        with factory() as db:
            customer = db.scalar(select(Customer).where(Customer.email == customer_email))
            assert customer is not None
            order = db.scalar(select(Order).where(Order.customer_id == customer.id))
            agreement = db.scalar(select(Agreement).where(Agreement.order_id == order.id))
            assert agreement.final_pdf_key and agreement.final_sha256
            pdf, _ = AgreementStorage(settings.agreement_storage_dir).read(
                agreement.final_pdf_key, agreement.final_sha256
            )
            assert hashlib.sha256(pdf).hexdigest() == agreement.final_sha256
            assert pdf == synthetic_pdf("VI-0 signed synthetic PDF")
        print("PASS: customer, order, approved PDF bytes/hash survive recreation")
        return

    public_checks()
    if "--public" in sys.argv:
        return
    anonymous = Browser()

    password, totp = secrets.token_urlsafe(32), pyotp.random_base32()
    with factory() as db:
        assert db.scalar(select(AdminUser.id).where(AdminUser.email == admin_email)) is None, (
            "Synthetic run already exists; select a new run name or use --persist"
        )
        db.add(
            AdminUser(
                email=admin_email,
                password_hash=HASHER.hash(password),
                totp_secret_encrypted=Fernet(
                    settings.auth_encryption_key.get_secret_value().encode()
                )
                .encrypt(totp.encode())
                .decode(),
            )
        )
        db.commit()
    admin = Browser()
    admin.request(
        "/api/auth/admin/login",
        {
            "email": admin_email,
            "password": password,
            "code": pyotp.TOTP(totp).now(),
        },
        status=204,
    )
    admin.check_cookies()
    assert admin.request("/api/auth/session")[1]["role"] == "admin"
    customer_headers, _ = admin.request(
        "/api/admin/customers",
        {
            "email": customer_email,
            "display_name": "VI-0 synthetic customer",
        },
        # External channels are deliberately disabled: customer is saved, and
        # invitation failure returns its ID for a later operator retry.
        status=503,
    )
    customer_id = customer_headers["X-Customer-ID"]
    assert customer_id
    order_id = admin.request(
        "/api/admin/orders",
        {
            "customer_id": customer_id,
            "service_type": "technical_preparation",
        },
        status=201,
    )[1]["id"]
    path = f"/api/admin/orders/{order_id}/agreement"
    initial = admin.request(
        path + "/initial",
        synthetic_pdf("VI-0 initial"),
        headers={
            "Content-Type": "application/pdf",
            "X-Agreement-Revision": "0",
        },
    )[1]
    print("PASS: admin password+TOTP login, Secure cookies, customer/order creation, PDF upload")

    # Synthetic token fixture: no SMTP delivery, real token verification and session issuance.
    raw = secrets.token_urlsafe(32)
    with factory() as db:
        customer = db.get(Customer, __import__("uuid").UUID(customer_id))
        db.add(
            AuthToken(
                customer_id=customer.id,
                token_hash=secret_hash(raw),
                purpose=TokenPurpose.MAGIC_LINK,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        db.commit()
    customer = Browser()
    customer.request("/api/auth/magic-link/verify", {"token": raw}, status=204)
    customer.check_cookies()
    assert customer.request("/api/auth/session")[1]["role"] == "customer"
    customer.request("/api/admin/orders", status=403)
    with factory() as db:
        other = Customer(email=f"{run_name}-other@example.org", display_name="Other synthetic")
        db.add(other)
        db.commit()
        other_customer_id = str(other.id)
    other_order_id = admin.request(
        "/api/admin/orders",
        {"customer_id": other_customer_id, "service_type": "technical_preparation"},
        status=201,
    )[1]["id"]
    customer.request(f"/api/customer/orders/{other_order_id}", status=404)
    customer.request(f"/api/customer/orders/{other_order_id}/agreement", status=404)
    print("PASS: customer cannot access another customer's order or agreement")
    customer_path = f"/api/customer/orders/{order_id}/agreement"
    assert customer.request(customer_path + "/initial")[1] == synthetic_pdf("VI-0 initial")
    signed = synthetic_pdf("VI-0 signed synthetic PDF")
    returned = customer.request(
        customer_path + "/returned",
        signed,
        headers={
            "Content-Type": "application/pdf",
            "X-Agreement-Revision": str(initial["revision"]),
        },
    )[1]
    approved = admin.request(path + "/approve", {"revision": returned["revision"]})[1]
    assert approved["final_sha256"] == hashlib.sha256(signed).hexdigest()
    headers, final = customer.request(customer_path + "/final")
    assert final == signed and "attachment" in headers["Content-Disposition"]
    assert headers["Cache-Control"] == "no-store"
    customer.request(customer_path + "/initial", status=404)
    anonymous.request(customer_path + "/final", status=401)
    print("PASS: customer magic login, PDF return/approval/download, cleanup and private access")
    for browser in (customer, admin):
        browser.request("/api/auth/logout", method="POST", status=204)
        browser.request("/api/auth/session", status=401)
    print("PASS: both sessions revoked by logout")


try:
    main()
except Exception as error:
    # Exceptions can contain SQL/response data. Emit only a safe type.
    trace = error.__traceback__
    while trace.tb_next:
        trace = trace.tb_next
    print(
        f"FAIL: container smoke ({type(error).__name__}, line {trace.tb_lineno})",
        file=sys.stderr,
    )
    raise SystemExit(1) from None
finally:
    engine.dispose()

import json
import logging
from io import StringIO
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from sinegor.core.config import Settings
from sinegor.core.logging import JsonFormatter
from sinegor.main import create_app
from sinegor.modules.auth.security import csrf_token, new_secret


@pytest.fixture
def app():
    return create_app(
        Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql+psycopg://test:secret@localhost/sinegor_test",
        )
    )


@pytest.fixture
def log_output(app):
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("sinegor")
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_liveness_does_not_require_database(app):
    with TestClient(app) as client:
        response = client.get("/api/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert len(response.headers["X-Request-ID"]) == 32


def test_agreement_openapi_declares_pdf_upload_and_download(app):
    paths = app.openapi()["paths"]
    upload = paths["/api/admin/orders/{order_id}/agreement/initial"]["post"]
    assert set(upload["requestBody"]["content"]) == {"application/pdf"}
    assert upload["requestBody"]["content"]["application/pdf"]["schema"]["format"] == "binary"
    assert any(p["name"] == "X-Agreement-Revision" and p["required"] for p in upload["parameters"])
    for role in ("admin", "customer"):
        download = paths[f"/api/{role}/orders/{{order_id}}/agreement/{{kind}}"]["get"]
        assert set(download["responses"]["200"]["content"]) == {"application/pdf"}


@pytest.mark.parametrize("component", ["header", "cookie"])
@pytest.mark.parametrize("invalid", ["missing", "forged", "expired", "other_session", "oversized"])
def test_csrf_rejects_invalid_header_or_cookie(app, component, invalid):
    @app.post("/api/test/csrf", status_code=204)
    def protected():
        pass

    raw_session = new_secret()
    key = app.state.csrf_key
    header = csrf_token(key, raw_session)
    cookie = csrf_token(key, raw_session)
    bad = {
        "missing": "",
        "forged": "forged",
        "expired": csrf_token(key, raw_session, now=0),
        "other_session": csrf_token(key, "other_session"),
        "oversized": "x" * 257,
    }[invalid]
    if component == "header":
        header = bad
    else:
        cookie = bad
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.session_cookie_name, raw_session)
        client.cookies.set(app.state.settings.csrf_cookie_name, cookie)
        response = client.post(
            "/api/test/csrf",
            headers={
                "Origin": str(app.state.settings.public_origin).rstrip("/"),
                "X-CSRF-Token": header,
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_failed"


def test_missing_route_uses_error_envelope(app):
    with TestClient(app) as client:
        response = client.get("/missing")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "http_404"
        assert response.json()["request_id"] == response.headers["X-Request-ID"]


class Payload(BaseModel):
    count: int


def test_validation_does_not_echo_body(app, log_output):
    @app.post("/test/validation")
    def validate(payload: Payload):
        return payload

    with TestClient(app) as client:
        response = client.post(
            "/test/validation?token=private_query", json={"count": "private_body"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
    output = log_output.getvalue() + response.text
    assert "private_body" not in output
    assert "private_query" not in output


def test_unexpected_errors_are_safe_and_correlated(app, log_output):
    @app.get("/test/failure")
    def fail():
        raise RuntimeError("private_exception_content")

    with TestClient(app) as client:
        response = client.get("/test/failure?token=private_token")
        assert response.status_code == 500
        request_id = response.headers["X-Request-ID"]
        assert response.json() == {
            "error": {"code": "internal_error", "message": "Internal server error"},
            "request_id": request_id,
        }
    output = log_output.getvalue()
    assert "private_exception_content" not in output + response.text
    assert "private_token" not in output + response.text
    records = [json.loads(line) for line in output.splitlines()]
    error = next(item for item in records if item["event"] == "unhandled_error")
    assert error["request_id"] == request_id
    assert error["exception_type"] == "RuntimeError"


def test_readiness_failure_returns_503_without_database_details(app, log_output):
    with TestClient(app) as client:
        with patch.object(
            app.state.engine,
            "connect",
            side_effect=OperationalError(
                "SELECT secret",
                {},
                RuntimeError("postgres://private_password@internal-host"),
            ),
        ):
            response = client.get("/api/health/ready")
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "database_unavailable"
    output = log_output.getvalue() + response.text
    assert "private_password" not in output
    assert "internal-host" not in output


def test_production_does_not_expose_api_docs():
    app: FastAPI = create_app(
        Settings(
            _env_file=None,
            app_env="production",
            session_secret="test-session-secret-" * 3,
            auth_encryption_key=Fernet.generate_key().decode(),
            public_origin="https://example.ru",
            database_url="postgresql+psycopg://user:dedicated_password@localhost/sinegor",
        )
    )
    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
        assert client.get("/api/health/live").status_code == 200

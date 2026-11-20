"""Real PostgreSQL roles exercise DML, DDL, retention and production startup."""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from sinegor.core.config import Settings
from sinegor.db.session import create_db_engine
from sinegor.main import create_app
from sinegor.modules.security_events.permissions import verify_runtime_permissions

pytestmark = pytest.mark.integration


@pytest.fixture
def roles(database_settings, alembic_config):
    command.upgrade(alembic_config, "head")
    engine = create_db_engine(database_settings)
    suffix = uuid4().hex[:12]
    runtime, maintenance = "journal_api_" + suffix, "journal_cleanup_" + suffix
    password = "isolated-security-test-password"
    script = (
        Path(__file__).resolve().parents[4] / "infra/postgres/security-journal.sql"
    ).read_text()
    script = "\n".join(
        line
        for line in script.splitlines()
        if not line.startswith("\\") and line not in {"BEGIN;", "COMMIT;"}
    )
    script = script.replace(':"runtime_role"', f'"{runtime}"').replace(
        ':"maintenance_role"', f'"{maintenance}"'
    )
    with engine.begin() as connection:
        for role in [runtime, maintenance]:
            connection.exec_driver_sql(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'")
        connection.exec_driver_sql(script)
    with engine.connect() as connection:
        previous_limits = set(connection.scalars(text("SELECT key_hash FROM auth_rate_limits")))
    base = make_url(database_settings.database_url.get_secret_value())
    runtime_url = base.set(username=runtime, password=password)
    maintenance_url = base.set(username=maintenance, password=password)
    runtime_engine = create_engine(runtime_url, hide_parameters=True)
    maintenance_engine = create_engine(maintenance_url, hide_parameters=True)
    try:
        yield engine, runtime_engine, maintenance_engine, runtime, maintenance
    finally:
        runtime_engine.dispose()
        maintenance_engine.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM public.security_events")
            for key in (
                set(connection.scalars(text("SELECT key_hash FROM auth_rate_limits")))
                - previous_limits
            ):
                connection.execute(
                    text("DELETE FROM auth_rate_limits WHERE key_hash=:key"), {"key": key}
                )
            connection.exec_driver_sql(
                "ALTER FUNCTION public.purge_security_events() "
                "SET sinegor.security_retention_months TO '6'"
            )
            for role in [runtime, maintenance]:
                connection.exec_driver_sql(f"DROP OWNED BY {role}")
                connection.exec_driver_sql(f"DROP ROLE {role}")
        engine.dispose()


def insert_event(connection, stamp=None):
    identifier = uuid4()
    connection.execute(
        text("""
        INSERT INTO public.security_events
        (id, recorded_at, event_type, result, request_id, reason_code)
        VALUES (:id, COALESCE(:stamp, statement_timestamp()),
                'access_denied', 'failure', :request, 'csrf_failed')
    """),
        {"id": identifier, "stamp": stamp, "request": uuid4().hex},
    )
    return identifier


def test_runtime_cannot_mutate_journal_or_invoke_retention_and_other_dml_works(roles):
    owner, runtime, maintenance, _, _ = roles
    with runtime.begin() as connection:
        verify_runtime_permissions(connection)
        identifier = insert_event(connection)
        assert connection.scalar(text("SELECT count(*) FROM public.security_events")) == 1
        customer = uuid4()
        connection.execute(
            text("INSERT INTO customers (id,email) VALUES (:id, 'roles@example.ru')"),
            {"id": customer},
        )
        connection.execute(
            text("UPDATE customers SET display_name='Updated' WHERE id=:id"), {"id": customer}
        )
        assert (
            connection.scalar(
                text("SELECT display_name FROM customers WHERE id=:id"), {"id": customer}
            )
            == "Updated"
        )
        connection.execute(text("DELETE FROM customers WHERE id=:id"), {"id": customer})
    for sql in [
        "UPDATE public.security_events SET reason_code='logout'",
        "DELETE FROM public.security_events",
        "TRUNCATE public.security_events",
        "ALTER TABLE public.security_events ADD COLUMN secret text",
        "DROP TABLE public.security_events",
        "SELECT public.purge_security_events()",
        "ALTER FUNCTION public.purge_security_events() "
        "SET sinegor.security_retention_months TO '1'",
        "CREATE OR REPLACE FUNCTION public.purge_security_events() "
        "RETURNS bigint LANGUAGE sql AS $$ SELECT 0::bigint $$",
    ]:
        with pytest.raises(DBAPIError), runtime.begin() as connection:
            connection.exec_driver_sql(sql)
    for sql in [
        "SELECT * FROM public.security_events",
        "DELETE FROM public.security_events",
        "UPDATE public.security_events SET result='success'",
        "TRUNCATE public.security_events",
    ]:
        with pytest.raises(DBAPIError), maintenance.begin() as connection:
            connection.exec_driver_sql(sql)
    with maintenance.begin() as connection:
        assert connection.scalar(text("SELECT public.purge_security_events()")) == 0
    with owner.connect() as connection:
        assert connection.scalar(text("SELECT id FROM public.security_events")) == identifier


def test_cleanup_boundary_configuration_and_caller_cannot_override(roles):
    owner, runtime, maintenance, _, _ = roles
    with owner.connect() as connection:
        boundary = connection.scalar(text("SELECT statement_timestamp() - interval '6 months'"))
    with owner.begin() as connection:
        old = insert_event(connection, boundary - timedelta(days=1))
        recent = insert_event(connection, boundary + timedelta(days=1))
        ninety_one_days = insert_event(connection, datetime.now(UTC) - timedelta(days=91))
    with maintenance.begin() as connection:
        connection.exec_driver_sql("SET LOCAL sinegor.security_retention_months='0'")
        connection.exec_driver_sql("SET LOCAL TIME ZONE 'Pacific/Honolulu'")
        assert connection.scalar(text("SELECT public.purge_security_events()")) == 1
        assert connection.scalar(text("SELECT public.purge_security_events()")) == 0
    with runtime.connect() as connection:
        remaining = set(connection.scalars(text("SELECT id FROM public.security_events")))
        assert old not in remaining and remaining == {recent, ninety_one_days}


def test_startup_rejects_owner_and_inherited_or_column_update_privilege(roles):
    owner, runtime, _, runtime_name, maintenance_name = roles
    with pytest.raises(RuntimeError), owner.connect() as connection:
        verify_runtime_permissions(connection)
    for grant, revoke in [
        (
            f"GRANT UPDATE (result) ON public.security_events TO {runtime_name}",
            f"REVOKE UPDATE (result) ON public.security_events FROM {runtime_name}",
        ),
        (
            f"GRANT {maintenance_name} TO {runtime_name}",
            f"REVOKE {maintenance_name} FROM {runtime_name}",
        ),
    ]:
        with owner.begin() as connection:
            connection.exec_driver_sql(grant)
        try:
            with pytest.raises(RuntimeError), runtime.connect() as connection:
                verify_runtime_permissions(connection)
        finally:
            with owner.begin() as connection:
                connection.exec_driver_sql(revoke)


def test_real_production_requests_persist_denials_after_rollback_and_cleanup_cli(roles):
    owner, runtime, maintenance, _, _ = roles
    settings = Settings(
        _env_file=None,
        app_env="production",
        log_level="WARNING",
        database_url=runtime.url.render_as_string(hide_password=False),
        public_origin="https://testserver",
        session_secret="test-security-session-secret-" * 2,
        auth_encryption_key=Fernet.generate_key().decode(),
    )
    app = create_app(settings)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/api/admin/security-events")
        assert response.status_code == 401
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        response2 = client.post(
            "/api/auth/admin/login",
            json={
                "email": "unknown@example.ru",
                "password": "wrong-password-for-real-test",
                "code": "000000",
            },
            headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
        )
        assert response2.status_code == 401
    with owner.connect() as connection:
        rows = connection.execute(
            text("SELECT reason_code, request_id, user_id FROM public.security_events")
        ).all()
        assert {(r.reason_code, r.request_id) for r in rows} == {
            ("authentication_required", response.headers["X-Request-ID"]),
            ("invalid_credentials", response2.headers["X-Request-ID"]),
        }
        assert all(r.user_id is None for r in rows)
    env = os.environ | {
        "DATABASE_URL": maintenance.url.render_as_string(hide_password=False),
        "APP_ENV": "test",
        "SINEGOR_ENV_FILE": "/dev/null",
    }
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "sinegor.jobs.purge_security_events"],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "Expired security events removed: 0"


def test_runtime_temp_table_cannot_shadow_application_journal(roles):
    from sqlalchemy.orm import Session

    from sinegor.modules.security_events.service import record

    _, runtime, _, _, _ = roles
    with runtime.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TEMP TABLE security_events "
            "(LIKE public.security_events INCLUDING ALL) ON COMMIT DROP"
        )
        with Session(bind=connection) as db:
            record(db, "access_denied", "csrf_failed", result="failure")
            db.flush()
            assert connection.scalar(text("SELECT count(*) FROM public.security_events")) == 1
            assert connection.scalar(text("SELECT count(*) FROM pg_temp.security_events")) == 0


@pytest.mark.parametrize("capability", ["cleanup", "delete", "column_update", "schema_create"])
def test_startup_rejects_noinherit_memberships_with_set_role_escape(roles, capability):
    owner, runtime, _, runtime_name, maintenance_name = roles
    with owner.begin() as connection:
        connection.exec_driver_sql(f"ALTER ROLE {runtime_name} NOINHERIT")
        connection.exec_driver_sql(f"GRANT {maintenance_name} TO {runtime_name}")
        if capability != "cleanup":
            connection.exec_driver_sql(
                f"REVOKE EXECUTE ON FUNCTION public.purge_security_events() FROM {maintenance_name}"
            )
            grant = {
                "delete": "DELETE ON public.security_events",
                "column_update": "UPDATE (result) ON public.security_events",
                "schema_create": "CREATE ON SCHEMA public",
            }[capability]
            connection.exec_driver_sql(f"GRANT {grant} TO {maintenance_name}")
    with runtime.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT has_function_privilege(current_user, "
                    "'public.purge_security_events()', 'EXECUTE')"
                )
            )
            is False
        )
        # NOINHERIT does not prevent SET ROLE. Startup must inspect all reachable roles.
        with pytest.raises(RuntimeError):
            verify_runtime_permissions(connection)


def test_production_runtime_login_read_and_logout_use_restricted_role(roles):
    import pyotp
    from sqlalchemy import delete, select
    from sqlalchemy.orm import Session

    from sinegor.modules.auth.models import AdminUser
    from sinegor.modules.auth.models import Session as AuthSession
    from sinegor.modules.auth.security import HASHER

    owner, runtime, _, _, _ = roles
    key = Fernet.generate_key()
    secret, identifier = pyotp.random_base32(), uuid4()
    settings = Settings(
        _env_file=None,
        app_env="production",
        log_level="WARNING",
        database_url=runtime.url.render_as_string(hide_password=False),
        public_origin="https://testserver",
        session_secret="test-session-key-" * 3,
        auth_encryption_key=key.decode(),
    )
    with Session(owner) as db:
        db.add(
            AdminUser(
                id=identifier,
                email="runtime-admin@example.ru",
                password_hash=HASHER.hash("isolated-admin-password"),
                totp_secret_encrypted=Fernet(key).encrypt(secret.encode()).decode(),
            )
        )
        db.commit()
    try:
        with TestClient(create_app(settings), base_url="https://testserver") as client:

            def post(path, payload=None):
                csrf = client.get("/api/auth/csrf").json()["csrf_token"]
                return client.post(
                    path,
                    json=payload,
                    headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
                )

            assert (
                post(
                    "/api/auth/admin/login",
                    {
                        "email": "runtime-admin@example.ru",
                        "password": "isolated-admin-password",
                        "code": pyotp.TOTP(secret).now(),
                    },
                ).status_code
                == 204
            )
            assert client.get("/api/auth/session").json()["role"] == "admin"
            response = client.get(
                "/api/admin/security-events", params={"event_type": "authentication"}
            )
            assert response.status_code == 200
            assert len(response.json()) == 1
            assert response.json()[0]["user_id"] == str(identifier)
            assert post("/api/auth/logout").status_code == 204
            assert client.get("/api/admin/security-events").status_code == 401
        with Session(owner) as db:
            from sinegor.modules.security_events.models import SecurityEvent

            assert db.scalar(select(SecurityEvent.id).where(SecurityEvent.reason_code == "logout"))
    finally:
        with owner.begin() as connection:
            connection.execute(delete(AuthSession).where(AuthSession.admin_id == identifier))
            connection.execute(delete(AdminUser).where(AdminUser.id == identifier))

"""Synthetic PostgreSQL probes, run only by postgres-logging-audit.py.

Line-delimited JSON control protocol. Never emit exception messages or SQL values.
The client shares only the disposable audit PostgreSQL network namespace.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql

assert os.environ.get("SINEGOR_PGLOG_AUDIT") == "20261112"


def connect(**overrides):
    config = {
        "host": "127.0.0.1",
        "port": 5432,
        "dbname": "postgres",
        "user": "postgres",
        "password": os.environ["POSTGRES_PASSWORD"],
        "connect_timeout": 3,
        "autocommit": True,
        "application_name": "sinegor_pglog_audit",
    }
    config.update(overrides)
    return psycopg.connect(**config)


def setup():
    with connect() as db:
        db.execute("CREATE SCHEMA audit")
        db.execute(
            sql.SQL("CREATE ROLE audit_runtime LOGIN PASSWORD {}").format(
                sql.Literal(os.environ["AUDIT_ROLE_PASSWORD"])
            )
        )
        db.execute("GRANT USAGE ON SCHEMA audit TO audit_runtime")
        db.execute("CREATE TABLE audit.parents (value text PRIMARY KEY)")
        db.execute("CREATE TABLE audit.children (value text REFERENCES audit.parents(value))")
        db.execute("CREATE TABLE audit.private (value text)")
        db.execute("INSERT INTO audit.private VALUES ('synthetic')")
        db.execute("""CREATE FUNCTION audit.fail(value text) RETURNS void LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'audit_expected_error' USING DETAIL=value,HINT=value; END $$""")
        for name, severity in (("warn", "WARNING"), ("log", "LOG")):
            db.execute(
                sql.SQL(
                    "CREATE FUNCTION audit.{}(value text) RETURNS void "
                    "LANGUAGE plpgsql AS $$ BEGIN RAISE " + severity + " '%',value; END $$"
                ).format(sql.Identifier(name))
            )
    return {"ok": True}


def migration(token):
    # Real Alembic CLI, isolated configuration/revision and transaction rollback.
    with tempfile.TemporaryDirectory(prefix="pglog-migration-") as directory:
        root = Path(directory)
        (root / "versions").mkdir()
        (root / "alembic.ini").write_text(f"[alembic]\nscript_location = {root}\n")
        (root / "env.py").write_text("""
import os
from alembic import context
from sqlalchemy import create_engine, URL
engine=create_engine(URL.create('postgresql+psycopg',username='postgres',
    password=os.environ['POSTGRES_PASSWORD'],host='127.0.0.1',port=5432,database='postgres'),
    hide_parameters=True)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction(): context.run_migrations()
engine.dispose()
""")
        (root / "versions/0001_failure.py").write_text("""
import os
from alembic import op
import sqlalchemy as sa
revision='pglog_probe'
down_revision=None
def upgrade():
    op.create_table('audit_migration_probe',sa.Column('id',sa.Integer,primary_key=True))
    op.execute(sa.text('SELECT CAST(:value AS integer)').bindparams(
        value=os.environ['AUDIT_MIGRATION_CANARY']))
""")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
            env={**os.environ, "AUDIT_MIGRATION_CANARY": token},
            capture_output=True,
            text=True,
            timeout=25,
        )
        assert result.returncode != 0
        with connect() as db:
            assert (
                db.execute("SELECT to_regclass('public.audit_migration_probe')").fetchone()[0]
                is None
            )
        return {
            "ok": False,
            "expected_sqlstate": "22P02",
            "migration_rolled_back": True,
            "client_output_has_canary": token in result.stdout + result.stderr,
        }


def probe(request):
    case, values = request["case"], request["values"]
    if case == "setup":
        return setup()
    if case == "migration_failure":
        return migration(values["token"])
    pid = None
    try:
        if case == "auth_bad_password":
            connect(password=values["password"]).close()
        elif case == "auth_sensitive_login":
            connect(user=values["email"], password=values["token"]).close()
        elif case == "database_missing":
            connect(dbname=values["token"]).close()
        elif case == "connection_refused":
            connect(port=65432).close()
        else:
            options = (
                {"user": "audit_runtime", "password": os.environ["AUDIT_ROLE_PASSWORD"]}
                if case == "permission_denied"
                else {}
            )
            with connect(**options) as db:
                pid = db.info.backend_pid
                payload = " | ".join(values.values())
                if case == "success":
                    assert db.execute("SELECT %s::text", (payload,)).fetchone()[0] == payload
                elif case == "unique":
                    db.execute("INSERT INTO audit.parents VALUES (%s)", (payload,))
                    db.execute("INSERT INTO audit.parents VALUES (%s)", (payload,))
                elif case == "foreign_key":
                    db.execute("INSERT INTO audit.children VALUES (%s)", (payload,))
                elif case == "syntax":
                    db.execute(sql.SQL("SELECT 1 {}").format(sql.Literal(values["token"])))
                elif case.startswith("invalid_cast_"):
                    field = case.removeprefix("invalid_cast_")
                    db.execute("SELECT CAST(%s AS integer)", (values[field],))
                elif case == "permission_denied":
                    db.execute("SELECT * FROM audit.private")
                elif case == "plpgsql_detail_context":
                    db.execute("SELECT audit.fail(%s)", (payload,))
                elif case == "raise_warning":
                    db.execute("SELECT audit.warn(%s)", (payload,))
                elif case == "raise_log":
                    db.execute("SELECT audit.log(%s)", (payload,))
                elif case == "connection_terminated":
                    with connect() as admin:
                        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
                    db.execute("SELECT 1")
                else:
                    raise ValueError("Unknown audit case")
        return {"ok": True, "pid": pid, "sqlstate": None}
    except psycopg.Error as error:
        return {
            "ok": False,
            "pid": pid,
            "sqlstate": error.sqlstate,
            "exception_type": type(error).__name__,
        }


for line in sys.stdin:
    try:
        request = json.loads(line)
        if request["case"] == "exit":
            break
        result = probe(request)
    except Exception as error:
        result = {"harness_error": type(error).__name__}
    print(json.dumps(result), flush=True)

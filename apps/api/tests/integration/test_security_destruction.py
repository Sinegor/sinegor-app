"""Privileged retention records only committed, actual deleted batches."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_security_permissions import insert_event, roles  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture
def destruction_roles(roles):  # noqa: F811
    owner, *_ = roles
    try:
        yield roles
    finally:
        with owner.begin() as connection:
            connection.execute(
                text("DELETE FROM public.destruction_operations WHERE kind='security_events'")
            )


def old_stamp():
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=220
    )


def batches(connection):
    return (
        connection.execute(
            text("SELECT * FROM public.destruction_operations WHERE kind='security_events'")
        )
        .mappings()
        .all()
    )


def test_security_retention_registers_minimal_batch_and_repeated_call_is_empty(destruction_roles):
    owner, _, maintenance, _, maintenance_name = destruction_roles
    customer = uuid4()
    with owner.begin() as connection:
        connection.execute(
            text("INSERT INTO customers(id,email,display_name) VALUES (:id,:email,:name)"),
            {"id": customer, "email": "destruction@example.ru", "name": "Иванов Иван Иванович"},
        )
        first = insert_event(connection, old_stamp())
        second = insert_event(connection, old_stamp())
        connection.execute(
            text("UPDATE security_events SET user_id=:id,user_role='customer' WHERE id=:event"),
            {"id": customer, "event": first},
        )
        recent = insert_event(connection)
    try:
        with maintenance.begin() as connection:
            assert connection.scalar(text("SELECT public.purge_security_events()")) == 2
            assert connection.scalar(text("SELECT public.purge_security_events()")) == 0
        with owner.connect() as connection:
            rows = batches(connection)
            assert len(rows) == 1
            row = rows[0]
            assert row["state"] == "documents_pending"
            assert row["destroyed_at"] is not None
            assert row["expires_at"] > row["destroyed_at"] + timedelta(days=1094)
            metadata = row["metadata_json"]
            assert metadata["entity"]["batch_count"] == 2
            assert metadata["basis"]
            assert maintenance_name in metadata["initiator"]
            assert maintenance_name in metadata["executor"]
            subjects = metadata["subjects"]
            assert any("Иванов Иван Иванович" in subject["identity"] for subject in subjects)
            assert any("невозможно" in subject["identity"].lower() for subject in subjects)
            assert all(subject["categories"] and subject["source"] for subject in subjects)
            assert "destruction@example.ru" not in str(metadata)
            assert str(first) not in str(metadata) and str(second) not in str(metadata)
            assert set(connection.scalars(text("SELECT id FROM security_events"))) == {recent}
    finally:
        with owner.begin() as connection:
            connection.execute(text("DELETE FROM customers WHERE id=:id"), {"id": customer})


def test_security_retention_registry_failure_rolls_back_deletion(destruction_roles):
    owner, _, maintenance, *_ = destruction_roles
    with owner.begin() as connection:
        identifier = insert_event(connection, old_stamp())
        connection.exec_driver_sql("""
            CREATE FUNCTION public.reject_security_destruction_test() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                IF NEW.kind = 'security_events' THEN
                    RAISE EXCEPTION 'synthetic registry failure';
                END IF;
                RETURN NEW;
            END; $$
        """)
        connection.exec_driver_sql("""
            CREATE TRIGGER reject_security_destruction_test
            BEFORE INSERT ON public.destruction_operations FOR EACH ROW
            EXECUTE FUNCTION public.reject_security_destruction_test()
        """)
    try:
        with pytest.raises(DBAPIError), maintenance.begin() as connection:
            connection.scalar(text("SELECT public.purge_security_events()"))
        with owner.connect() as connection:
            assert connection.scalar(text("SELECT id FROM security_events")) == identifier
            assert batches(connection) == []
    finally:
        with owner.begin() as connection:
            connection.exec_driver_sql(
                "DROP TRIGGER reject_security_destruction_test ON public.destruction_operations"
            )
            connection.exec_driver_sql("DROP FUNCTION public.reject_security_destruction_test()")


def test_concurrent_security_retention_confirms_each_event_only_once(destruction_roles):
    owner, _, maintenance, *_ = destruction_roles
    with owner.begin() as connection:
        for _ in range(5):
            insert_event(connection, old_stamp())

    def purge(_):
        with maintenance.begin() as connection:
            return connection.scalar(text("SELECT public.purge_security_events()"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(purge, range(2))) == [0, 5]
    with owner.connect() as connection:
        rows = batches(connection)
        assert len(rows) == 1
        assert rows[0]["metadata_json"]["entity"]["batch_count"] == 5


def test_security_cleanup_role_cannot_mutate_register_directly(destruction_roles):
    _, _, maintenance, *_ = destruction_roles
    for sql in [
        "SELECT * FROM public.destruction_operations",
        "DELETE FROM public.destruction_operations",
        "UPDATE public.destruction_operations SET state='documents_pending'",
        "TRUNCATE public.destruction_operations",
    ]:
        with pytest.raises(DBAPIError), maintenance.begin() as connection:
            connection.exec_driver_sql(sql)


def test_security_migration_roundtrip_preserves_acl_and_configuration(
    destruction_roles, alembic_config
):
    from alembic import command

    owner, runtime, maintenance, *_ = destruction_roles
    with owner.begin() as connection:
        identifier = insert_event(connection, old_stamp())
        connection.exec_driver_sql(
            "ALTER FUNCTION public.purge_security_events() "
            "SET sinegor.security_retention_months TO '6'"
        )
        original_acl = connection.scalar(
            text(
                "SELECT proacl::text FROM pg_proc "
                "WHERE oid='public.purge_security_events()'::regprocedure"
            )
        )
    command.downgrade(alembic_config, "0016_destruction_register")
    command.upgrade(alembic_config, "head")
    with owner.connect() as connection:
        assert connection.scalar(text("SELECT id FROM security_events")) == identifier
        assert batches(connection) == []
        assert (
            connection.scalar(
                text(
                    "SELECT proacl::text FROM pg_proc "
                    "WHERE oid='public.purge_security_events()'::regprocedure"
                )
            )
            == original_acl
        )
        config = connection.scalar(
            text(
                "SELECT proconfig FROM pg_proc "
                "WHERE oid='public.purge_security_events()'::regprocedure"
            )
        )
        assert "sinegor.security_retention_months=6" in config
        assert "search_path=pg_catalog" in config
        assert "TimeZone=UTC" in config
    from sinegor.modules.security_events.permissions import verify_runtime_permissions

    with runtime.connect() as connection:
        verify_runtime_permissions(connection)
    with maintenance.begin() as connection:
        assert connection.scalar(text("SELECT public.purge_security_events()")) == 1

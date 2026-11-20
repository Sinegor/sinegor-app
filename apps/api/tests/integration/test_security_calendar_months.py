"""Exercise the migration predicate at frozen calendar boundaries in a test clone."""

import ast
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from test_security_permissions import insert_event, roles  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "recorded,expiry",
    [
        ("2026-08-31T12:00:00+00:00", "2027-02-28T12:00:00+00:00"),
        ("2023-08-31T12:00:00+00:00", "2024-02-29T12:00:00+00:00"),
        ("2024-02-29T12:00:00+00:00", "2024-08-29T12:00:00+00:00"),
        ("2026-01-31T12:00:00+00:00", "2026-07-31T12:00:00+00:00"),
        ("2031-03-31T12:00:00+00:00", "2031-09-30T12:00:00+00:00"),
    ],
)
@pytest.mark.parametrize("offset,removed", [(-1, 0), (0, 1), (1, 1)])
def test_six_calendar_months_before_at_and_after_expiry(roles, recorded, expiry, offset, removed):  # noqa: F811
    owner, _, maintenance, _, maintenance_name = roles
    path = (
        Path(__file__).resolve().parents[2] / "migrations/versions/0018_security_calendar_months.py"
    )
    tree = ast.parse(path.read_text())
    sql = ast.literal_eval(
        next(
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "UPGRADE_SQL"
                for target in node.targets
            )
        )
    )
    sql = sql.replace("public.purge_security_events()", "public.calendar_boundary_test()")
    clock = f"(timestamptz '{expiry}' + interval '{offset} microsecond')"
    sql = sql.replace("statement_timestamp()", clock)
    with owner.begin() as connection:
        connection.exec_driver_sql(sql)
        connection.exec_driver_sql(
            "REVOKE ALL ON FUNCTION public.calendar_boundary_test() FROM PUBLIC"
        )
        connection.exec_driver_sql(
            f"GRANT EXECUTE ON FUNCTION public.calendar_boundary_test() TO {maintenance_name}"
        )
        identifier = insert_event(connection, datetime.fromisoformat(recorded))
    try:
        with maintenance.begin() as connection:
            assert connection.scalar(text("SELECT public.calendar_boundary_test()")) == removed
        with owner.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM security_events WHERE id=:id"), {"id": identifier}
                )
                == 1 - removed
            )
    finally:
        with owner.begin() as connection:
            connection.exec_driver_sql("DROP FUNCTION public.calendar_boundary_test()")

"""Fail production startup if the effective runtime privileges bypass the journal boundary."""

from sqlalchemy import Connection, text


def verify_runtime_permissions(connection: Connection) -> None:
    safe = connection.scalar(
        text("""
        SELECT
          has_table_privilege(current_user, 'public.security_events', 'SELECT')
          AND has_table_privilege(current_user, 'public.security_events', 'INSERT')
          AND NOT has_table_privilege(current_user, 'public.security_events', 'UPDATE')
          AND NOT has_any_column_privilege(current_user, 'public.security_events', 'UPDATE')
          AND NOT has_table_privilege(current_user, 'public.security_events', 'DELETE')
          AND NOT has_table_privilege(current_user, 'public.security_events', 'TRUNCATE')
          AND NOT has_table_privilege(current_user, 'public.security_events', 'TRIGGER')
          AND NOT has_table_privilege(current_user, 'public.security_events', 'REFERENCES')
          AND NOT has_schema_privilege(current_user, 'public', 'CREATE')
          AND NOT has_function_privilege(current_user, 'public.purge_security_events()', 'EXECUTE')
          AND NOT EXISTS (
            SELECT 1 FROM pg_roles r
            WHERE pg_has_role(current_user, r.oid, 'MEMBER') AND (
              r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolbypassrls
              OR has_table_privilege(r.oid, 'public.security_events', 'UPDATE')
              OR has_any_column_privilege(r.oid, 'public.security_events', 'UPDATE')
              OR has_table_privilege(r.oid, 'public.security_events', 'DELETE')
              OR has_table_privilege(r.oid, 'public.security_events', 'TRUNCATE')
              OR has_table_privilege(r.oid, 'public.security_events', 'TRIGGER')
              OR has_table_privilege(r.oid, 'public.security_events', 'REFERENCES')
              OR has_schema_privilege(r.oid, 'public', 'CREATE')
              OR has_function_privilege(r.oid, 'public.purge_security_events()', 'EXECUTE')
              OR r.oid = (SELECT relowner FROM pg_class
                          WHERE oid = 'public.security_events'::regclass)
              OR r.oid = (SELECT proowner FROM pg_proc
                          WHERE oid = 'public.purge_security_events()'::regprocedure)
              OR r.oid = (SELECT nspowner FROM pg_namespace WHERE nspname = 'public')
              OR r.oid = (SELECT datdba FROM pg_database WHERE datname = current_database())
            )
          )
    """)
    )
    if safe is not True:
        raise RuntimeError("Unsafe PostgreSQL runtime privileges for security journal")

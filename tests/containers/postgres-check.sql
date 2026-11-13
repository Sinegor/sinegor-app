\set ON_ERROR_STOP on
-- Run as postgres in the isolated project's API database after migrate + grants.
DO $$
BEGIN
    IF current_setting('log_min_messages') <> 'warning'
       OR current_setting('log_min_error_statement') <> 'panic'
       OR current_setting('log_error_verbosity') <> 'terse'
       OR current_setting('log_statement') <> 'none'
       OR current_setting('log_parameter_max_length_on_error') <> '0' THEN
        RAISE EXCEPTION 'PostgreSQL must retain warnings/errors without statements or DETAIL values';
    END IF;
    IF has_database_privilege('sinegor_api', 'sinegor_cms', 'CONNECT')
       OR has_database_privilege('sinegor_cms', 'sinegor', 'CONNECT') THEN
        RAISE EXCEPTION 'Application roles can connect to the other database';
    END IF;
    IF (SELECT count(*) FROM pg_database WHERE datname IN ('sinegor', 'sinegor_cms')) <> 2
       OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname LIKE 'sinegor_%'
                  AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Unexpected database/role isolation';
    END IF;
    IF NOT has_parameter_privilege('sinegor_owner', 'sinegor.security_retention_days', 'SET')
       OR has_parameter_privilege('sinegor_api', 'sinegor.security_retention_days', 'SET') THEN
        RAISE EXCEPTION 'Unexpected migration parameter privileges';
    END IF;
    IF NOT has_table_privilege('sinegor_api', 'public.security_events', 'SELECT, INSERT')
       OR has_table_privilege('sinegor_api', 'public.security_events', 'UPDATE, DELETE, TRUNCATE')
       OR has_schema_privilege('sinegor_api', 'public', 'CREATE')
       OR has_function_privilege('sinegor_api', 'public.purge_security_events()', 'EXECUTE') THEN
        RAISE EXCEPTION 'Unsafe runtime journal privileges';
    END IF;
    IF NOT has_function_privilege('sinegor_security_cleanup',
                                 'public.purge_security_events()', 'EXECUTE') THEN
        RAISE EXCEPTION 'Missing dedicated maintenance permission';
    END IF;
    IF (SELECT version_num FROM public.alembic_version) <> '0017_security_destruction' THEN
        RAISE EXCEPTION 'API migrations are incomplete';
    END IF;
END;
$$;

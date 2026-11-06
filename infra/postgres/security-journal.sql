-- Run with psql as the migration/table owner, after alembic upgrade head:
-- psql service=sinegor_migrations -v runtime_role=sinegor_api \
--   -v maintenance_role=sinegor_security_cleanup -f infra/postgres/security-journal.sql
-- Both LOGIN roles must already exist, with separate credentials, no elevated
-- attributes, no membership in the owner role and no ownership of database/schema.
-- Runtime must not own tables; maintenance must be dedicated to this operation.
\set ON_ERROR_STOP on
BEGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM :"runtime_role", :"maintenance_role";
GRANT USAGE ON SCHEMA public TO :"runtime_role", :"maintenance_role";
-- Preserve ordinary application DML. No runtime DDL or migration privileges.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"runtime_role";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"runtime_role";
REVOKE ALL ON TABLE public.security_events FROM PUBLIC, :"runtime_role", :"maintenance_role";
GRANT SELECT, INSERT ON TABLE public.security_events TO :"runtime_role";
REVOKE ALL ON FUNCTION public.purge_security_events() FROM PUBLIC, :"runtime_role", :"maintenance_role";
GRANT EXECUTE ON FUNCTION public.purge_security_events() TO :"maintenance_role";
COMMIT;
-- Owner-only retention configuration (UTC calendar days, default 90):
-- ALTER FUNCTION public.purge_security_events() SET sinegor.security_retention_days TO '90';
-- Run this script again after migrations that introduce tables or recreate this function.

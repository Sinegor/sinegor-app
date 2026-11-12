#!/bin/sh
set -eu
# Passwords are read by psql from environment, never interpolated into SQL/shell logs.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
\getenv api_owner_password API_OWNER_PASSWORD
\getenv api_password API_DATABASE_PASSWORD
\getenv cms_password CMS_DATABASE_PASSWORD
\getenv security_password SECURITY_CLEANUP_PASSWORD
CREATE ROLE sinegor_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'api_owner_password';
CREATE ROLE sinegor_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'api_password';
CREATE ROLE sinegor_security_cleanup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'security_password';
CREATE ROLE sinegor_cms LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'cms_password';
-- CREATE/ALTER FUNCTION ... SET requires explicit parameter permission for a
-- non-superuser migration owner. Runtime and maintenance do not receive it.
GRANT SET ON PARAMETER "sinegor.security_retention_days" TO sinegor_owner;
CREATE DATABASE sinegor OWNER sinegor_owner;
CREATE DATABASE sinegor_cms OWNER sinegor_cms;
REVOKE ALL ON DATABASE sinegor FROM PUBLIC;
GRANT CONNECT ON DATABASE sinegor TO sinegor_api, sinegor_security_cleanup;
REVOKE ALL ON DATABASE sinegor_cms FROM PUBLIC;
SQL

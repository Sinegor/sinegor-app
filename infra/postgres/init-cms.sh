#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv cms_password CMS_DATABASE_PASSWORD
SELECT format('CREATE ROLE sinegor_cms LOGIN PASSWORD %L', :'cms_password') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sinegor_cms') \gexec
SELECT 'CREATE DATABASE sinegor_cms OWNER sinegor_cms' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'sinegor_cms') \gexec
SQL

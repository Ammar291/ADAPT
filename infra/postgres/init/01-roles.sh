#!/bin/sh
# Runs once, when the Postgres data volume is first initialised.
#
# Roles:
#   $POSTGRES_USER  owner of the schema; used ONLY by migrations and governance/RAG curation.
#   $APP_DB_USER    runtime role for API + worker. Not a superuser and not the table owner,
#                   so row-level security policies apply to every query it makes.
# A second database ($POSTGRES_DB"_test") is created for integration tests.
set -eu

APP_DB_USER="${APP_DB_USER:-adapt_app}"
APP_DB_PASSWORD="${APP_DB_PASSWORD:-adapt_app}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_DB_USER}') THEN
      CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
  END
  \$\$;
  CREATE DATABASE ${POSTGRES_DB}_test OWNER ${POSTGRES_USER};
SQL

for db in "$POSTGRES_DB" "${POSTGRES_DB}_test"; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-SQL
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pgcrypto;
    GRANT CONNECT ON DATABASE ${db} TO ${APP_DB_USER};
    GRANT USAGE ON SCHEMA public TO ${APP_DB_USER};
SQL
done

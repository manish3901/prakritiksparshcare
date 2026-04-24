#!/usr/bin/env bash
set -euo pipefail

# Runs only on first container init (empty PGDATA).
# Creates:
# - database psc_coupon
# - role psc_main_user  (password = PSC_DB_PASSWORD)
# - role psc_coupon_user (password = COUPON_DB_PASSWORD)
# Grants ownership and basic privileges.

# Create coupon DB if missing.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
SELECT 'CREATE DATABASE psc_coupon' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'psc_coupon')\gexec
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'psc_main_user') THEN
    CREATE ROLE psc_main_user LOGIN PASSWORD '${PSC_DB_PASSWORD}';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'psc_coupon_user') THEN
    CREATE ROLE psc_coupon_user LOGIN PASSWORD '${COUPON_DB_PASSWORD}';
  END IF;
END
\$\$;

ALTER DATABASE psc_main OWNER TO psc_main_user;
ALTER DATABASE psc_coupon OWNER TO psc_coupon_user;
SQL

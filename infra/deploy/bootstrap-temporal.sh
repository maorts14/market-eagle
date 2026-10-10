#!/bin/sh
set -eu

export PGPASSWORD="$(cat /run/secrets/temporal_db_password)"
export SQL_PASSWORD="$PGPASSWORD"
export SQL_HOST="$PGHOST"
export SQL_PORT="$PGPORT"
export SQL_USER="$PGUSER"
export SQL_PLUGIN=postgres12

for database in temporal temporal_visibility; do
    if [ "$database" = temporal ]; then
        schema=temporal
    else
        schema=visibility
    fi
    version_exists="$(psql --dbname "$database" --tuples-only --no-align --command "SELECT to_regclass('public.schema_version') IS NOT NULL")"
    if [ "$version_exists" = f ]; then
        temporal-sql-tool --db "$database" setup-schema -v 0.0
    fi
    temporal-sql-tool --db "$database" update-schema -d "/etc/temporal/schema/postgresql/v12/$schema/versioned"
done

echo 'Temporal schemas are ready'

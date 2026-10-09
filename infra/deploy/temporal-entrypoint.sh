#!/bin/sh
set -eu

# Temporal Server 1.27 requires POSTGRES_PWD. The secret is mounted only into
# this container; this bridge stays until the Temporal config is file-backed.
export POSTGRES_PWD="$(cat /run/secrets/temporal_db_password)"
exec /etc/temporal/entrypoint.sh

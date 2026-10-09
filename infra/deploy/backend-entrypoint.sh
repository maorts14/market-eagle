#!/bin/sh
set -eu

# Compose secrets are often mounted read-only with broad mode bits. libpq
# requires its password file to be private to the process user.
if [ -n "${PGPASS_SECRET:-}" ]; then
    umask 077
    cp "/run/secrets/${PGPASS_SECRET}" /tmp/market-eagle.pgpass
    if [ -n "${AGENT_PGPASS_SECRET:-}" ]; then
        printf '\n' >> /tmp/market-eagle.pgpass
        cat "/run/secrets/${AGENT_PGPASS_SECRET}" >> /tmp/market-eagle.pgpass
    fi
    export PGPASSFILE=/tmp/market-eagle.pgpass
fi

if [ -f /run/secrets/alpaca_key_id ]; then
    export ALPACA_API_KEY_ID="$(cat /run/secrets/alpaca_key_id)"
    export ALPACA_API_SECRET_KEY="$(cat /run/secrets/alpaca_secret_key)"
fi
if [ -f /run/secrets/fmp_key ]; then
    export FMP_API_KEY="$(cat /run/secrets/fmp_key)"
fi
if [ -f /run/secrets/openrouter_key ]; then
    export OPENROUTER_API_KEY="$(cat /run/secrets/openrouter_key)"
fi

exec "$@"

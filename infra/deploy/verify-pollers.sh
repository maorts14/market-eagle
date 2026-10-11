#!/bin/sh
set -eu

case "${CHECK_COLLECTION:-0}" in
    0|1) ;;
    *) echo 'CHECK_COLLECTION must be 0 or 1' >&2; exit 2 ;;
esac
case "${POLLER_ATTEMPTS:-12}" in
    ''|*[!0-9]*|0) echo 'POLLER_ATTEMPTS must be a positive integer' >&2; exit 2 ;;
esac

temporal operator namespace describe \
    --address "$TEMPORAL_ADDRESS" \
    --namespace "$TEMPORAL_NAMESPACE" \
    --command-timeout 5s >/dev/null

queues='market-eagle-agent'
if [ "$CHECK_COLLECTION" = 1 ]; then
    queues="$queues market-backfill market-session market-catalog"
fi

attempt=1
while [ "$attempt" -le "$POLLER_ATTEMPTS" ]; do
    missing=''
    for queue in $queues; do
        for kind in workflow activity; do
            if response="$(temporal task-queue describe \
                --address "$TEMPORAL_ADDRESS" \
                --namespace "$TEMPORAL_NAMESPACE" \
                --task-queue "$queue" \
                --task-queue-type-legacy "$kind" \
                --legacy-mode \
                --output json \
                --command-timeout 5s 2>/dev/null)" \
                && printf '%s\n' "$response" | jq -e \
                    '[(.pollers // [])[] | select(.last_access_time.seconds >= (now - 60) and .last_access_time.seconds <= (now + 5))] | length > 0' \
                    >/dev/null; then
                :
            else
                missing="$missing $queue/$kind"
            fi
        done
    done
    if [ -z "$missing" ]; then
        echo 'Expected Temporal workflow and activity pollers are active'
        exit 0
    fi
    attempt=$((attempt + 1))
    if [ "$attempt" -le "$POLLER_ATTEMPTS" ]; then
        sleep 5
    fi
done

echo "Missing Temporal pollers:$missing" >&2
exit 1

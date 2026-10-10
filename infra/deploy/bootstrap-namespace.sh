#!/bin/sh
set -eu

if temporal operator namespace describe --address "$TEMPORAL_ADDRESS" --namespace "$TEMPORAL_NAMESPACE" >/dev/null 2>&1; then
    echo 'Temporal namespace already exists'
else
    temporal operator namespace create --address "$TEMPORAL_ADDRESS" --namespace "$TEMPORAL_NAMESPACE" --retention 7d
fi

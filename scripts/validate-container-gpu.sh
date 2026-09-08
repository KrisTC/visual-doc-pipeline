#!/usr/bin/env sh
# Start a published image with a requested NVIDIA GPU and run its validation.

set -eu

if [ "$#" -ne 1 ]; then
    printf '%s\n' 'Usage: scripts/validate-container-gpu.sh IMAGE' >&2
    exit 2
fi

exec docker run --rm --gpus all --entrypoint python "$1" /app/scripts/validate_container_gpu.py

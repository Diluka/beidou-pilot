#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
exec docker build --tag "${HEADLESS_CLIENT_IMAGE:-local/beidou-pilot:local}" \
    --build-arg "BUILD_JOBS=${BUILD_JOBS:-2}" "$@" "$project_root"

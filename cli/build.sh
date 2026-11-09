#!/usr/bin/env bash
set -euo pipefail
CLIENT_ROOT="${CLIENT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
export CLIENT_ROOT
exec docker build --tag local/beidou-v17-client:intel --file "$CLIENT_ROOT/environment/Dockerfile" "$CLIENT_ROOT/environment" "$@"

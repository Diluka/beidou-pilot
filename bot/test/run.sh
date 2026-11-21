#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
BUILD_DIR="$ROOT/tmp/bot-test-build"
mkdir -p "$BUILD_DIR"

(
    cd "$ROOT/third_party/lua"
    gcc -DLUA_USE_LINUX -O0 \
        -o "$BUILD_DIR/lua" \
        $(ls *.c | grep -vE '^(luac|onelua|ltests)\.c$') \
        -lm -ldl
)

cd "$ROOT"
"$BUILD_DIR/lua" bot/test/run.lua

#!/usr/bin/env bash
# Smoke test of the built graphical interface.
#
# The window has to open and stay open. The interface is checked without a
# screen by the Rust tests; this script proves that the binary itself opens
# a window on a machine that may not have one.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BINARY="${1:-target/release/pinterest-gui}"
LOG="$(mktemp)"
PID=""

cleanup() {
    if [ -n "$PID" ]; then
        kill "$PID" 2>/dev/null || true
    fi
    rm -f "$LOG"
}
trap cleanup EXIT

if [ ! -x "$BINARY" ]; then
    echo "the binary $BINARY does not exist" >&2
    exit 1
fi

# A virtual display when the machine has none.
if command -v xvfb-run > /dev/null 2>&1; then
    RUNNER=(xvfb-run -a --server-args="-screen 0 1280x900x24")
else
    RUNNER=()
fi

"${RUNNER[@]}" "$BINARY" > "$LOG" 2>&1 &
PID=$!

sleep 8

if ! kill -0 "$PID" 2>/dev/null; then
    echo "the graphical interface exited on its own" >&2
    cat "$LOG" >&2
    exit 1
fi

if grep -qE "panicked at|ImportError|ModuleNotFoundError|Fatal Python error" "$LOG"; then
    echo "the graphical interface failed" >&2
    cat "$LOG" >&2
    exit 1
fi

echo "OK: the graphical interface opened and stayed open"

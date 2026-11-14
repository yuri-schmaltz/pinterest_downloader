#!/usr/bin/env bash
# Runs the whole product end to end against the fixture server and shows
# what each application does: the Rust CLI in browser and HTTP mode, the
# Python CLI and the two GUIs.
#
# The script needs nothing but the built binaries, the Python virtual
# environment and the fixture server. It never touches the real Pinterest.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CLI="${RUST_CLI:-$ROOT/target/release/pinterest-cli}"
GUI="${RUST_GUI:-$ROOT/target/release/pinterest-gui}"
SERVER="${FIXTURE_SERVER:-$ROOT/target/release/examples/fixture_server}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

WORK="$(mktemp -d)"
SERVER_PID=""
cleanup() {
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

say() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

say "starting the fixture server"
"$SERVER" > "$WORK/server.url" 2> "$WORK/server.err" &
SERVER_PID=$!
URL=""
for _ in $(seq 1 50); do
    URL="$(head -n 1 "$WORK/server.url" 2>/dev/null || true)"
    [ -n "$URL" ] && break
    sleep 0.2
done
if [ -z "$URL" ]; then
    echo "the fixture server did not start" >&2
    cat "$WORK/server.err" >&2
    exit 1
fi
echo "server at $URL"

say "Rust CLI --help"
"$CLI" --help

say "Rust CLI in browser mode (the full journey)"
set +e
"$CLI" "$URL/alice/art/" \
    --mode browser \
    --out "$WORK/downloads" \
    --cache-dir "$WORK/cache" \
    --log-file "$WORK/download_log.json" \
    --json-log
STATUS=$?
set -e
echo "exit code: $STATUS"

say "what landed on the disk"
find "$WORK/downloads" -type f | sort | sed "s|$WORK|\$WORK|"

say "the report"
"$PYTHON" - "$WORK/download_log.json" <<'PY'
import json, sys
totals = None
with open(sys.argv[1], encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)["event"]
        if event["type"] == "finished":
            totals = event["totals"]
print(json.dumps(totals, indent=2, ensure_ascii=False))
PY

say "Rust CLI in HTTP mode"
set +e
"$CLI" "$URL/snapshot/art/" \
    --mode http \
    --out "$WORK/downloads-http" \
    --cache-dir "$WORK/cache-http"
STATUS=$?
set -e
echo "exit code: $STATUS"
find "$WORK/downloads-http" -type f | sort | sed "s|$WORK|\$WORK|"

say "a second run reuses the files that are already there"
set +e
"$CLI" "$URL/alice/art/" \
    --mode browser \
    --out "$WORK/downloads" \
    --cache-dir "$WORK/cache" \
    --log-file "$WORK/download_log2.json"
STATUS=$?
set -e
echo "exit code: $STATUS"
"$PYTHON" - "$WORK/download_log2.json" <<'PY'
import json, sys
totals = None
with open(sys.argv[1], encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)["event"]
        if event["type"] == "finished":
            totals = event["totals"]
print(json.dumps(totals, indent=2, ensure_ascii=False))
PY

say "Rust GUI"
"$GUI" --help 2>&1 | head -30 || true

say "Python CLI"
set +e
"$PYTHON" -m src.pinterest_board_dl --help 2>&1 | head -40
set -e

say "Python GUI (offscreen)"
set +e
QT_QPA_PLATFORM=offscreen timeout 20 "$PYTHON" -m src.pinterest_board_gui 2>&1 | head -20
echo "the GUI was closed by the timeout, as expected"
set -e

say "done"

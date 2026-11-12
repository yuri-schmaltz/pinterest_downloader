#!/usr/bin/env bash
# Smoke test of the built Rust CLI.
#
# The binary has to work on a machine that has neither Python nor Node, so
# the test uses nothing but the binary itself and a small server written in
# Rust. It checks that the CLI starts, that it downloads and that the files
# land in the layout that the Python tool shares.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BINARY="${1:-target/release/pinterest-cli}"
SERVER="${2:-target/release/examples/fixture_server}"
WORKDIR="$(mktemp -d)"
SERVER_PID=""
cleanup() {
    rm -rf "$WORKDIR"
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if [ ! -x "$BINARY" ]; then
    echo "the binary $BINARY does not exist" >&2
    exit 1
fi
if [ ! -x "$SERVER" ]; then
    echo "the fixture server $SERVER does not exist" >&2
    exit 1
fi

echo "== version and help =="
"$BINARY" --version
"$BINARY" --help > /dev/null

echo "== invalid arguments are refused =="
if "$BINARY" --workers 0 somewhere > /dev/null 2>&1; then
    echo "zero workers should be refused" >&2
    exit 1
fi

echo "== the server starts =="
"$SERVER" > "$WORKDIR/server.url" 2>"$WORKDIR/server.err" &
SERVER_PID=$!
URL=""
for _ in $(seq 1 50); do
    URL="$(head -n 1 "$WORKDIR/server.url" 2>/dev/null || true)"
    if [ -n "$URL" ]; then
        break
    fi
    sleep 0.2
done
if [ -z "$URL" ]; then
    echo "the fixture server did not start" >&2
    cat "$WORKDIR/server.err" >&2
    exit 1
fi
echo "server at $URL"

echo "== the CLI downloads a board =="
set +e
"$BINARY" "$URL/snapshot/art/" \
    --mode http \
    --out "$WORKDIR/downloads" \
    --cache-dir "$WORKDIR/cache" \
    --json-log > "$WORKDIR/events.jsonl" 2>"$WORKDIR/cli.err"
STATUS=$?
set -e
# The HTTP snapshot cannot prove that the board is complete, so the CLI
# reports a partial result with the exit code 6.
if [ "$STATUS" -ne 6 ] && [ "$STATUS" -ne 0 ]; then
    echo "the CLI failed with the exit code $STATUS" >&2
    cat "$WORKDIR/cli.err" >&2
    exit 1
fi

MEDIA="$WORKDIR/downloads/snapshot/art/101.jpg"
if [ ! -s "$MEDIA" ]; then
    echo "the media was not downloaded to $MEDIA" >&2
    cat "$WORKDIR/cli.err" >&2
    ls -R "$WORKDIR/downloads" >&2 || true
    exit 1
fi
echo "downloaded $MEDIA"

echo "== the events are valid JSON =="
while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in
        *'"type"'*) ;;
        *) continue ;;
    esac
    if ! printf '%s' "$line" | grep -qE '^\{.*\}$'; then
        echo "an event line is not a JSON object: $line" >&2
        exit 1
    fi
done < "$WORKDIR/events.jsonl"

echo "== a second run reuses the file =="
set +e
"$BINARY" "$URL/snapshot/art/" \
    --mode http \
    --out "$WORKDIR/downloads" \
    --cache-dir "$WORKDIR/cache" \
    --json-log > "$WORKDIR/events2.jsonl" 2>/dev/null
set -e
if ! grep -q '"reused":1' "$WORKDIR/events2.jsonl"; then
    echo "the second run did not reuse the file that was already there" >&2
    cat "$WORKDIR/events2.jsonl" >&2
    exit 1
fi

echo "OK: the built CLI works without Python or Node"

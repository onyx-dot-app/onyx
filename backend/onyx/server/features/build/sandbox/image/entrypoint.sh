#!/bin/bash
# Sandbox container supervisor. Runs `opencode serve` in a restart loop.
#
# The root guest supervisor opens the history gate before running this as UID 1000.

set -euo pipefail

OPENCODE_PORT=4096
SANDBOX_LISTEN_HOST="${SANDBOX_LISTEN_HOST:-0.0.0.0}"
export XDG_DATA_HOME="/workspace/opencode-data"
mkdir -p "$XDG_DATA_HOME"

# opencode's bash tool defaults to 120s, which is too tight for legitimately slow
# tools (e.g. image generation). Raise it so opencode bounds long tools itself
# rather than the coarser api-server inactivity backstop killing the whole turn.
export OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS="${OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS:-180000}"

child_pid=
trap 'if [ -n "$child_pid" ]; then kill -TERM "$child_pid" 2>/dev/null || true; fi; exit 0' SIGTERM SIGINT

if [ -z "${OPENCODE_SERVER_PASSWORD:-}" ]; then
    echo "[entrypoint] WARNING: OPENCODE_SERVER_PASSWORD is empty — opencode serve will run without auth"
fi

# Trust the egress-proxy MITM CA in Chromium's NSS db so browser HTTPS works.
# A failure or missing browser runtime must not block boot.
import_proxy_ca() {
    # Non-zero on no-import so the caller logs the "not imported" branch rather
    # than falsely claiming success (a browser image with a broken CA mount).
    command -v certutil >/dev/null 2>&1 || return 1
    local ca="${SANDBOX_PROXY_CA_BUNDLE_SRC:-/sandbox-ca/ca.crt}"
    [ -f "$ca" ] || return 1
    local nssdb="${HOME:-/home/sandbox}/.pki/nssdb"
    mkdir -p "$nssdb"
    [ -f "$nssdb/cert9.db" ] || certutil -d "sql:$nssdb" -N --empty-password
    certutil -d "sql:$nssdb" -A -t "C,," -n "onyx-proxy" -i "$ca" 2>/dev/null
}
import_proxy_ca \
    && echo "[entrypoint] imported proxy CA into Chromium NSS db" \
    || echo "[entrypoint] proxy CA not imported into NSS (browser runtime absent or CA missing)"

backoff=1
max_backoff=30

while true; do
    echo "[entrypoint] starting opencode serve on $SANDBOX_LISTEN_HOST:$OPENCODE_PORT (XDG_DATA_HOME=$XDG_DATA_HOME)"
    set +e
    /home/sandbox/.opencode/bin/opencode serve --hostname "$SANDBOX_LISTEN_HOST" --port "$OPENCODE_PORT" --print-logs &
    child_pid=$!
    wait "$child_pid"
    exit_code=$?
    set -e
    child_pid=

    echo "[entrypoint] opencode serve exited (code=$exit_code); restarting in ${backoff}s"
    sleep "$backoff"
    backoff=$((backoff * 2))
    if [ "$backoff" -gt "$max_backoff" ]; then
        backoff=$max_backoff
    fi
done

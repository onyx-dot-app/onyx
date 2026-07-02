#!/bin/bash
# Sandbox container supervisor. Runs `opencode serve` in a restart loop.
#
# OPENCODE_SERVER_PASSWORD is the auth input. Kubernetes sets
# OPENCODE_DATA_HOME to a sandbox-global shared volume after the native sidecar
# has restored opencode history. Other backends keep the historical
# /workspace/.opencode-data default.

set -euo pipefail

OPENCODE_PORT=4096
export XDG_DATA_HOME="${OPENCODE_DATA_HOME:-/workspace/.opencode-data}"
mkdir -p "$XDG_DATA_HOME"

child_pid=
trap 'if [ -n "$child_pid" ]; then kill -TERM "$child_pid" 2>/dev/null || true; fi; exit 0' SIGTERM SIGINT

if [ -z "${OPENCODE_SERVER_PASSWORD:-}" ]; then
    echo "[entrypoint] WARNING: OPENCODE_SERVER_PASSWORD is empty — opencode serve will run without auth"
fi

# Trust the egress-proxy MITM CA in Chromium's NSS db (Chromium reads trust only
# from there) so browser HTTPS works. Best-effort — a failure, or no browser
# runtime, must not block boot.
import_proxy_ca() {
    # Non-zero on no-import so the caller logs the "not imported" branch rather
    # than falsely claiming success (a browser image with a broken CA mount).
    command -v certutil >/dev/null 2>&1 || return 1
    local bundle="${SANDBOX_PROXY_CA_BUNDLE_DST:-/etc/ssl/sandbox/ca-bundle.crt}"
    [ -f "$bundle" ] || return 1
    local nssdb="${HOME:-/home/sandbox}/.pki/nssdb"
    mkdir -p "$nssdb"
    [ -f "$nssdb/cert9.db" ] || certutil -d "sql:$nssdb" -N --empty-password
    # The bundle is many roots; `certutil -A` imports one cert at a time, so split.
    local splitdir imported=0 f
    splitdir="$(mktemp -d)"
    csplit -z -f "$splitdir/ca-" -b "%03d.pem" "$bundle" "/BEGIN CERTIFICATE/" "{*}" >/dev/null 2>&1 || true
    for f in "$splitdir"/ca-*.pem; do
        [ -f "$f" ] || continue
        certutil -d "sql:$nssdb" -A -t "C,," -n "proxy-$(basename "$f" .pem)" -i "$f" 2>/dev/null \
            && imported=$((imported + 1))
    done
    rm -rf "$splitdir"
    [ "$imported" -gt 0 ]
}
import_proxy_ca \
    && echo "[entrypoint] imported proxy CA into Chromium NSS db" \
    || echo "[entrypoint] proxy CA not imported into NSS (browser runtime absent or CA missing)"

backoff=1
max_backoff=30

while true; do
    echo "[entrypoint] starting opencode serve on 0.0.0.0:$OPENCODE_PORT (XDG_DATA_HOME=$XDG_DATA_HOME)"
    set +e
    opencode serve --hostname 0.0.0.0 --port "$OPENCODE_PORT" --print-logs &
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

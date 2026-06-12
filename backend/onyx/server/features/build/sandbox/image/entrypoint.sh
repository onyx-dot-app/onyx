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

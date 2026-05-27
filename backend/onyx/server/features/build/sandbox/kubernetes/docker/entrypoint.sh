#!/bin/bash
# Sandbox container supervisor.
#
# Runs `opencode serve` in a restart loop with exponential backoff —
# but ONLY when AGENT_TRANSPORT=serve. The ACP rollback path (the
# documented fallback target) execs `opencode acp` per message; running
# `opencode serve` alongside that path shares XDG_DATA_HOME and can
# corrupt the SQLite session store, recreating exactly the multi-process
# flat-file bug the per-message ACP subprocess model existed to prevent.
#
# When AGENT_TRANSPORT != serve, this script idles (sleep loop) — the
# container stays alive so `kubectl exec`-driven flows still have a
# running pod to attach to.
#
# Environment contract:
#   AGENT_TRANSPORT           "serve" → run opencode serve; anything else
#                             (including unset) → idle and let the ACP
#                             exec path own opencode invocation.
#   OPENCODE_SERVER_PASSWORD  required when AGENT_TRANSPORT=serve. Mounted
#                             from a per-pod K8s Secret by the sandbox
#                             manager. opencode-serve uses HTTP Basic
#                             auth; an empty value disables auth (a fact
#                             we log loudly).
#   XDG_DATA_HOME             set here so opencode's SQLite lands on the
#                             shared workspace volume and is captured by
#                             snapshots / survives container restarts
#                             within the same pod.
#
# Logs go to stdout/stderr so kubectl logs and the sidecar-mirrored log
# paths both pick them up.

set -euo pipefail

OPENCODE_PORT="${OPENCODE_SERVE_PORT:-4096}"
WORKSPACE_DATA_HOME="/workspace/.opencode-data"
TRANSPORT="${AGENT_TRANSPORT:-acp}"

export XDG_DATA_HOME="${XDG_DATA_HOME:-$WORKSPACE_DATA_HOME}"
mkdir -p "$XDG_DATA_HOME"

# Forward SIGTERM/SIGINT to the child so kubectl delete and graceful
# shutdown reach opencode.
child_pid=
trap 'if [ -n "$child_pid" ]; then kill -TERM "$child_pid" 2>/dev/null || true; fi; exit 0' SIGTERM SIGINT

if [ "$TRANSPORT" != "serve" ]; then
    echo "[entrypoint] AGENT_TRANSPORT=$TRANSPORT (not 'serve') — idling; ACP exec path owns opencode invocation"
    # Block forever (interrupted only by SIGTERM trap). Using ``tail -f /dev/null``
    # so the container has a deterministic, low-CPU foreground process.
    tail -f /dev/null &
    child_pid=$!
    wait "$child_pid"
    exit 0
fi

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
    # Exponential backoff capped at max_backoff
    backoff=$((backoff * 2))
    if [ "$backoff" -gt "$max_backoff" ]; then
        backoff=$max_backoff
    fi
done

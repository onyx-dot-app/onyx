#!/usr/bin/env bash
# Boots the in-container backend (alembic migrations, optional Craft templates,
# uvicorn api_server, and — in `full` mode — supervisord-managed celery workers)
# before invoking pytest with whatever args were passed through.
#
# Modes (RUN_WITH_BACKEND_MODE):
#   full     — integration / multitenant suites: uvicorn for api_server plus
#              supervisord for the full celery worker set (the workers
#              autostart from backend/supervisord.conf).
#   api_only — onyx-lite suite: redis/celery aren't available, so we only
#              start uvicorn.
set -euo pipefail

MODE="${RUN_WITH_BACKEND_MODE:-full}"
BACKEND_DIR="/workspace/backend"
SUPERVISORD_CONF="${BACKEND_DIR}/supervisord.conf"
API_HEALTH_URL="http://127.0.0.1:8080/health"
HEALTH_TIMEOUT_SECONDS="${API_SERVER_HEALTH_TIMEOUT_SECONDS:-600}"

cd "$BACKEND_DIR"

if [[ "${MULTI_TENANT:-false}" == "true" ]]; then
    echo "==> Running alembic -n schema_private upgrade head"
    uv run --no-sync alembic -n schema_private upgrade head
else
    echo "==> Running alembic upgrade head"
    uv run --no-sync alembic upgrade head
fi

if [[ "${ENABLE_CRAFT:-false}" == "true" ]]; then
    echo "==> Setting up Craft templates"
    bash "${BACKEND_DIR}/scripts/setup_craft_templates.sh"
fi

if [[ "$MODE" != "api_only" ]]; then
    # The web_search tests exercise OnyxWebCrawler's Playwright fallback.
    # The devcontainer image ships the apt deps; download the browser
    # binary here so its version tracks the lockfile's playwright-python.
    # Playwright has no ubuntu26.04 Chromium build yet — pin to the
    # binary-compatible 24.04 build, matching the host's arch.
    PW_ARCH=$(case $(dpkg --print-architecture) in amd64) echo x64;; arm64) echo arm64;; esac)
    echo "==> Installing Playwright Chromium browser (ubuntu24.04-${PW_ARCH})"
    PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-${PW_ARCH} \
        uv run --no-sync playwright install chromium
fi

SUPERVISORD_PID=""
UVICORN_PID=""

cleanup() {
    local exit_code=$?
    if [[ -n "$UVICORN_PID" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
        kill "$UVICORN_PID" 2>/dev/null || true
        wait "$UVICORN_PID" 2>/dev/null || true
    fi
    if [[ -n "$SUPERVISORD_PID" ]] && kill -0 "$SUPERVISORD_PID" 2>/dev/null; then
        # Belt-and-braces: supervisorctl shutdown is the clean path, but if the
        # socket never came up (e.g. we hit `exit 1` from the socket-wait loop
        # below) it'll fail silently and `wait` would block until the runner
        # timeout. Send SIGTERM as a fallback so `wait` always returns.
        uv run --no-sync supervisorctl -c "$SUPERVISORD_CONF" shutdown >/dev/null 2>&1 || true
        kill "$SUPERVISORD_PID" 2>/dev/null || true
        wait "$SUPERVISORD_PID" 2>/dev/null || true
    fi
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

echo "==> Starting uvicorn api_server"
uv run --no-sync uvicorn onyx.main:app --host 0.0.0.0 --port 8080 \
    > /var/log/api_server.log 2>&1 &
UVICORN_PID=$!

if [[ "$MODE" != "api_only" ]]; then
    echo "==> Starting supervisord (celery workers)"
    uv run --no-sync supervisord -c "$SUPERVISORD_CONF" &
    SUPERVISORD_PID=$!

    echo "==> Waiting for supervisord socket"
    for _ in $(seq 1 30); do
        [[ -S /tmp/supervisor.sock ]] && break
        sleep 1
    done
    if [[ ! -S /tmp/supervisor.sock ]]; then
        echo "ERROR: supervisord socket never appeared at /tmp/supervisor.sock" >&2
        exit 1
    fi
fi

echo "==> Waiting for api_server health (up to ${HEALTH_TIMEOUT_SECONDS}s)"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_SECONDS ))
until curl -fsS "$API_HEALTH_URL" >/dev/null 2>&1; do
    if (( $(date +%s) >= deadline )); then
        echo "ERROR: api_server did not become healthy within ${HEALTH_TIMEOUT_SECONDS}s" >&2
        echo "--- /var/log/api_server.log ---"
        tail -n 200 /var/log/api_server.log 2>/dev/null || true
        if [[ "$MODE" != "api_only" ]]; then
            uv run --no-sync supervisorctl -c "$SUPERVISORD_CONF" status || true
        fi
        exit 1
    fi
    if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
        echo "ERROR: uvicorn exited before becoming healthy" >&2
        echo "--- /var/log/api_server.log ---"
        tail -n 200 /var/log/api_server.log 2>/dev/null || true
        exit 1
    fi
    sleep 2
done
echo "==> api_server is healthy"

if [[ "$MODE" != "api_only" ]]; then
    # Mirror the previous remote supervisorctl healthcheck — fail if any
    # critical worker is in FATAL/BACKOFF/STOPPED. slack_bot / discord_bot /
    # watchdog are intentionally allowed to flap (no creds in CI).
    echo "==> supervisorctl status"
    STATUS_OUTPUT=$(uv run --no-sync supervisorctl -c "$SUPERVISORD_CONF" status || true)
    echo "$STATUS_OUTPUT"
    FAILED=$(echo "$STATUS_OUTPUT" \
        | grep -E "FATAL|BACKOFF|STOPPED" \
        | grep -v "slack_bot\|discord_bot\|watchdog" || true)
    if [[ -n "$FAILED" ]]; then
        echo "ERROR: critical background processes failed to start:" >&2
        echo "$FAILED" >&2
        exit 1
    fi
fi

echo "==> Running pytest $*"
uv run --no-sync pytest "$@"

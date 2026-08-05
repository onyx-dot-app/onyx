#!/usr/bin/env bash
# CI entrypoint for the gateway client suite. The CLI subprocesses under test
# need a real TCP api_server, which the in-process TestClient harness cannot
# provide, so start one in this container (same code, same env) before pytest.
# Expected cwd: backend/ (matches the integration test-runner workdir).
set -uo pipefail

api_server_protocol="${API_SERVER_PROTOCOL:-http}"
api_server_host="${API_SERVER_HOST:-127.0.0.1}"
api_server_port="${API_SERVER_PORT:-8080}"
api_server_url="${api_server_protocol}://${api_server_host}:${api_server_port}"
log_path="/tmp/gateway-clients-api-server.log"

print_server_log_tail() {
  echo "---- api_server log tail ----"
  tail -100 "$log_path" || true
}

# shellcheck disable=SC2329
cleanup() {
  kill "$server_pid" 2> /dev/null || true
  wait "$server_pid" 2> /dev/null || true
}

trap 'exit 130' INT
trap 'exit 143' TERM

if curl -fsS "${api_server_url}/health" > /dev/null 2>&1; then
  echo "A server is already responding at ${api_server_url}; refusing to run against stale code"
  exit 1
fi

if ! uv run --no-sync alembic upgrade head; then
  echo "Failed to migrate the gateway client test database"
  exit 1
fi

uv run --no-sync uvicorn onyx.main:app \
  --host "$api_server_host" --port "$api_server_port" \
  > "$log_path" 2>&1 &
server_pid=$!
trap cleanup EXIT

ready="false"
for _ in $(seq 90); do
  if ! kill -0 "$server_pid" 2> /dev/null; then
    echo "api_server exited before becoming ready at ${api_server_url}/health"
    print_server_log_tail
    exit 1
  fi
  if curl -fsS "${api_server_url}/health" > /dev/null 2>&1; then
    if ! kill -0 "$server_pid" 2> /dev/null; then
      echo "api_server exited while another server answered at ${api_server_url}/health"
      print_server_log_tail
      exit 1
    fi
    ready="true"
    break
  fi
  sleep 2
done

if [ "$ready" != "true" ]; then
  echo "api_server did not become ready at ${api_server_url}/health"
  print_server_log_tail
  exit 1
fi

uv run --no-sync pytest -v --tb=short -rs tests/integration/tests/gateway_clients
status=$?

if [ "$status" -ne 0 ]; then
  print_server_log_tail
fi
exit "$status"

#!/usr/bin/env bash
# CI entrypoint for the gateway client suite. The CLI subprocesses under test
# need a real TCP api_server, which the in-process TestClient harness cannot
# provide, so start one in this container (same code, same env) before pytest.
# Expected cwd: backend/ (matches the integration test-runner workdir).
set -uo pipefail

uv run --no-sync uvicorn onyx.main:app --host 127.0.0.1 --port 8080 \
  > /tmp/gateway-clients-api-server.log 2>&1 &
server_pid=$!

for _ in $(seq 90); do
  if curl -sf http://127.0.0.1:8080/health > /dev/null; then
    break
  fi
  sleep 2
done

uv run --no-sync pytest -v --tb=short -rs tests/integration/tests/gateway_clients
status=$?

kill "$server_pid" 2> /dev/null || true
if [ "$status" -ne 0 ]; then
  echo "---- api_server log tail ----"
  tail -100 /tmp/gateway-clients-api-server.log || true
fi
exit "$status"

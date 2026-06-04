#!/usr/bin/env bash
# Explicit-mode entrypoint. All proxy env vars are set by docker-compose; we
# just verify they're present, log a banner, and idle.

set -euo pipefail

echo "[sandbox-explicit] HTTPS_PROXY=${HTTPS_PROXY:-<unset>}"
echo "[sandbox-explicit] REQUESTS_CA_BUNDLE=${REQUESTS_CA_BUNDLE:-<unset>}"
echo "[sandbox-explicit] NODE_EXTRA_CA_CERTS=${NODE_EXTRA_CA_CERTS:-<unset>}"
echo "[sandbox-explicit] ready"

exec sleep infinity

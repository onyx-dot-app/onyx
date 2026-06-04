#!/usr/bin/env bash
# Transparent-mode entrypoint. No proxy env vars. Waits for the iptables-init
# sidecar to apply rules before exposing the shell, so demos that race the
# init container don't observe an unprotected window.

set -euo pipefail

READY_FILE=/state/ready

echo "[sandbox-transparent] waiting for iptables rules to be installed"
for _ in $(seq 1 300); do
    if [[ -f "$READY_FILE" ]]; then
        echo "[sandbox-transparent] iptables rules ready"
        echo "[sandbox-transparent] ready"
        exec sleep infinity
    fi
    sleep 0.2
done

echo "[sandbox-transparent] FATAL: iptables-init never marked ready"
exit 1

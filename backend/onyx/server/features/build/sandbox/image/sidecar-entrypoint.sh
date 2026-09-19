#!/bin/bash
set -e
trap 'kill 0 2>/dev/null; exit' SIGTERM SIGINT

start_sidecar() {
  while true; do
    /workspace/.venv/bin/python -m sandbox_daemon.server
    sleep 1
  done
}

start_sidecar &
sleep infinity &
wait

#!/bin/bash
set -e
trap 'kill 0 2>/dev/null; exit' SIGTERM SIGINT

start_daemon() {
  while true; do
    /workspace/.venv/bin/python -m push_daemon.server
    sleep 1
  done
}

start_daemon &
sleep infinity &
wait

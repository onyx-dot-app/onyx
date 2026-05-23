#!/bin/bash
set -e
trap 'kill 0 2>/dev/null; exit' SIGTERM SIGINT
sleep infinity &
wait

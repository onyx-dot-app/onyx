#!/bin/sh
# Starts the guest daemon in a sandbox container, as the sandbox user.
# Args go to guest-daemon after --container (for example --listen tcp:...,
# --key-file, --tls-cert, --tls-key). Docker runs it through
# firewall-init (entrypoint mode), which drops to uid 1000 first.
set -eu
if [ "$(id -u)" = 0 ]; then
  echo "sandbox-entrypoint: run as uid 1000, not root" >&2
  exit 1
fi
mkdir -p /tmp/onyx/tool-results /tmp/onyx/artifacts
# tini (PID 1) reaps orphaned command children; the daemon waits only for
# its own children.
exec /usr/bin/tini -s -- /usr/local/bin/guest-daemon --container "$@"

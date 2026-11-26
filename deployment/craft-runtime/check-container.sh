#!/usr/bin/env bash
# Checks the craft-runtime container image: starts the guest daemon in it
# and calls it over TLS (microvm/internal/guestd/containertest).
#   1. Kubernetes shape: uid 1000, no capabilities (firewall-init runs in an
#      init container there, so it is not part of this case).
#   2. Docker shape: firewall-init in entrypoint mode locks egress down to a
#      proxy address, then drops to uid 1000 and starts the daemon.
# Needs docker, openssl and Go (microvm/go.mod).
#
# Usage: deployment/craft-runtime/check-container.sh <image>
set -euo pipefail

image=${1:?usage: check-container.sh <image>}
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
work=$(mktemp -d)
containers=()
network="craft-runtime-check-$$"
cleanup() {
  for c in "${containers[@]}"; do docker rm -f "${c}" >/dev/null 2>&1 || true; done
  docker network rm "${network}" >/dev/null 2>&1 || true
  rm -rf "${work}"
}
trap cleanup EXIT

log() { echo "[check-container] $*" >&2; }

# The container user (uid 1000) reads these through a read-only mount.
chmod 0755 "${work}"
mkdir -m 0755 "${work}/daemon" "${work}/ca"
openssl rand -hex 32 >"${work}/daemon/key"
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 1 \
  -subj /CN=localhost -addext subjectAltName=DNS:localhost,IP:127.0.0.1 \
  -keyout "${work}/daemon/tls.key" -out "${work}/daemon/tls.crt" 2>/dev/null
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 1 \
  -subj /CN=check-proxy-ca -keyout "${work}/ca/ca.key" -out "${work}/ca/ca.crt" 2>/dev/null
chmod 0644 "${work}"/daemon/* "${work}/ca/ca.crt"

daemon_args=(--listen tcp:0.0.0.0:8052 --key-file /run/craft-fc/daemon/key
  --tls-cert /run/craft-fc/daemon/tls.crt --tls-key /run/craft-fc/daemon/tls.key)
# A server next to the sandboxes: the pod case must reach it, the
# locked-down Docker case must not.
docker network create "${network}" >/dev/null
target=$(docker run --detach --network "${network}" --user 1000:1000 --entrypoint python "${image}" \
  -m http.server 8080 --bind 0.0.0.0 --directory /tmp)
containers+=("${target}")
target_ip=$(docker inspect -f "{{(index .NetworkSettings.Networks \"${network}\").IPAddress}}" "${target}")
egress_url="http://${target_ip}:8080/"
log "egress target ${egress_url}"

common=(--detach --network "${network}" --publish 127.0.0.1::8052 --cap-drop ALL --security-opt no-new-privileges
  --shm-size 256m --tmpfs "/tmp:rw,nosuid,nodev,mode=1777"
  --volume "${work}/daemon:/run/craft-fc/daemon:ro")

check() {
  local name=$1 lockdown=$2
  shift 2
  local cid port
  cid=$(docker run --name "craft-runtime-check-${name}-$$" "${common[@]}" "$@")
  containers+=("${cid}")
  port=$(docker port "${cid}" 8052/tcp | head -n 1 | awk -F: '{print $NF}')
  log "${name}: daemon on 127.0.0.1:${port}"
  if ! (cd "${repo}/microvm" && SANDBOXD_ADDR="127.0.0.1:${port}" SANDBOXD_CA="${work}/daemon/tls.crt" \
    SANDBOXD_KEY="${work}/daemon/key" SANDBOXD_LOCKDOWN="${lockdown}" SANDBOXD_EGRESS_URL="${egress_url}" \
    go test -tags container -count=1 -v ./internal/guestd/containertest); then
    docker logs "${cid}" >&2 || true
    exit 1
  fi
  docker logs "${cid}" 2>&1 | tail -n 20 >&2
}

log "the entrypoint refuses root"
# A bad --listen makes a daemon that the guard lets through exit at once;
# only the guard prints the diagnostic.
if out=$(docker run --rm --user 0:0 "${image}" --listen none 2>&1); then
  log "FAIL: the entrypoint started as root"
  exit 1
fi
if [[ "${out}" != *"run as uid 1000, not root"* ]]; then
  log "FAIL: the entrypoint did not refuse root: ${out}"
  exit 1
fi

check pod 0 --user 1000:1000 "${image}" "${daemon_args[@]}"

# 192.0.2.1 (TEST-NET-1) stands in for the sandbox proxy: nothing answers.
check docker 1 --user 0:0 --cap-add NET_ADMIN --cap-add SETPCAP --cap-add SETUID \
  --cap-add SETGID --cap-add CHOWN \
  --env SANDBOX_PROXY_HOST=192.0.2.1 --env SANDBOX_PROXY_PORT=3128 \
  --env SANDBOX_PROXY_BOOTSTRAP_MODE=entrypoint \
  --volume "${work}/ca:/sandbox-ca:ro" \
  --entrypoint /usr/local/bin/firewall-init "${image}" \
  /usr/local/bin/sandbox-entrypoint "${daemon_args[@]}"

log "OK"

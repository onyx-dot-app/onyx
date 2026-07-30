#!/usr/bin/env bash
# Rebuild the backend + sandbox images from this worktree, load them into the
# kind cluster, and restart the pods that run them (sandbox-proxy especially —
# it is NOT telepresence-local and silently runs stale code otherwise).
#
#   refresh-images.sh           rebuild, load, restart
#   refresh-images.sh --check   report staleness only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

CLUSTER_NAME="${CLUSTER_NAME:-onyx-dev}"
BACKEND_IMAGE="${BACKEND_IMAGE:-onyxdotapp/onyx-backend:dev}"
SANDBOX_IMAGE="${SANDBOX_IMAGE:-onyxdotapp/sandbox:dev}"
SANDBOX_IMAGE_DIR="$REPO_ROOT/backend/onyx/server/features/build/sandbox/image"

# docker's .Created is always UTC; strip Z + fractional seconds, then parse
# with GNU date (-d) or BSD date (-j -f).
utc_to_epoch() {
  local ts="${1%Z}"
  ts="${ts%%.*}"
  date -u -d "$ts" +%s 2>/dev/null || date -u -j -f '%Y-%m-%dT%H:%M:%S' "$ts" +%s
}

check_staleness() {
  local stale=0
  local backend_created last_commit commit_epoch
  backend_created=$(docker image inspect "$BACKEND_IMAGE" --format '{{.Created}}' 2>/dev/null || echo "missing")
  last_commit=$(git -C "$REPO_ROOT" log -1 --format=%cI -- backend/)
  commit_epoch=$(git -C "$REPO_ROOT" log -1 --format=%ct -- backend/)
  echo "backend image built:        $backend_created"
  echo "last backend/ commit:       $last_commit"
  if [[ "$backend_created" == "missing" || "$(utc_to_epoch "$backend_created")" -lt "$commit_epoch" ]]; then
    echo "WARNING: $BACKEND_IMAGE is older than the latest backend/ commit — the"
    echo "         sandbox-proxy is running stale code. Run: $0"
    stale=1
  fi
  local podtemplate_image
  podtemplate_image=$(kubectl get podtemplate sandbox-pod -n onyx-sandboxes \
    -o jsonpath='{.template.spec.containers[0].image}' 2>/dev/null || echo "unknown")
  echo "sandbox PodTemplate image:  $podtemplate_image"
  return "$stale"
}

if [[ "${1:-}" == "--check" ]]; then
  check_staleness
  exit $?
fi

echo "==> building $BACKEND_IMAGE"
docker build -t "$BACKEND_IMAGE" "$REPO_ROOT/backend"
kind load docker-image "$BACKEND_IMAGE" --name "$CLUSTER_NAME"

echo "==> building $SANDBOX_IMAGE"
docker build -t "$SANDBOX_IMAGE" "$SANDBOX_IMAGE_DIR"
kind load docker-image "$SANDBOX_IMAGE" --name "$CLUSTER_NAME"

echo "==> pointing sandbox PodTemplate at $SANDBOX_IMAGE"
kubectl patch podtemplate sandbox-pod -n onyx-sandboxes --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/template/spec/containers/0/image\",\"value\":\"$SANDBOX_IMAGE\"}]"

echo "==> restarting sandbox-proxy + api-server onto the new backend image"
kubectl rollout restart deploy/onyx-sandbox-proxy deploy/onyx-api-server -n onyx
kubectl rollout status deploy/onyx-sandbox-proxy -n onyx --timeout=180s

echo "==> done. Existing sandbox pods keep their old image until recycled."

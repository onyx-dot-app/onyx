#!/usr/bin/env bash
# Benchmark sandbox image size and pod spinup latency against a kind cluster.
#
# Per image:
#   - image size (uncompressed, from docker)
#   - cold spinup: image removed from kind node → kind load → pod create → Ready
#   - warm spinup: image already on kind node → pod create → Ready
#
# Each scenario runs $REPS times; min/median/max reported. Pods are created in
# $NS (default onyx-sandboxes) running `sleep` so we measure only the platform
# overhead. The full session-spinup path (KubernetesSandboxManager.provision +
# setup_session_workspace) is more than this measures — but image-pull and
# basic container start dominate the cold-start latency, and that's what
# Dockerfile changes affect.
#
# Usage:
#   bench-sandbox-spinup.sh <image1> [image2 ...]
#
# Examples:
#   # Compare current dev image against a candidate
#   bench-sandbox-spinup.sh onyxdotapp/sandbox:dev onyxdotapp/sandbox:candidate
#
#   # Override defaults
#   REPS=5 NS=onyx-sandboxes \
#     bench-sandbox-spinup.sh onyxdotapp/sandbox:dev
#
# Requires: docker, kind, kubectl, python3. Cluster context must be
# kind-onyx-dev — see docs/dev/local-kubernetes.md for the local setup.
# Full context + recorded numbers: docs/craft/sandbox/image-and-spinup.md.
set -euo pipefail

KIND_CLUSTER="${KIND_CLUSTER:-onyx-dev}"
KIND_NODE="${KIND_NODE:-${KIND_CLUSTER}-control-plane}"
NS="${NS:-onyx-sandboxes}"
REPS="${REPS:-3}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-300s}"

if [ "$#" -lt 1 ]; then
  echo "usage: $(basename "$0") <image1> [image2 ...]" >&2
  exit 2
fi

ctx=$(kubectl config current-context)
if [ "$ctx" != "kind-$KIND_CLUSTER" ]; then
  echo "refusing to run: kubectl context is '$ctx', expected 'kind-$KIND_CLUSTER'" >&2
  exit 2
fi

if ! kubectl get ns "$NS" >/dev/null 2>&1; then
  kubectl create namespace "$NS" >/dev/null
fi

ns_now() { python3 -c 'import time; print(int(time.time_ns()))'; }

bytes_to_mb() { python3 -c "import sys; print(int(int(sys.argv[1])/1024/1024))" "$1"; }

remove_image_from_node() {
  local image="$1"
  docker exec "$KIND_NODE" crictl rmi "docker.io/$image" >/dev/null 2>&1 || true
  docker exec "$KIND_NODE" crictl rmi "$image" >/dev/null 2>&1 || true
}

# One run, prints elapsed ms to stdout.
bench_one() {
  local image="$1" mode="$2"
  local pod
  pod="bench-$(date +%s)-$$-$RANDOM"

  # Eager expansion of $NS/$pod into the trap command is intentional —
  # we want the cleanup to reference the values captured here, not whatever
  # is in scope when the trap fires.
  # shellcheck disable=SC2064
  trap "kubectl -n '$NS' delete pod '$pod' --force --grace-period=0 >/dev/null 2>&1 || true" RETURN

  if [ "$mode" = "cold" ]; then
    remove_image_from_node "$image"
  fi

  local t0
  t0=$(ns_now)

  if [ "$mode" = "cold" ]; then
    kind load docker-image "$image" --name "$KIND_CLUSTER" >/dev/null
  fi

  cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: $pod
  namespace: $NS
  labels:
    app.kubernetes.io/component: spinup-bench
spec:
  restartPolicy: Never
  terminationGracePeriodSeconds: 1
  containers:
    - name: c
      image: $image
      imagePullPolicy: IfNotPresent
      command: ["sleep", "3600"]
      resources:
        requests:
          cpu: "100m"
          memory: "128Mi"
EOF

  kubectl -n "$NS" wait --for=condition=Ready "pod/$pod" --timeout="$WAIT_TIMEOUT" >/dev/null
  local t1
  t1=$(ns_now)

  echo $(( (t1 - t0) / 1000000 ))
}

# Run $REPS iterations, print min / median / max to stdout.
run_scenario() {
  local image="$1" mode="$2"
  local samples=()
  for ((i = 1; i <= REPS; i++)); do
    local ms
    ms=$(bench_one "$image" "$mode")
    samples+=("$ms")
    printf "    r%d: %s ms\n" "$i" "$ms" >&2
  done
  # Sort ascending and pick min/median/max — portable to bash 3 (no mapfile).
  local sorted
  sorted=$(printf '%s\n' "${samples[@]}" | sort -n)
  local n
  n=$(printf '%s\n' "$sorted" | wc -l | tr -d ' ')
  local min median max
  min=$(printf '%s\n' "$sorted" | sed -n 1p)
  median=$(printf '%s\n' "$sorted" | sed -n "$(( (n + 1) / 2 ))p")
  max=$(printf '%s\n' "$sorted" | sed -n "${n}p")
  printf "    min=%s ms  median=%s ms  max=%s ms\n" "$min" "$median" "$max"
}

echo "=== Image sizes ==="
for image in "$@"; do
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "  $image: NOT FOUND locally — pull or build it first" >&2
    exit 2
  fi
  bytes=$(docker image inspect "$image" --format '{{.Size}}')
  printf "  %s: %s MB\n" "$image" "$(bytes_to_mb "$bytes")"
done
echo

for image in "$@"; do
  echo "=== $image ==="
  echo "  cold (image not on node → kind load + pod ready):"
  run_scenario "$image" cold
  echo "  warm (image already on node → pod ready):"
  run_scenario "$image" warm
  echo
done

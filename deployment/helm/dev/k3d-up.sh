#!/usr/bin/env bash
#
# k3d-up.sh — one-command bring-up for the Craft Tilt local-dev path.
#
# Creates the local k3d cluster + registry if absent, writes a standalone
# kubeconfig, creates the onyx namespace, then execs `tilt up` which builds
# the backend image, renders the onyx Helm chart (CNPG / OpenSearch / MinIO
# / Vespa / api / celery / sandbox-proxy / web / ingress-nginx), and wires
# hot-reload of backend source into the running pods.
#
# Idempotent — safe to re-run; if the cluster already exists this skips
# straight to launching Tilt against it.
#
# Usage:
#   bash deployment/helm/dev/k3d-up.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

CLUSTER_NAME="onyx-local"
REGISTRY_NAME="onyx-registry"
# macOS Ventura+ reserves :5000 for AirPlay Receiver; use :5001 instead.
REGISTRY_PORT="5001"
KUBECONFIG_FILE="${HOME}/.kube/onyx-local.yaml"

# ---- 0. Tool check ----

missing=()
for bin in k3d tilt kubectl helm; do
  command -v "${bin}" >/dev/null 2>&1 || missing+=("${bin}")
done
if (( ${#missing[@]} > 0 )); then
  echo "error: missing required tools: ${missing[*]}" >&2
  echo "install everything with: brew bundle (from repo root)" >&2
  exit 1
fi

# ---- 1. Local Docker registry ----
#
# k3d clusters created with `--registry-use` wire their containerd to pull
# from this registry. Tilt pushes locally-built images here and the cluster
# pulls without traversing kind-style `load docker-image` overhead.

if k3d registry list "${REGISTRY_NAME}" >/dev/null 2>&1; then
  echo "k3d registry '${REGISTRY_NAME}' already exists; skipping create"
else
  echo "creating k3d registry '${REGISTRY_NAME}' on :${REGISTRY_PORT}..."
  k3d registry create "${REGISTRY_NAME}" --port "${REGISTRY_PORT}"
fi

# ---- 2. k3d cluster ----
#
# Traefik + ServiceLB are disabled at cluster creation: the onyx chart ships
# ingress-nginx via the upstream subchart, and ServiceLB (klipper-lb) is not
# needed when Tilt port-forwards the relevant Services.

if k3d cluster list "${CLUSTER_NAME}" >/dev/null 2>&1; then
  echo "k3d cluster '${CLUSTER_NAME}' already exists; skipping create"
else
  echo "creating k3d cluster '${CLUSTER_NAME}'..."
  k3d cluster create "${CLUSTER_NAME}" \
    --registry-use "${REGISTRY_NAME}:${REGISTRY_PORT}" \
    --k3s-arg "--disable=traefik@server:0" \
    --k3s-arg "--disable=servicelb@server:0"
fi

# ---- 3. Standalone kubeconfig ----
#
# Write a kubeconfig that contains only this cluster. Worktrees can `.envrc`-
# set KUBECONFIG to this file so prod/staging contexts in the user's main
# ~/.kube/config are unreachable from inside the repo.

mkdir -p "$(dirname "${KUBECONFIG_FILE}")"
k3d kubeconfig get "${CLUSTER_NAME}" > "${KUBECONFIG_FILE}"
echo "wrote kubeconfig to ${KUBECONFIG_FILE}"

# ---- 4. Namespace ----

KUBECONFIG="${KUBECONFIG_FILE}" kubectl get namespace onyx >/dev/null 2>&1 \
  || KUBECONFIG="${KUBECONFIG_FILE}" kubectl create namespace onyx

# ---- 5. CNPG operator ----
#
# Pre-installed as its own Helm release so its mutating webhook is ready
# before Tilt applies the app chart's Cluster CR. Without this, a single
# combined helm install races the Cluster CR against the operator's pod
# startup — the API server forwards the Cluster CR to the webhook before
# the operator pod has Service endpoints, the webhook call fails with
# "no endpoints available", and the install aborts. `--wait` blocks until
# the operator pod is Ready (which means endpoints exist).

helm repo add cnpg https://cloudnative-pg.github.io/charts >/dev/null 2>&1 || true
KUBECONFIG="${KUBECONFIG_FILE}" helm repo update cnpg >/dev/null

if ! KUBECONFIG="${KUBECONFIG_FILE}" helm -n cnpg-system status cnpg >/dev/null 2>&1; then
  echo "installing CNPG operator (one-time)..."
  KUBECONFIG="${KUBECONFIG_FILE}" helm install cnpg cnpg/cloudnative-pg \
    --namespace cnpg-system \
    --create-namespace \
    --version 0.26.0 \
    --wait \
    --timeout 5m
else
  echo "CNPG operator already installed; skipping"
fi

# Same rationale as CNPG: the opstree redis-operator's controller has a
# startup window where applying the Redis CR immediately after the operator
# Deployment fails to materialize (helm install --wait then hangs). Pre-
# install the operator so its controllers are running before the app chart's
# Redis CR is applied.

helm repo add ot-helm https://ot-container-kit.github.io/helm-charts >/dev/null 2>&1 || true
KUBECONFIG="${KUBECONFIG_FILE}" helm repo update ot-helm >/dev/null

if ! KUBECONFIG="${KUBECONFIG_FILE}" helm -n redis-operator-system status redis-operator >/dev/null 2>&1; then
  echo "installing redis-operator (one-time)..."
  KUBECONFIG="${KUBECONFIG_FILE}" helm install redis-operator ot-helm/redis-operator \
    --namespace redis-operator-system \
    --create-namespace \
    --version 0.24.0 \
    --wait \
    --timeout 5m
else
  echo "redis-operator already installed; skipping"
fi

# ---- 6. Clear stuck helm releases ----
#
# If a previous `tilt up` was Ctrl-C'd while `helm install --wait` was still
# running, the release is left in `pending-install` and the next install
# aborts with "another operation in progress". Detect and uninstall any
# such stuck release before relaunching Tilt. (Pods + Services from the
# failed install are reaped along with the release.)

for ns_release in "onyx:onyx" "cnpg-system:cnpg" "redis-operator-system:redis-operator"; do
  ns="${ns_release%%:*}"
  release="${ns_release##*:}"
  # `|| true` because helm status exits non-zero when the release doesn't
  # exist and we have `set -e`; pipefail would otherwise abort the script.
  status=$(KUBECONFIG="${KUBECONFIG_FILE}" helm -n "${ns}" status "${release}" -o json 2>/dev/null \
    | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
  case "${status}" in
    pending-install|pending-upgrade|pending-rollback)
      echo "clearing stuck helm release ${release} (-n ${ns}) status=${status}..."
      KUBECONFIG="${KUBECONFIG_FILE}" helm -n "${ns}" uninstall "${release}" --ignore-not-found || true
      ;;
  esac
done

# ---- 7. Launch Tilt ----
#
# `tilt up` blocks. Open http://localhost:10350 for the UI. Ctrl-C exits;
# state on the cluster persists. Re-run this script to resume.

export KUBECONFIG="${KUBECONFIG_FILE}"
cd "${REPO_ROOT}"

echo
echo "launching 'tilt up' — open http://localhost:10350 for the Tilt UI"
echo

exec tilt up

cat <<EOF

k3d cluster '${CLUSTER_NAME}' is up.

Next:
  export KUBECONFIG=${KUBECONFIG_FILE}
  tilt up

EOF

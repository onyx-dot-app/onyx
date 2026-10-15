#!/usr/bin/env bash
#
# k8s-up.sh — bring up an Onyx dev cluster on the local machine.
#
# Idempotent. See docs/craft/dev/local-kubernetes.md for the full workflow.
#
# Usage:
#   deployment/helm/dev/k8s-up.sh
#   deployment/helm/dev/k8s-up.sh --opensearch-password 'YourStrongPwHere'
#
# Flags:
#   --cluster-name <name>          kind cluster name (default: onyx-dev)
#   --namespace <ns>               k8s namespace (default: onyx)
#   --opensearch-password <pw>     admin password on first install
#                                  (default: generated, printed at the end)
#   --skip-cluster-create          use an existing cluster
#   --skip-helm                    non-Craft cluster-only setup; no runtime install
#   --check-runtime                check an existing Craft runtime without changes
#

set -euo pipefail

CLUSTER_NAME="onyx-dev"
NAMESPACE="onyx"
OPENSEARCH_PASSWORD=""
SKIP_CLUSTER_CREATE=0
SKIP_HELM=0
CHECK_RUNTIME=0
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.33.1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "$SCRIPT_DIR/../charts/onyx" && pwd)"
VALUES_OVERLAY="$SCRIPT_DIR/values-localdev.yaml"

require() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: '$bin' is required but not on PATH" >&2
    echo "see docs/craft/dev/local-kubernetes.md for installation" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cluster-name|--namespace|--opensearch-password)
      if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
        echo "error: $1 requires a value" >&2
        exit 2
      fi
      case "$1" in
        --cluster-name) CLUSTER_NAME="$2" ;;
        --namespace) NAMESPACE="$2" ;;
        --opensearch-password) OPENSEARCH_PASSWORD="$2" ;;
      esac
      shift 2
      ;;
    --skip-cluster-create)  SKIP_CLUSTER_CREATE=1; shift ;;
    --skip-helm)            SKIP_HELM=1; shift ;;
    --check-runtime)        CHECK_RUNTIME=1; shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown flag: $1" >&2
      exit 2
      ;;
  esac
done

require kind
require kubectl
EXPECTED_CTX="kind-$CLUSTER_NAME"

kubectl_dev() {
  kubectl --context "$EXPECTED_CTX" "$@"
}

check_runtime() {
  require docker
  if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
    echo "Craft requires an existing Linux KVM kind cluster with kata-fc." >&2
    echo "See docs/craft/dev/local-kubernetes.md before creating the cluster." >&2
    exit 1
  fi
  if [[ "$(kubectl_dev get runtimeclass kata-fc -o jsonpath='{.handler}')" != kata-fc ]]; then
    echo "Craft requires the kata-fc RuntimeClass handler." >&2
    echo "See docs/craft/dev/local-kubernetes.md for the pinned runtime setup." >&2
    exit 1
  fi
  local nodes node
  nodes="$(kind get nodes --name "$CLUSTER_NAME")"
  for node in $nodes; do
    if ! docker exec "$node" sh -ec \
      'test -c /dev/kvm && test -r /dev/kvm && test -w /dev/kvm && test -c /dev/vhost-vsock && ctr plugins ls | awk '\''$1 ~ /snapshotter/ && $2 == "devmapper" && $4 == "ok" { found = 1 } END { exit !found }'\'''; then
      echo "Node $node needs usable KVM, vhost-vsock, and healthy containerd devmapper." >&2
      echo "See docs/craft/dev/local-kubernetes.md. No runtime was installed or changed." >&2
      exit 1
    fi
    docker exec -i "$node" bash -s -- verify-installed-version \
      < "$SCRIPT_DIR/../../firecracker/install-pinned-firecracker.sh"
  done
  if [[ -z "$nodes" ]]; then
    echo "no kind nodes found for $CLUSTER_NAME" >&2
    exit 1
  fi
}

if [[ "$CHECK_RUNTIME" -eq 1 ]]; then
  check_runtime
  exit 0
fi

if [[ "$SKIP_HELM" -eq 0 ]]; then
  require helm
  check_runtime
fi

# ---- 1. kind cluster ----

if [[ "$SKIP_HELM" -eq 1 && "$SKIP_CLUSTER_CREATE" -eq 0 ]]; then
  if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
    echo "kind cluster '$CLUSTER_NAME' already exists; skipping create"
  else
    echo "creating kind cluster '$CLUSTER_NAME' with node image '$KIND_NODE_IMAGE' ..."
    kind create cluster --name "$CLUSTER_NAME" --image "$KIND_NODE_IMAGE"
  fi
fi

if [[ "$SKIP_HELM" -eq 1 ]]; then
  kubectl_dev get nodes
  echo "Cluster-only setup complete. Craft runtime and Onyx were not installed."
  exit 0
fi

# Use an isolated helm repo config: helm matches chart deps by repo NAME, so a
# stale dev-global repo with a colliding name (we've seen this with
# 'code-interpreter') can shadow ours and break the install.
echo "preparing isolated helm repo config ..."
HELM_DEV_HOME="$(mktemp -d -t onyx-dev-helm-XXXXXX)"
export HELM_REPOSITORY_CONFIG="$HELM_DEV_HOME/repositories.yaml"
export HELM_REPOSITORY_CACHE="$HELM_DEV_HOME/cache"
mkdir -p "$HELM_REPOSITORY_CACHE"
trap 'rm -rf "$HELM_DEV_HOME"' EXIT

# Repo names must match the dep names in Chart.yaml.
helm repo add cloudnative-pg  https://cloudnative-pg.github.io/charts          >/dev/null
helm repo add opensearch      https://opensearch-project.github.io/helm-charts >/dev/null
helm repo add ingress-nginx   https://kubernetes.github.io/ingress-nginx       >/dev/null
helm repo add redis-ot        https://ot-container-kit.github.io/helm-charts   >/dev/null
helm repo add minio           https://charts.min.io/                           >/dev/null
helm repo add code-interpreter https://onyx-dot-app.github.io/python-sandbox/  >/dev/null
helm repo update >/dev/null

echo "updating chart dependencies ..."
helm dependency update "$CHART_DIR" >/dev/null

# Refresh waits for every old backend pod before changing the guest protocol.
existing_deployments="$(kubectl_dev -n "$NAMESPACE" get deployments -l app.kubernetes.io/instance=onyx --ignore-not-found -o name)"
existing_template="$(kubectl_dev -n onyx-sandboxes get podtemplate sandbox-pod --ignore-not-found -o name)"
if [[ -n "$existing_deployments" || -n "$existing_template" ]]; then
  CLUSTER_NAME="$CLUSTER_NAME" NAMESPACE="$NAMESPACE" "$SCRIPT_DIR/refresh-images.sh" --skip-build
else
  CLUSTER_NAME="$CLUSTER_NAME" "$SCRIPT_DIR/refresh-images.sh" --prepare --skip-build
fi

kindnet="$(kubectl_dev -n kube-system get daemonset kindnet --ignore-not-found -o name)"
if [[ -n "$kindnet" ]]; then
  echo "removing the kindnet CPU limit ..."
  kubectl_dev -n kube-system patch daemonset kindnet --type=strategic \
    -p '{"spec":{"template":{"spec":{"containers":[{"name":"kindnet-cni","resources":{"limits":{"cpu":null}}}]}}}}'
  kubectl_dev -n kube-system rollout status daemonset/kindnet --timeout=120s
fi

kubectl_dev get namespace "$NAMESPACE" >/dev/null 2>&1 \
  || kubectl_dev create namespace "$NAMESPACE"
# Pre-created namespaces need ownership metadata for Helm adoption.
kubectl_dev get namespace onyx-sandboxes >/dev/null 2>&1 \
  || kubectl_dev create namespace onyx-sandboxes
kubectl_dev label namespace onyx-sandboxes app.kubernetes.io/managed-by=Helm --overwrite >/dev/null
kubectl_dev annotate namespace onyx-sandboxes meta.helm.sh/release-name=onyx --overwrite >/dev/null
kubectl_dev annotate namespace onyx-sandboxes meta.helm.sh/release-namespace="$NAMESPACE" --overwrite >/dev/null
kubectl_dev label node --all onyx.app/workload=sandbox --overwrite >/dev/null

# Generate a password on first install only; upgrades reuse the existing Secret.
PW_FLAG=()
if ! kubectl_dev -n "$NAMESPACE" get secret onyx-opensearch >/dev/null 2>&1; then
  if [[ -z "$OPENSEARCH_PASSWORD" ]]; then
    # Prefix 'Aa1!' satisfies OpenSearch's complexity rule (upper/lower/digit/symbol).
    OPENSEARCH_PASSWORD="Aa1!$(openssl rand -hex 12)"
    echo "generated opensearch admin password: $OPENSEARCH_PASSWORD"
    echo "(stored in k8s Secret onyx-opensearch — retrieve with:"
    echo "  kubectl -n $NAMESPACE get secret onyx-opensearch -o jsonpath='{.data.opensearch_admin_password}' | base64 -d)"
  fi
  PW_FLAG=(--set "auth.opensearch.values.opensearch_admin_password=$OPENSEARCH_PASSWORD")
fi

echo "helm upgrade --install onyx ..."
# ${PW_FLAG[@]+"${PW_FLAG[@]}"} expands to nothing when empty; bare
# "${PW_FLAG[@]}" errors under `set -u` on subsequent runs.
#
# On a fresh cluster the CNPG operator pod isn't ready when we submit the
# postgres Cluster CR, so its mutating webhook returns "connection refused"
# and helm install fails. The operator becomes ready within ~15s, and a
# `helm upgrade --install` reconciles the failed release cleanly. Retry
# transparently to keep the OOB experience one-shot.
HELM_ATTEMPTS=3
for attempt in $(seq 1 "$HELM_ATTEMPTS"); do
  if helm upgrade --install onyx "$CHART_DIR" \
      --kube-context "$EXPECTED_CTX" \
      -n "$NAMESPACE" \
      -f "$VALUES_OVERLAY" \
      ${PW_FLAG[@]+"${PW_FLAG[@]}"}; then
    break
  fi
  if [[ "$attempt" -lt "$HELM_ATTEMPTS" ]]; then
    echo "helm install failed (attempt $attempt/$HELM_ATTEMPTS) — waiting 20s for operators to be ready, then retrying ..."
    sleep 20
  else
    echo "helm install failed after $HELM_ATTEMPTS attempts" >&2
    exit 1
  fi
done

# ---- 3. telepresence traffic-manager (one-time per cluster) ----

# The vscode (k8s) launch profiles intercept api_server via telepresence,
# which requires a traffic-manager deployment in the cluster. This is
# cluster-scoped and idempotent — re-running on a cluster that already has
# it installed is a no-op.
if command -v telepresence >/dev/null 2>&1; then
  if ! kubectl_dev -n ambassador get deployment traffic-manager >/dev/null 2>&1; then
    echo "installing telepresence traffic-manager (one-time per cluster) ..."
    # On a freshly-installed cluster the default 30s helm timeout inside
    # telepresence is often too tight (CRD webhook bootstraps, image pulls).
    # Retry transparently — same pattern as the chart install above.
    TP_ATTEMPTS=3
    for tp_attempt in $(seq 1 "$TP_ATTEMPTS"); do
      if telepresence helm install \
          --kubeconfig "${KUBECONFIG:-$HOME/.kube/config}" \
          --context "kind-$CLUSTER_NAME" >/dev/null 2>&1; then
        echo "  traffic-manager installed."
        break
      fi
      if [[ "$tp_attempt" -lt "$TP_ATTEMPTS" ]]; then
        echo "  install attempt $tp_attempt/$TP_ATTEMPTS timed out — waiting 20s and retrying ..."
        sleep 20
      else
        echo "  traffic-manager install failed after $TP_ATTEMPTS attempts; run manually:" >&2
        echo "    telepresence helm install --context kind-$CLUSTER_NAME" >&2
      fi
    done
  fi
else
  echo "note: telepresence CLI not found; skipping traffic-manager install."
  echo "  install the OSS binary:"
  echo "    curl -fLo /opt/homebrew/bin/telepresence \\"
  echo "      https://github.com/telepresenceio/telepresence/releases/latest/download/telepresence-darwin-arm64"
  echo "    chmod +x /opt/homebrew/bin/telepresence"
  echo "  see docs/craft/dev/local-kubernetes.md for the full setup"
fi

# ---- 4. next steps ----

cat <<EOF

cluster: kind-$CLUSTER_NAME
namespace: $NAMESPACE
context: $EXPECTED_CTX

next steps:
  1. watch pods come up:
       kubectl --context $EXPECTED_CTX -n $NAMESPACE get pods -w

  2. (optional) connect your host to cluster DNS so you can run api_server
     locally and have it reach in-cluster services. Traffic-manager was
     installed above; just connect:
       telepresence connect -n $NAMESPACE

  3. for features that depend on api_server-source pod identity (e.g.
     NetworkPolicies, in-pod auth via injected env), intercept instead:
       telepresence intercept onyx-api-server \\
         --namespace $NAMESPACE \\
         --port 8080:8080

  4. open vscode and run the "Run All Onyx Services" launch profile.
     Before first run, copy .vscode/.env.k8s.template to .vscode/.env.k8s
     and fill in the <REPLACE THIS> values.

teardown:
  deployment/helm/dev/k8s-down.sh

EOF

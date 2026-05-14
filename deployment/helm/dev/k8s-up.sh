#!/usr/bin/env bash
#
# k8s-up.sh — bring up an Onyx dev cluster on the local machine.
#
# Idempotent: safe to run repeatedly. Creates a kind cluster named `onyx-dev`
# if it doesn't exist, installs / upgrades the Onyx helm chart with the
# local-dev overlay, and prints the next steps for telepresence + vscode.
#
# See docs/dev/local-kubernetes.md for the full workflow and rationale.
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
#   --skip-cluster-create          skip kind create (use an existing cluster)
#   --skip-helm                    only create the cluster, don't install Onyx

set -euo pipefail

CLUSTER_NAME="onyx-dev"
NAMESPACE="onyx"
OPENSEARCH_PASSWORD=""
SKIP_CLUSTER_CREATE=0
SKIP_HELM=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "$SCRIPT_DIR/../charts/onyx" && pwd)"
VALUES_OVERLAY="$CHART_DIR/values-localdev.yaml"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cluster-name)         CLUSTER_NAME="$2"; shift 2 ;;
    --namespace)            NAMESPACE="$2"; shift 2 ;;
    --opensearch-password)  OPENSEARCH_PASSWORD="$2"; shift 2 ;;
    --skip-cluster-create)  SKIP_CLUSTER_CREATE=1; shift ;;
    --skip-helm)            SKIP_HELM=1; shift ;;
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

require() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: '$bin' is required but not on PATH" >&2
    echo "see docs/dev/local-kubernetes.md for installation" >&2
    exit 1
  fi
}

require kind
require helm
require kubectl

# ---- 1. kind cluster ----

if [[ "$SKIP_CLUSTER_CREATE" -eq 0 ]]; then
  if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
    echo "kind cluster '$CLUSTER_NAME' already exists; skipping create"
  else
    echo "creating kind cluster '$CLUSTER_NAME' ..."
    kind create cluster --name "$CLUSTER_NAME"
  fi
fi

# Switch kubectl context to the kind cluster (kind names its contexts kind-<name>).
kubectl config use-context "kind-$CLUSTER_NAME" >/dev/null

# Safety: refuse to operate unless the current context is exactly the kind
# cluster we expect ('kind-<cluster-name>'). The 'onyx' namespace also exists
# in our prod EKS clusters, and the dev may have other kind clusters for
# other projects — so neither namespace nor a loose 'kind-*' match is safe.
EXPECTED_CTX="kind-$CLUSTER_NAME"
CURRENT_CTX="$(kubectl config current-context)"
if [[ "$CURRENT_CTX" != "$EXPECTED_CTX" ]]; then
  echo "refusing to operate: current kubectl context is '$CURRENT_CTX'" >&2
  echo "expected '$EXPECTED_CTX' — pass --cluster-name to target a different kind cluster" >&2
  exit 1
fi

# ---- 2. helm install / upgrade ----

if [[ "$SKIP_HELM" -eq 1 ]]; then
  echo "skipping helm install (--skip-helm)"
  exit 0
fi

kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 \
  || kubectl create namespace "$NAMESPACE"

echo "preparing isolated helm repo config ..."
# We run helm with its own repo config + cache for this install. Why:
# helm matches chart dependencies to registered repos by NAME (not by URL).
# If the dev has a stale repo whose name collides with one of our deps but
# points at a wrong/404 URL (we've seen this with 'code-interpreter'), helm
# picks it over ours and the install fails. Isolating helm's config sidesteps
# all of that — we never touch the dev's global helm state.
HELM_DEV_HOME="$(mktemp -d -t onyx-dev-helm-XXXXXX)"
export HELM_REPOSITORY_CONFIG="$HELM_DEV_HOME/repositories.yaml"
export HELM_REPOSITORY_CACHE="$HELM_DEV_HOME/cache"
mkdir -p "$HELM_REPOSITORY_CACHE"
trap 'rm -rf "$HELM_DEV_HOME"' EXIT

# Register the repos the chart needs, named to match the dep names in
# Chart.yaml (helm matches by name).
helm repo add cloudnative-pg  https://cloudnative-pg.github.io/charts          >/dev/null
helm repo add vespa           https://onyx-dot-app.github.io/vespa-helm-charts >/dev/null
helm repo add opensearch      https://opensearch-project.github.io/helm-charts >/dev/null
helm repo add ingress-nginx   https://kubernetes.github.io/ingress-nginx       >/dev/null
helm repo add redis-ot        https://ot-container-kit.github.io/helm-charts   >/dev/null
helm repo add minio           https://charts.min.io/                           >/dev/null
helm repo add code-interpreter https://onyx-dot-app.github.io/python-sandbox/  >/dev/null
helm repo update >/dev/null

echo "updating chart dependencies ..."
helm dependency update "$CHART_DIR" >/dev/null

# Generate a password on first install if not provided. Subsequent upgrades
# reuse the existing Secret, so the password flag is only needed once.
PW_FLAG=()
if ! kubectl -n "$NAMESPACE" get secret onyx-opensearch >/dev/null 2>&1; then
  if [[ -z "$OPENSEARCH_PASSWORD" ]]; then
    # 24 hex chars, prefixed with 'Aa1!' so it satisfies OpenSearch's
    # complexity requirements (upper, lower, digit, symbol). Using openssl
    # avoids the `tr </dev/urandom | head` SIGPIPE pattern that breaks under
    # `set -o pipefail`.
    OPENSEARCH_PASSWORD="Aa1!$(openssl rand -hex 12)"
    echo "generated opensearch admin password: $OPENSEARCH_PASSWORD"
    echo "(stored in k8s Secret onyx-opensearch — retrieve with:"
    echo "  kubectl -n $NAMESPACE get secret onyx-opensearch -o jsonpath='{.data.opensearch_admin_password}' | base64 -d)"
  fi
  PW_FLAG=(--set "auth.opensearch.values.opensearch_admin_password=$OPENSEARCH_PASSWORD")
fi

echo "helm upgrade --install onyx ..."
# ${PW_FLAG[@]+"${PW_FLAG[@]}"} expands to nothing when the array is empty —
# bare "${PW_FLAG[@]}" errors under `set -u` on subsequent runs (after the
# OpenSearch secret exists and we don't re-supply the password).
helm upgrade --install onyx "$CHART_DIR" \
  -n "$NAMESPACE" \
  -f "$VALUES_OVERLAY" \
  ${PW_FLAG[@]+"${PW_FLAG[@]}"}

# ---- 3. next steps ----

cat <<EOF

cluster: kind-$CLUSTER_NAME
namespace: $NAMESPACE
context: $(kubectl config current-context)

next steps:
  1. watch pods come up:
       kubectl -n $NAMESPACE get pods -w

  2. (optional) connect your host to cluster DNS so you can run api_server
     locally and have it reach in-cluster services:
       telepresence helm install        # one-time, installs traffic-manager
       telepresence connect -n $NAMESPACE

  3. for features that depend on api_server-source pod identity (e.g.
     NetworkPolicies, in-pod auth via injected env), intercept instead:
       telepresence intercept onyx-api-server \\
         --namespace $NAMESPACE \\
         --port 8080:8080 \\
         --env-file .vscode/.env.k8s

  4. open vscode and run the "Run All Onyx Services" launch profile. With
     intercept active, the local api_server inherits the cluster's env
     (postgres creds, redis url, sandbox secret, etc.).

teardown:
  deployment/helm/dev/k8s-down.sh

EOF

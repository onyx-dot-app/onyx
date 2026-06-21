#!/usr/bin/env bash
#
# k8s-up.sh — bring up an Onyx dev cluster on the local machine.
#
# Idempotent. See docs/dev/local-kubernetes.md for the full workflow.
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
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.33.1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "$SCRIPT_DIR/../charts/onyx" && pwd)"
VALUES_OVERLAY="$CHART_DIR/values-localdev.yaml"

require() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: '$bin' is required but not on PATH" >&2
    echo "see docs/dev/local-kubernetes.md for installation" >&2
    exit 1
  fi
}

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

require kind
require helm
require kubectl

# ---- 1. kind cluster ----

if [[ "$SKIP_CLUSTER_CREATE" -eq 0 ]]; then
  if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
    echo "kind cluster '$CLUSTER_NAME' already exists; skipping create"
  else
    echo "creating kind cluster '$CLUSTER_NAME' with node image '$KIND_NODE_IMAGE' ..."
    kind create cluster --name "$CLUSTER_NAME" --image "$KIND_NODE_IMAGE"
  fi
fi

kubectl config use-context "kind-$CLUSTER_NAME" >/dev/null

# Refuse to operate unless the current context is exactly the expected kind
# cluster: the 'onyx' namespace exists in prod EKS too, and other kind clusters
# may also be present.
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
# The chart also templates the onyx-sandboxes namespace (see
# templates/sandbox-namespace.yaml). We pre-create it here so local setup can
# label nodes before helm install runs, but we must stamp Helm ownership
# metadata or `helm install` refuses to adopt the namespace.
kubectl get namespace onyx-sandboxes >/dev/null 2>&1 \
  || kubectl create namespace onyx-sandboxes
kubectl label   namespace onyx-sandboxes app.kubernetes.io/managed-by=Helm --overwrite >/dev/null
kubectl annotate namespace onyx-sandboxes meta.helm.sh/release-name=onyx --overwrite >/dev/null
kubectl annotate namespace onyx-sandboxes meta.helm.sh/release-namespace="$NAMESPACE" --overwrite >/dev/null
kubectl label node --all onyx.app/workload=sandbox --overwrite >/dev/null 2>&1

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
helm repo add vespa           https://onyx-dot-app.github.io/vespa-helm-charts >/dev/null
helm repo add opensearch      https://opensearch-project.github.io/helm-charts >/dev/null
helm repo add ingress-nginx   https://kubernetes.github.io/ingress-nginx       >/dev/null
helm repo add redis-ot        https://ot-container-kit.github.io/helm-charts   >/dev/null
helm repo add minio           https://charts.min.io/                           >/dev/null
helm repo add code-interpreter https://onyx-dot-app.github.io/python-sandbox/  >/dev/null
helm repo update >/dev/null

echo "updating chart dependencies ..."
helm dependency update "$CHART_DIR" >/dev/null

# Generate a password on first install only; upgrades reuse the existing Secret.
PW_FLAG=()
if ! kubectl -n "$NAMESPACE" get secret onyx-opensearch >/dev/null 2>&1; then
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
  if ! kubectl -n ambassador get deployment traffic-manager >/dev/null 2>&1; then
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
  echo "  install with: brew install datawire/blackbird/telepresence-oss"
fi

# ---- 4. next steps ----

cat <<EOF

cluster: kind-$CLUSTER_NAME
namespace: $NAMESPACE
context: $(kubectl config current-context)

next steps:
  1. watch pods come up:
       kubectl -n $NAMESPACE get pods -w

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

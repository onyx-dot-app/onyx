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
#   --skip-cluster-create          skip kind create (use an existing cluster)
#   --skip-helm                    only create the cluster, don't install Onyx
#
# Environment:
#   ONYX_DEV_CA_DIR   directory of extra root CAs to trust inside the nodes,
#                     one PEM certificate per .crt file. Needed behind a
#                     TLS-intercepting proxy, which makes image pulls fail
#                     with "x509: certificate signed by unknown authority".
#                     On macOS the script populates this from the System
#                     keychain automatically.

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

# Private root CAs to trust inside the nodes. A TLS-intercepting corporate
# proxy re-signs registry traffic with its own root: the host trusts it, but
# containerd in the node ships only the stock Debian bundle, so image pulls
# fail with `x509: certificate signed by unknown authority`. Set ONYX_DEV_CA_DIR
# to curate the set by hand — one PEM certificate per `.crt` file.
CA_DIR="${ONYX_DEV_CA_DIR:-$HOME/.onyx-dev/ca-certificates}"
NODE_CA_DIR="/usr/local/share/ca-certificates"

require() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: '$bin' is required but not on PATH" >&2
    echo "see docs/craft/dev/local-kubernetes.md for installation" >&2
    exit 1
  fi
}

# Copy the machine's installed root CAs into CA_DIR, one certificate per file.
# Reads only the System keychain, which holds admin/MDM-installed certs — the
# public roots live in SystemRootCertificates.keychain and the node has those
# already.
collect_host_ca_certs() {
  mkdir -p "$CA_DIR"

  if [[ "$(uname -s)" != "Darwin" ]]; then
    return 0
  fi

  local work part fingerprint target added=0
  work="$(mktemp -d -t onyx-dev-ca-XXXXXX)"

  security find-certificate -a -p /Library/Keychains/System.keychain \
    >"$work/bundle" 2>/dev/null || true

  # update-ca-certificates skips any file holding more than one certificate.
  awk -v dir="$work" \
    '/^-----BEGIN CERTIFICATE-----$/ { n += 1 } n { print >> (dir "/part-" n) }' \
    "$work/bundle"

  for part in "$work"/part-*; do
    [[ -f "$part" ]] || continue
    # Trust anchors only. The keychain also holds leaf identities (MDM, device)
    # which must not become roots. macOS ships LibreSSL, which has no `-ext`.
    if ! openssl x509 -in "$part" -noout -text 2>/dev/null | grep -q "CA:TRUE"; then
      continue
    fi
    fingerprint="$(openssl x509 -in "$part" -noout -fingerprint -sha256 2>/dev/null |
      tr -d ':' | cut -d= -f2 | cut -c1-16)"
    [[ -n "$fingerprint" ]] || continue
    target="$CA_DIR/host-$fingerprint.crt"
    if ! cmp -s "$part" "$target"; then
      cp "$part" "$target"
      added=$((added + 1))
    fi
  done

  rm -rf "$work"
  if [[ "$added" -gt 0 ]]; then
    echo "collected $added host root CA(s) into $CA_DIR"
  fi
}

# extraMounts put the certificates in the node, but only update-ca-certificates
# writes them into the bundle containerd actually reads. Also covers clusters
# created before this mount existed, by copying the files in directly.
trust_host_ca_certs_in_nodes() {
  local node cert before after

  if ! compgen -G "$CA_DIR/*.crt" >/dev/null; then
    return 0
  fi

  for node in $(kind get nodes --name "$CLUSTER_NAME"); do
    for cert in "$CA_DIR"/*.crt; do
      docker exec "$node" test -f "$NODE_CA_DIR/$(basename "$cert")" 2>/dev/null \
        || docker cp "$cert" "$node:$NODE_CA_DIR/" >/dev/null
    done

    before="$(docker exec "$node" sha256sum /etc/ssl/certs/ca-certificates.crt 2>/dev/null | cut -d' ' -f1)"
    docker exec "$node" update-ca-certificates >/dev/null 2>&1 || true
    after="$(docker exec "$node" sha256sum /etc/ssl/certs/ca-certificates.crt 2>/dev/null | cut -d' ' -f1)"

    # containerd reads the bundle once at start, so it needs a restart to pick
    # up new anchors. Skip it when the bundle did not change.
    if [[ "$before" != "$after" ]]; then
      echo "trusting host root CAs in $node; restarting containerd ..."
      docker exec "$node" systemctl restart containerd
    fi
  done
}

write_kind_config() {
  cat >"$1" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraMounts:
      - hostPath: ${CA_DIR}
        containerPath: ${NODE_CA_DIR}
EOF
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

collect_host_ca_certs

if [[ "$SKIP_CLUSTER_CREATE" -eq 0 ]]; then
  if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
    echo "kind cluster '$CLUSTER_NAME' already exists; skipping create"
  else
    echo "creating kind cluster '$CLUSTER_NAME' with node image '$KIND_NODE_IMAGE' ..."
    KIND_CONFIG="$(mktemp -t onyx-dev-kind-XXXXXX)"
    write_kind_config "$KIND_CONFIG"
    kind create cluster \
      --name "$CLUSTER_NAME" \
      --image "$KIND_NODE_IMAGE" \
      --config "$KIND_CONFIG"
    rm -f "$KIND_CONFIG"
  fi
fi

trust_host_ca_certs_in_nodes

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

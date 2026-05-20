#!/usr/bin/env bash
#
# k8s-down.sh — tear down the Onyx dev cluster.
#
# Default: uninstall the helm release and delete the kind cluster (wipes data).
# --keep-cluster preserves the cluster and its PVCs for reinstall.
#
# Usage:
#   deployment/helm/dev/k8s-down.sh
#   deployment/helm/dev/k8s-down.sh --keep-cluster
#
# Flags:
#   --cluster-name <name>   kind cluster name (default: onyx-dev)
#   --namespace <ns>        k8s namespace (default: onyx)
#   --keep-cluster          uninstall Onyx but keep the kind cluster

set -euo pipefail

CLUSTER_NAME="onyx-dev"
NAMESPACE="onyx"
KEEP_CLUSTER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cluster-name) CLUSTER_NAME="$2"; shift 2 ;;
    --namespace)    NAMESPACE="$2"; shift 2 ;;
    --keep-cluster) KEEP_CLUSTER=1; shift ;;
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

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "kind cluster '$CLUSTER_NAME' does not exist; nothing to do"
  exit 0
fi

kubectl config use-context "kind-$CLUSTER_NAME" >/dev/null

# Same context safety guard as k8s-up.sh — the 'onyx' namespace exists in prod
# EKS too, so refuse anything but the exact expected kind context.
EXPECTED_CTX="kind-$CLUSTER_NAME"
CURRENT_CTX="$(kubectl config current-context)"
if [[ "$CURRENT_CTX" != "$EXPECTED_CTX" ]]; then
  echo "refusing to operate: current kubectl context is '$CURRENT_CTX'" >&2
  echo "expected '$EXPECTED_CTX' — pass --cluster-name to target a different kind cluster" >&2
  exit 1
fi

if [[ "$KEEP_CLUSTER" -eq 1 ]]; then
  # PVCs are intentionally left intact so the next install reuses postgres /
  # opensearch / vespa / minio data. For a clean slate, omit --keep-cluster
  # or run: kubectl -n $NAMESPACE delete pvc --all
  echo "uninstalling helm release 'onyx' in namespace '$NAMESPACE' ..."
  helm uninstall onyx -n "$NAMESPACE" 2>/dev/null || true

  echo "done. cluster 'kind-$CLUSTER_NAME' is preserved (PVCs intact)."
else
  echo "deleting kind cluster '$CLUSTER_NAME' (this wipes all cluster data) ..."
  kind delete cluster --name "$CLUSTER_NAME"
fi

#!/usr/bin/env bash
# Creates the egress-poc-ca Secret in the egress-poc namespace from the
# CA files on disk. Idempotent: deletes any existing Secret first.
#
# Expects ENCRYPTION_KEY_SECRET to be the SAME passphrase that ca/gen-ca.sh
# used when encrypting ca.key.enc. Default matches gen-ca.sh's default.

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
CA_DIR="$DIR/ca"
NAMESPACE="${NAMESPACE:-egress-poc}"
ENCRYPTION_KEY_SECRET="${ENCRYPTION_KEY_SECRET:-poc-key-not-for-prod}"

if [[ ! -f "$CA_DIR/ca.crt" || ! -f "$CA_DIR/ca.key.enc" ]]; then
    echo "error: ca/ca.crt or ca/ca.key.enc missing — run ca/gen-ca.sh first" >&2
    exit 1
fi

kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 \
  || kubectl create namespace "$NAMESPACE"

kubectl -n "$NAMESPACE" delete secret egress-poc-ca --ignore-not-found

kubectl -n "$NAMESPACE" create secret generic egress-poc-ca \
    --from-file=ca.crt="$CA_DIR/ca.crt" \
    --from-file=ca.key.enc="$CA_DIR/ca.key.enc" \
    --from-literal=passphrase="$ENCRYPTION_KEY_SECRET"

echo "[ok] egress-poc-ca secret created in namespace $NAMESPACE"

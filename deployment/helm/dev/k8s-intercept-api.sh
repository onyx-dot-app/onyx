#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
readonly REPO_ROOT
readonly ENV_FILE="${REPO_ROOT}/.vscode/.env.k8s"
readonly KUBE_CONTEXT="kind-onyx-dev"
readonly KUBE_NAMESPACE="onyx"
readonly KUBECTL=(
  kubectl
  --context "$KUBE_CONTEXT"
  --namespace "$KUBE_NAMESPACE"
)

require_command() {
  local command_name="$1"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "error: ${command_name} was not found" >&2
    exit 1
  fi
}

update_env_value() {
  local key="$1"
  local value="$2"
  local temporary_file

  temporary_file="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    index($0, key "=") == 1 { print key "=" value; found = 1; next }
    { print }
    END { if (!found) print key "=" value }
  ' "$ENV_FILE" >"$temporary_file"
  chmod 600 "$temporary_file"
  mv "$temporary_file" "$ENV_FILE"
}

read_secret() {
  local secret_name="$1"
  local secret_key="$2"
  local secret_value

  secret_value="$(
    "${KUBECTL[@]}" get secret "$secret_name" \
      -o "jsonpath={.data.${secret_key}}" 2>/dev/null | base64 -d || true
  )"
  if [[ -z "$secret_value" ]]; then
    echo "error: could not read ${secret_key} from ${secret_name}" >&2
    exit 1
  fi

  printf '%s' "$secret_value"
}

require_command kubectl
require_command telepresence

if ! kubectl config get-contexts "$KUBE_CONTEXT" -o name >/dev/null 2>&1; then
  echo "error: kubectl context ${KUBE_CONTEXT} was not found" >&2
  echo "run deployment/helm/dev/k8s-up.sh first" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: ${ENV_FILE} was not found" >&2
  echo "copy .vscode/.env.k8s.template and set its required values" >&2
  exit 1
fi

opensearch_password="$(
  read_secret onyx-opensearch opensearch_admin_password
)"
encryption_key="$(
  read_secret onyx-encryption-key encryption_key_secret
)"

update_env_value OPENSEARCH_ADMIN_PASSWORD "$opensearch_password"
update_env_value ENCRYPTION_KEY_SECRET "$encryption_key"
unset opensearch_password encryption_key

telepresence connect \
  --context "$KUBE_CONTEXT" \
  --namespace "$KUBE_NAMESPACE"
telepresence leave onyx-api-server >/dev/null 2>&1 || true
telepresence intercept onyx-api-server \
  --namespace "$KUBE_NAMESPACE" \
  --port 8080:8080 \
  --mount=false

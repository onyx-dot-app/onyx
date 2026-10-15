#!/usr/bin/env bash
#
# craft-up.sh — one-shot Onyx Craft dev setup on the local machine.
#
# Idempotent wrapper around k8s-up.sh that also builds and loads the sandbox
# image and bootstraps .vscode/.env.k8s from the tracked template. Safe to
# re-run on a partially-set-up machine.
#
# See docs/craft/dev/local-kubernetes.md for the full workflow.
#
# Usage:
#   deployment/helm/dev/craft-up.sh
#   deployment/helm/dev/craft-up.sh --skip-sandbox-image
#
# Flags:
#   --cluster-name <name>          kind cluster name (default: onyx-dev)
#   --skip-cluster-create          use the configured kind cluster
#   --skip-helm                    non-Craft cluster-only setup; no image builds
#   --skip-sandbox-image           skip the sandbox image build, but still run
#                                  `kind load` so a previously-built image gets
#                                  picked up by a fresh cluster
#   -h | --help                    show this help
#
# Any unrecognised flag is passed through to k8s-up.sh.

set -euo pipefail

CLUSTER_NAME="onyx-dev"
SKIP_HELM=0
SKIP_SANDBOX_IMAGE=0
PASSTHROUGH=()

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ENV_K8S="$REPO_ROOT/.vscode/.env.k8s"
ENV_K8S_TEMPLATE="$REPO_ROOT/.vscode/.env.k8s.template"
ENV_WEB="$REPO_ROOT/.vscode/.env.web"
ENV_WEB_TEMPLATE="$REPO_ROOT/.vscode/env.web_template.txt"

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
    --cluster-name)
      if [[ $# -lt 2 ]]; then
        echo "error: --cluster-name requires a value" >&2
        exit 2
      fi
      CLUSTER_NAME="$2"
      PASSTHROUGH+=("$1" "$2")
      shift 2
      ;;
    --skip-cluster-create)
      PASSTHROUGH+=("$1")
      shift
      ;;
    --skip-helm)
      SKIP_HELM=1
      PASSTHROUGH+=("$1")
      shift
      ;;
    --skip-sandbox-image)
      SKIP_SANDBOX_IMAGE=1
      shift
      ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      PASSTHROUGH+=("$1")
      shift
      ;;
  esac
done

require docker
require kind
require kubectl
# helm is only invoked by k8s-up.sh when it actually installs the chart;
# with --skip-helm the cluster-only workflow shouldn't demand helm on PATH.
if [[ "$SKIP_HELM" -eq 0 ]]; then
  require helm
fi

if [[ "$SKIP_HELM" -eq 1 ]]; then
  exec "$SCRIPT_DIR/k8s-up.sh" ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
fi

# Check the configured runtime before builds, env copies, or cluster changes.
"$SCRIPT_DIR/k8s-up.sh" --check-runtime ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
IMAGE_FLAGS=(--prepare)
if [[ "$SKIP_SANDBOX_IMAGE" -eq 1 ]]; then
  IMAGE_FLAGS+=(--skip-sandbox-image)
fi
CLUSTER_NAME="$CLUSTER_NAME" "$SCRIPT_DIR/refresh-images.sh" "${IMAGE_FLAGS[@]}"

echo "==> bringing up kind cluster + helm install (k8s-up.sh) ..."
"$SCRIPT_DIR/k8s-up.sh" ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}

# ---- 2. bootstrap the vscode env files if missing ----

# Never overwrite an existing file: it holds dev-edited secrets.
bootstrap_env_file() {
  local dest="$1" template="$2" hint="${3:-}"
  local name; name="$(basename "$dest")"

  if [[ -f "$dest" ]]; then
    echo "==> .vscode/$name already exists; leaving it untouched"
    return
  fi
  if [[ ! -f "$template" ]]; then
    echo "error: $(basename "$template") missing — cannot bootstrap $name" >&2
    exit 1
  fi
  cp "$template" "$dest"
  echo "==> created .vscode/$name from template${hint:+ — $hint}"
}

bootstrap_env_file "$ENV_K8S" "$ENV_K8S_TEMPLATE" \
  "edit <REPLACE THIS> values (at minimum GEN_AI_API_KEY)"

bootstrap_env_file "$ENV_WEB" "$ENV_WEB_TEMPLATE"

cat <<EOF

craft-up complete.

next steps:
  1. open vscode and run the "Run All Onyx Services (k8s)" launch profile.
     (api + web + every celery worker + beat, intercepting api_server via
     telepresence.)

  2. visit http://localhost:3000 once services are up.

  3. rebuild loop for the sandbox image:
       make craft-sandbox-image

teardown:
  make craft-down

EOF

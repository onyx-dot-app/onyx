#!/usr/bin/env bash
#
# craft-up.sh — one-shot Onyx Craft dev setup on the local machine.
#
# Idempotent wrapper around k8s-up.sh that also builds and loads the sandbox
# image and bootstraps .vscode/.env.k8s from the tracked template. Safe to
# re-run on a partially-set-up machine.
#
# See docs/dev/local-kubernetes.md for the full workflow.
#
# Usage:
#   deployment/helm/dev/craft-up.sh
#   deployment/helm/dev/craft-up.sh --skip-sandbox-image
#
# Flags:
#   --cluster-name <name>          kind cluster name (default: onyx-dev)
#   --skip-cluster-create          skip kind create (passthrough to k8s-up.sh)
#   --skip-helm                    only create the cluster (passthrough)
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
SANDBOX_IMAGE="onyxdotapp/sandbox:dev"
SANDBOX_IMAGE_DIR="$REPO_ROOT/backend/onyx/server/features/build/sandbox/image"
ENV_K8S="$REPO_ROOT/.vscode/.env.k8s"
ENV_K8S_TEMPLATE="$REPO_ROOT/.vscode/.env.k8s.template"

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

# ---- 1. cluster bring-up (delegates) ----

echo "==> bringing up kind cluster + helm install (k8s-up.sh) ..."
"$SCRIPT_DIR/k8s-up.sh" ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}

# ---- 2. bootstrap .vscode/.env.k8s if missing ----

if [[ -f "$ENV_K8S" ]]; then
  echo "==> .vscode/.env.k8s already exists; leaving it untouched"
else
  if [[ ! -f "$ENV_K8S_TEMPLATE" ]]; then
    echo "error: .vscode/.env.k8s.template missing — cannot bootstrap .env.k8s" >&2
    exit 1
  fi
  cp "$ENV_K8S_TEMPLATE" "$ENV_K8S"
  echo "==> created .vscode/.env.k8s from template — edit <REPLACE THIS> values (at minimum GEN_AI_API_KEY)"
fi

# ---- 3. sandbox image build + load ----

if [[ "$SKIP_SANDBOX_IMAGE" -eq 1 ]]; then
  echo "==> skipping sandbox image build (--skip-sandbox-image)"
else
  echo "==> building $SANDBOX_IMAGE ..."
  docker build -t "$SANDBOX_IMAGE" "$SANDBOX_IMAGE_DIR"
fi

echo "==> loading $SANDBOX_IMAGE into kind node ($CLUSTER_NAME) ..."
kind load docker-image "$SANDBOX_IMAGE" --name "$CLUSTER_NAME"

# ---- 4. next steps ----

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

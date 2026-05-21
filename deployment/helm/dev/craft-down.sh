#!/usr/bin/env bash
#
# craft-down.sh — symmetric teardown of `make craft-up`.
#
# Quits telepresence, deletes the kind cluster (via k8s-down.sh), and
# optionally removes locally-built images. Never touches .vscode/.env.k8s —
# it contains user-edited secrets.
#
# See docs/dev/local-kubernetes.md for the full workflow.
#
# Usage:
#   deployment/helm/dev/craft-down.sh
#   deployment/helm/dev/craft-down.sh --remove-images
#   deployment/helm/dev/craft-down.sh --keep-cluster
#
# Flags:
#   --cluster-name <name>   kind cluster name (default: onyx-dev)
#   --keep-cluster          uninstall helm but preserve the kind cluster
#                           and its PVCs (passthrough to k8s-down.sh)
#   --remove-images         also `docker rmi` the locally-built sandbox and
#                           backend dev images (off by default — rebuilding
#                           from cache is fast)
#   -h | --help             show this help

set -euo pipefail

REMOVE_IMAGES=0
PASSTHROUGH=()

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cluster-name)
      if [[ $# -lt 2 ]]; then
        echo "error: --cluster-name requires a value" >&2
        exit 2
      fi
      PASSTHROUGH+=("$1" "$2")
      shift 2
      ;;
    --keep-cluster)
      PASSTHROUGH+=("$1")
      shift
      ;;
    --remove-images)
      REMOVE_IMAGES=1
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

# ---- 1. quit telepresence ----

if command -v telepresence >/dev/null 2>&1; then
  echo "==> quitting telepresence (if running) ..."
  telepresence quit 2>/dev/null || true
else
  echo "==> telepresence not installed; skipping quit"
fi

# ---- 2. cluster teardown (delegates; inherits context-safety guard) ----

echo "==> tearing down kind cluster + helm release (k8s-down.sh) ..."
"$SCRIPT_DIR/k8s-down.sh" ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}

# ---- 3. optional image cleanup ----

if [[ "$REMOVE_IMAGES" -eq 1 ]]; then
  echo "==> removing locally-built dev images ..."
  docker rmi onyxdotapp/sandbox:dev onyxdotapp/onyx-backend:dev 2>/dev/null || true
fi

# ---- 4. next steps ----

cat <<EOF

craft-down complete.

next steps:
  Run \`make craft-up\` to bring it back. Your .vscode/.env.k8s was not touched.

EOF

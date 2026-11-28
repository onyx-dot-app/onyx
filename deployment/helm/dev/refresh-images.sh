#!/usr/bin/env bash
# Refresh changed local images, or report checkout changes with --check.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/dev.py" \
  --cluster-name "${CLUSTER_NAME:-onyx-dev}" \
  --namespace "${NAMESPACE:-onyx}" images "$@"

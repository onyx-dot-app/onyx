#!/usr/bin/env bash
# Refresh the local backend and guest together. No sandbox pod is deleted.
# Usage: refresh-images.sh [--check|--prepare|--skip-build|--skip-sandbox-image]
#
# Stop host Onyx API, Celery workers, and beat processes before refresh,
# including VS Code "(k8s)" services. Restart them only after refresh succeeds.
# In-cluster rollouts do not stop host processes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

CLUSTER_NAME="${CLUSTER_NAME:-onyx-dev}"
NAMESPACE="${NAMESPACE:-onyx}"
EXPECTED_CTX="kind-$CLUSTER_NAME"
BACKEND_IMAGE="onyxdotapp/onyx-backend:dev"
SANDBOX_IMAGE="onyxdotapp/sandbox:dev"
CHECK=0
PREPARE=0
SKIP_BUILD=0
SKIP_SANDBOX_IMAGE=0

for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --prepare) PREPARE=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    --skip-sandbox-image) SKIP_SANDBOX_IMAGE=1 ;;
    -h|--help) sed -n '2,7s/^# \{0,1\}//p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

kubectl_dev() {
  kubectl --context "$EXPECTED_CTX" --namespace "$NAMESPACE" "$@"
}

require_empty_sandboxes() {
  local namespace pods
  namespace="$(kubectl --context "$EXPECTED_CTX" get namespace onyx-sandboxes --ignore-not-found -o name)"
  if [[ -z "$namespace" ]]; then
    return
  fi
  pods="$(kubectl --context "$EXPECTED_CTX" --namespace onyx-sandboxes get pods -o name)"
  if [[ -n "$pods" ]]; then
    echo "refusing to update images while sandbox pods exist:" >&2
    echo "$pods" >&2
    echo "Stop traffic and snapshot sessions with the current release first." >&2
    echo "Stop host Onyx API, Celery workers, and beat processes," >&2
    echo 'including VS Code "(k8s)" services. Restart them only after refresh succeeds.' >&2
    echo "No sandbox pods were deleted. See docs/craft/infra/firecracker.md." >&2
    exit 1
  fi
}

load_guest_image() {
  local nodes node cluster_label platform expected_id actual_status
  nodes="$(kind get nodes --name "$CLUSTER_NAME")"
  if [[ -z "$nodes" ]]; then
    echo "no kind nodes found for $CLUSTER_NAME" >&2
    exit 1
  fi
  for node in $nodes; do
    cluster_label="$(docker inspect -f '{{ index .Config.Labels "io.x-k8s.kind.cluster" }}' "$node")"
    if [[ "$cluster_label" != "$CLUSTER_NAME" ]]; then
      echo "refusing to load $node; expected kind cluster $CLUSTER_NAME, got $cluster_label" >&2
      exit 1
    fi
  done
  platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$SANDBOX_IMAGE")"
  if [[ "$platform" != linux/amd64 && "$platform" != linux/arm64 ]]; then
    echo "unsupported guest image platform: $platform" >&2
    exit 1
  fi
  # Docker's image ID can identify an index or manifest instead of the CRI config.
  expected_id="$(docker image save --platform "$platform" "$SANDBOX_IMAGE" \
    | tar -xOf - manifest.json \
    | uv run --project "$REPO_ROOT" --frozen --no-sync python -c '
import json
import re
import sys

manifest = json.load(sys.stdin)
if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
    raise SystemExit("expected exactly one saved guest image manifest")
config = manifest[0].get("Config")
if not isinstance(config, str):
    raise SystemExit("invalid saved guest config digest")
match = re.fullmatch(r"(?:([0-9a-f]{64})\.json|blobs/sha256/([0-9a-f]{64}))", config)
if match is None:
    raise SystemExit("invalid saved guest config digest")
print("sha256:" + (match.group(1) or match.group(2)))
')"
  for node in $nodes; do
    docker image save --platform "$platform" "$SANDBOX_IMAGE" \
      | docker exec -i "$node" ctr --namespace k8s.io images import \
        --local --snapshotter devmapper --label io.cri-containerd.pinned=pinned -
    actual_status="$(docker exec "$node" crictl \
      --runtime-endpoint unix:///run/containerd/containerd.sock \
      --image-endpoint unix:///run/containerd/containerd.sock \
      inspecti -o go-template --template '{{.status.id}} {{.status.pinned}}' \
      "docker.io/$SANDBOX_IMAGE")"
    if [[ "$actual_status" != "$expected_id true" ]]; then
      echo "guest image identity or retention mismatch on $node" >&2
      echo "expected $expected_id true; got $actual_status" >&2
      exit 1
    fi
  done
}

"$SCRIPT_DIR/k8s-up.sh" --cluster-name "$CLUSTER_NAME" --check-runtime

if [[ "$CHECK" -eq 1 ]]; then
  docker image inspect "$BACKEND_IMAGE" "$SANDBOX_IMAGE" --format '{{.RepoTags}} {{.Id}}'
  kubectl --context "$EXPECTED_CTX" --namespace onyx-sandboxes get podtemplate sandbox-pod \
    -o 'jsonpath={.template.metadata.labels.onyx\.app/sandbox-protocol}{"\n"}{range .template.spec.initContainers[*]}{.name}{" "}{.image}{" "}{.imagePullPolicy}{"\n"}{end}{range .template.spec.containers[*]}{.name}{" "}{.image}{" "}{.imagePullPolicy}{"\n"}{end}'
  echo "Image presence is not source freshness or Firecracker acceptance."
  exit 0
fi

require_empty_sandboxes

if [[ "$PREPARE" -eq 1 ]]; then
  existing_template="$(kubectl --context "$EXPECTED_CTX" --namespace onyx-sandboxes get podtemplate sandbox-pod --ignore-not-found -o name)"
else
  template_file="$(mktemp -t onyx-sandbox-template.XXXXXX)"
  trap 'rm -f "$template_file"' EXIT
  helm template onyx "$SCRIPT_DIR/../charts/onyx" --namespace "$NAMESPACE" \
    --kube-version 1.33.1 --values "$SCRIPT_DIR/values-localdev.yaml" \
    --set auth.opensearch.existingSecret=onyx-opensearch \
    --show-only templates/sandbox-podtemplate.yaml > "$template_file"
fi

if ! command -v uv >/dev/null 2>&1 || [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  echo "Image refresh requires uv and a synced development .venv. Run uv sync --frozen first." >&2
  exit 1
fi

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  docker build -t "$BACKEND_IMAGE" "$REPO_ROOT/backend"
  if [[ "$SKIP_SANDBOX_IMAGE" -eq 0 ]]; then
    docker build -t "$SANDBOX_IMAGE" "$REPO_ROOT/backend/onyx/server/features/build/sandbox/image"
  fi
fi
docker image inspect "$BACKEND_IMAGE" "$SANDBOX_IMAGE" >/dev/null

if [[ "$PREPARE" -eq 1 ]]; then
  if [[ -z "$existing_template" ]]; then
    kind load docker-image "$BACKEND_IMAGE" --name "$CLUSTER_NAME"
    load_guest_image
  fi
  exit 0
fi

require_empty_sandboxes
kind load docker-image "$BACKEND_IMAGE" --name "$CLUSTER_NAME"
pods="$(kubectl_dev get pods -l app.kubernetes.io/instance=onyx \
  -o 'jsonpath={range .items[*]}{.metadata.name}{"\t"}{range .spec.containers[*]}{.image}{" "}{end}{"\n"}{end}')"
old_backend_pods=()
while IFS=$'\t' read -r pod images; do
  for image in $images; do
    case "$image" in
      onyxdotapp/onyx-backend[:@]*|docker.io/onyxdotapp/onyx-backend[:@]*)
        old_backend_pods+=("pod/$pod")
        break
        ;;
    esac
  done
done <<< "$pods"
deployments="$(kubectl_dev get deployments -l app.kubernetes.io/instance=onyx \
  -o 'jsonpath={range .items[*]}{.metadata.name}{"\t"}{range .spec.template.spec.containers[*]}containers/{.name}{"="}{.image}{" "}{end}{range .spec.template.spec.initContainers[*]}initContainers/{.name}{"="}{.image}{" "}{end}{"\n"}{end}')"
backend_deployments=()
while IFS=$'\t' read -r deployment containers; do
  matched=0
  for container in $containers; do
    case "${container#*=}" in
      onyxdotapp/onyx-backend[:@]*|docker.io/onyxdotapp/onyx-backend[:@]*)
        container_ref="${container%%=*}"
        kubectl_dev patch deployment "$deployment" --type=strategic \
          -p "{\"spec\":{\"template\":{\"spec\":{\"${container_ref%%/*}\":[{\"name\":\"${container_ref#*/}\",\"image\":\"$BACKEND_IMAGE\",\"imagePullPolicy\":\"IfNotPresent\"}]}}}}"
        matched=1
        ;;
    esac
  done
  if [[ "$matched" -eq 1 ]]; then
    backend_deployments+=("deployment/$deployment")
  fi
done <<< "$deployments"
if [[ "${#backend_deployments[@]}" -eq 0 ]]; then
  echo "no Onyx backend deployments found; run make craft-up first" >&2
  exit 1
fi
kubectl_dev rollout restart "${backend_deployments[@]}"
for deployment in "${backend_deployments[@]}"; do
  kubectl_dev rollout status "$deployment" --timeout=300s
done
if [[ "${#old_backend_pods[@]}" -gt 0 ]]; then
  kubectl_dev wait --for=delete "${old_backend_pods[@]}" --timeout=300s
fi

# Old provisioners must stop before the protocol and both guest images change.
require_empty_sandboxes
load_guest_image
kubectl --context "$EXPECTED_CTX" apply -f "$template_file"
require_empty_sandboxes
echo "Backend rollouts completed. The Helm guest template is updated."

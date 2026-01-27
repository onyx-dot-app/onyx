#!/bin/bash
# Run Kubernetes sandbox integration tests
#
# This script:
# 1. Builds the onyx-backend Docker image
# 2. Loads it into the kind cluster
# 3. Deletes/recreates the test pod
# 4. Waits for the pod to be ready
# 5. Runs the pytest command inside the pod
#
# Usage:
#   ./run-test.sh [test_name]
#
# Examples:
#   ./run-test.sh                                    # Run all tests
#   ./run-test.sh test_kubernetes_sandbox_provision  # Run specific test

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../../../../.." && pwd)"
NAMESPACE="onyx-sandboxes"
POD_NAME="sandbox-test"
IMAGE_NAME="onyxdotapp/onyx-backend:latest"
TEST_FILE="onyx/server/features/build/sandbox/kubernetes/test_kubernetes_sandbox.py"
ENV_FILE="$PROJECT_ROOT/.vscode/.env"

ORIGINAL_TEST_FILE="$PROJECT_ROOT/backend/tests/external_dependency_unit/craft/test_kubernetes_sandbox.py"
cp "$ORIGINAL_TEST_FILE" "$PROJECT_ROOT/backend/$TEST_FILE"

# Optional: specific test to run
TEST_NAME="${1:-}"

# Build env var arguments from .vscode/.env file for passing to the container
ENV_VARS=()
if [ -f "$ENV_FILE" ]; then
    echo "=== Loading environment variables from .vscode/.env ==="
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        # Skip lines without =
        [[ "$line" != *"="* ]] && continue
        # Add to env vars array
        ENV_VARS+=("$line")
    done < "$ENV_FILE"
    echo "Loaded ${#ENV_VARS[@]} environment variables"
else
    echo "Warning: .vscode/.env not found, running without additional env vars"
fi

echo "=== Building onyx-backend Docker image ==="
cd "$PROJECT_ROOT/backend"
docker build -t "$IMAGE_NAME" -f Dockerfile .

rm "$PROJECT_ROOT/backend/$TEST_FILE"

echo "=== Loading image into kind cluster ==="
kind load docker-image "$IMAGE_NAME" --name onyx 2>/dev/null || \
    kind load docker-image "$IMAGE_NAME" 2>/dev/null || \
    echo "Warning: Could not load into kind. If using minikube, run: minikube image load $IMAGE_NAME"

echo "=== Deleting existing test pod (if any) ==="
kubectl delete pod "$POD_NAME" -n "$NAMESPACE" --ignore-not-found=true

echo "=== Creating test pod ==="
kubectl apply -f "$SCRIPT_DIR/test-job.yaml"

echo "=== Waiting for pod to be ready ==="
kubectl wait --for=condition=Ready pod/"$POD_NAME" -n "$NAMESPACE" --timeout=120s

echo "=== Running tests ==="
if [ -n "$TEST_NAME" ]; then
    kubectl exec -it "$POD_NAME" -n "$NAMESPACE" -- \
        env "${ENV_VARS[@]}" pytest "$TEST_FILE::$TEST_NAME" -v -s
else
    kubectl exec -it "$POD_NAME" -n "$NAMESPACE" -- \
        env "${ENV_VARS[@]}" pytest "$TEST_FILE" -v -s
fi

echo "=== Tests complete ==="

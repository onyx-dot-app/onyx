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
TEST_FILE="onyx/server/features/build/sandbox/kubernetes/test_kubernetes_sandbox_provision.py"

# Optional: specific test to run
TEST_NAME="${1:-}"

echo "=== Building onyx-backend Docker image ==="
cd "$PROJECT_ROOT/backend"
docker build -t "$IMAGE_NAME" -f Dockerfile .

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
        pytest "$TEST_FILE::$TEST_NAME" -v -s
else
    kubectl exec -it "$POD_NAME" -n "$NAMESPACE" -- \
        pytest "$TEST_FILE" -v -s
fi

echo "=== Tests complete ==="

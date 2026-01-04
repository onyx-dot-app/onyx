#!/bin/bash

# We get OPENSEARCH_ADMIN_PASSWORD from the repo .env file.
source "$(dirname "$0")/../../.vscode/.env"

OPENSEARCH_CONTAINER_NAME="onyx-opensearch"
OPENSEARCH_IMAGE="opensearchproject/opensearch:3.2.0"
# First check the env for OPENSEARCH_REST_API_PORT, else hardcode to 9200.
OPENSEARCH_REST_API_PORT=${OPENSEARCH_REST_API_PORT:-9200}
OPENSEARCH_PERFORMANCE_ANALYZER_PORT=9600

function stop_and_remove_opensearch_container() {
  echo "Stopping and removing the existing OpenSearch container..."
  docker stop "$OPENSEARCH_CONTAINER_NAME" 2>/dev/null || true
  docker rm "$OPENSEARCH_CONTAINER_NAME" 2>/dev/null || true
}

# Set OPENSEARCH_ADMIN_PASSWORD=<some password> in your .env file.
if [ -z "$OPENSEARCH_ADMIN_PASSWORD" ]; then
  echo "Error: OPENSEARCH_ADMIN_PASSWORD environment variable is not set." >&2
  echo "Please set OPENSEARCH_ADMIN_PASSWORD=<some password> in your .env file." >&2
  exit 1
fi

# Stop and remove the existing container.
stop_and_remove_opensearch_container

# Start the OpenSearch container.
echo "Starting OpenSearch container..."
docker run --detach --name "$OPENSEARCH_CONTAINER_NAME" --publish "$OPENSEARCH_REST_API_PORT:9200" --publish "$OPENSEARCH_PERFORMANCE_ANALYZER_PORT:9600" -e "discovery.type=single-node" -e "OPENSEARCH_INITIAL_ADMIN_PASSWORD=$OPENSEARCH_ADMIN_PASSWORD" "$OPENSEARCH_IMAGE"

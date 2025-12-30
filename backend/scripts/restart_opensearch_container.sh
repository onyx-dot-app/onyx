#!/bin/bash
set -e

OPENSEARCH_CONTAINER_NAME="onyx-opensearch"

function stop_and_remove_opensearch_container() {
  echo "Stopping and removing the existing OpenSearch container..."
  docker stop $OPENSEARCH_CONTAINER_NAME 2>/dev/null || true
  docker rm $OPENSEARCH_CONTAINER_NAME 2>/dev/null || true
}

# Trap errors and output a message, then cleanup.
trap 'echo "Error occurred on line $LINENO. Exiting script." >&2; stop_and_remove_opensearch_container' ERR

# Stop and remove the existing container.
stop_and_remove_opensearch_container

# Start the OpenSearch container.
echo "Starting OpenSearch container..."
docker run --detach --name $OPENSEARCH_CONTAINER_NAME --publish 9200:9200 --publish 9600:9600 -e "discovery.type=single-node" -e "OPENSEARCH_INITIAL_ADMIN_PASSWORD=D@nswer_1ndex" opensearchproject/opensearch:3.2.0

#!/bin/bash

# We get OPENSEARCH_ADMIN_PASSWORD from the repo .env file.
source "$(dirname "$0")/../../.vscode/.env"

cd "$(dirname "$0")/../../deployment/docker_compose"

# Stop existing container.
echo "Stopping existing OpenSearch container..."
docker compose -f docker-compose.opensearch.yml down opensearch 2>/dev/null || true

# Start OpenSearch.
echo "Starting OpenSearch container..."
docker compose -f docker-compose.opensearch.yml up -d opensearch

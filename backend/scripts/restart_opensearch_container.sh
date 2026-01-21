#!/bin/bash

# We get OPENSEARCH_ADMIN_PASSWORD from the repo .env file.
source "$(dirname "$0")/../../.vscode/.env"

cd "$(dirname "$0")/../../deployment/docker_compose"

# Start OpenSearch.
echo "Forcefully starting fresh OpenSearch container..."
docker compose -f docker-compose.opensearch.yml up --force-recreate -d opensearch

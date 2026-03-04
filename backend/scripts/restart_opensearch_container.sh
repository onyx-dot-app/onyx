#!/bin/bash

# We get OPENSEARCH_ADMIN_PASSWORD from the repo .env file.
source "$(dirname "$0")/../../.vscode/.env"

cd "$(dirname "$0")/../../deployment/docker_compose"

# Start OpenSearch (uses opensearch-enabled profile from main compose).
echo "Forcefully starting fresh OpenSearch container..."
COMPOSE_PROFILES=opensearch-enabled docker compose -f docker-compose.yml -f docker-compose.dev.yml up --force-recreate -d opensearch

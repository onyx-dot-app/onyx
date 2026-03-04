#!/bin/bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
COMPOSE_FILE="$SCRIPT_DIR/../../deployment/docker_compose/docker-compose.yml"
COMPOSE_DEV_FILE="$SCRIPT_DIR/../../deployment/docker_compose/docker-compose.dev.yml"

stop_and_remove_containers() {
  docker stop onyx_postgres onyx_vespa onyx_redis onyx_minio onyx_code_interpreter 2>/dev/null || true
  docker rm onyx_postgres onyx_vespa onyx_redis onyx_minio onyx_code_interpreter 2>/dev/null || true
  docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_FILE" --profile opensearch-enabled stop opensearch 2>/dev/null || true
  docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_FILE" --profile opensearch-enabled rm -f opensearch 2>/dev/null || true
}

cleanup() {
  echo "Error occurred. Cleaning up..."
  stop_and_remove_containers
}

# Trap errors and output a message, then cleanup
trap 'echo "Error occurred on line $LINENO. Exiting script." >&2; cleanup' ERR

# Usage of the script with optional volume arguments
# ./restart_containers.sh [vespa_volume] [postgres_volume] [redis_volume]
# [minio_volume] [--keep-opensearch-data]

KEEP_OPENSEARCH_DATA=false
POSITIONAL_ARGS=()
for arg in "$@"; do
    if [[ "$arg" == "--keep-opensearch-data" ]]; then
        KEEP_OPENSEARCH_DATA=true
    else
        POSITIONAL_ARGS+=("$arg")
    fi
done

VESPA_VOLUME=${POSITIONAL_ARGS[0]:-""}
POSTGRES_VOLUME=${POSITIONAL_ARGS[1]:-""}
REDIS_VOLUME=${POSITIONAL_ARGS[2]:-""}
MINIO_VOLUME=${POSITIONAL_ARGS[3]:-""}

# Stop and remove the existing containers
echo "Stopping and removing existing containers..."
stop_and_remove_containers

# Start the PostgreSQL container with optional volume
echo "Starting PostgreSQL container..."
if [[ -n "$POSTGRES_VOLUME" ]]; then
    docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d -v $POSTGRES_VOLUME:/var/lib/postgresql/data postgres -c max_connections=250
else
    docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d postgres -c max_connections=250
fi

# Start the Vespa container with optional volume
echo "Starting Vespa container..."
if [[ -n "$VESPA_VOLUME" ]]; then
    docker run --detach --name onyx_vespa --hostname vespa-container --publish 8081:8081 --publish 19071:19071 -v $VESPA_VOLUME:/opt/vespa/var vespaengine/vespa:8
else
    docker run --detach --name onyx_vespa --hostname vespa-container --publish 8081:8081 --publish 19071:19071 vespaengine/vespa:8
fi

# If OPENSEARCH_ADMIN_PASSWORD is not already set, try loading it from
# .vscode/.env so existing dev setups that stored it there aren't silently
# broken.
VSCODE_ENV="$SCRIPT_DIR/../../.vscode/.env"
if [[ -z "${OPENSEARCH_ADMIN_PASSWORD:-}" && -f "$VSCODE_ENV" ]]; then
    # shellcheck source=/dev/null
    source "$VSCODE_ENV"
fi

# Start the OpenSearch container using the same service from docker-compose that
# our users use, setting OPENSEARCH_INITIAL_ADMIN_PASSWORD from the env's
# OPENSEARCH_ADMIN_PASSWORD if it exists, else defaulting to StrongPassword123!.
# Pass --keep-opensearch-data to preserve the opensearch-data volume across
# restarts, else the volume is deleted so the container starts fresh.
if [[ "$KEEP_OPENSEARCH_DATA" == "false" ]]; then
    echo "Deleting opensearch-data volume..."
    docker volume rm onyx_opensearch-data 2>/dev/null || true
fi
echo "Starting OpenSearch container..."
docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_FILE" --profile opensearch-enabled up --force-recreate -d opensearch

# Start the Redis container with optional volume
echo "Starting Redis container..."
if [[ -n "$REDIS_VOLUME" ]]; then
    docker run --detach --name onyx_redis --publish 6379:6379 -v $REDIS_VOLUME:/data redis
else
    docker run --detach --name onyx_redis --publish 6379:6379 redis
fi

# Start the MinIO container with optional volume
echo "Starting MinIO container..."
if [[ -n "$MINIO_VOLUME" ]]; then
    docker run --detach --name onyx_minio --publish 9004:9000 --publish 9005:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin -v $MINIO_VOLUME:/data minio/minio server /data --console-address ":9001"
else
    docker run --detach --name onyx_minio --publish 9004:9000 --publish 9005:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin minio/minio server /data --console-address ":9001"
fi

# Start the Code Interpreter container
echo "Starting Code Interpreter container..."
docker run --detach --name onyx_code_interpreter --publish 8000:8000 --user root -v /var/run/docker.sock:/var/run/docker.sock onyxdotapp/code-interpreter:latest bash ./entrypoint.sh code-interpreter-api

# Ensure alembic runs in the correct directory (backend/)
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"

# Give Postgres a second to start
sleep 1

# Alembic should be configured in the virtualenv for this repo
if [[ -f "../.venv/bin/activate" ]]; then
    source ../.venv/bin/activate
else
    echo "Warning: Python virtual environment not found at .venv/bin/activate; alembic may not work."
fi

# Run Alembic upgrade
echo "Running Alembic migration..."
alembic upgrade head

# Run the following instead of the above if using MT cloud
# alembic -n schema_private upgrade head

echo "Containers restarted and migration completed."

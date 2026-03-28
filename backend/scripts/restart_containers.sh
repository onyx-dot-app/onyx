#!/bin/bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
COMPOSE_FILE="$SCRIPT_DIR/../../deployment/docker_compose/docker-compose.yml"
COMPOSE_DEV_FILE="$SCRIPT_DIR/../../deployment/docker_compose/docker-compose.dev.yml"
PROJECT_NAME="onyx-stack"

stop_and_remove_containers() {
  docker stop onyx_postgres onyx_vespa onyx_redis onyx_minio onyx_code_interpreter 2>/dev/null || true
  docker rm onyx_postgres onyx_vespa onyx_redis onyx_minio onyx_code_interpreter 2>/dev/null || true
  # Only stop OpenSearch if it was started
  if [[ "${START_OPENSEARCH:-false}" == "true" ]]; then
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_FILE" --profile opensearch-enabled stop opensearch 2>/dev/null || true
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_FILE" --profile opensearch-enabled rm -f opensearch 2>/dev/null || true
  fi
}

CLEANUP_ON_EXIT=true

cleanup() {
  if [[ "$CLEANUP_ON_EXIT" == "true" ]]; then
    echo "Error occurred. Cleaning up..."
    stop_and_remove_containers
  fi
}

# Trap errors and exits to ensure cleanup runs on failure
trap 'echo "Error occurred on line $LINENO. Exiting script." >&2; cleanup' ERR
trap cleanup EXIT

# Usage of the script with optional volume arguments
# ./restart_containers.sh [vespa_volume] [postgres_volume] [redis_volume]
# [minio_volume] [--keep-opensearch-data]
#
# Environment variables:
#   START_OPENSEARCH=true        Enable OpenSearch (default: false)
#   OPENSEARCH_ADMIN_PASSWORD    OpenSearch admin password (default: StrongPassword123!)

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
    docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d \
        --health-cmd "pg_isready -U postgres" \
        --health-interval 5s \
        --health-timeout 3s \
        --health-retries 5 \
        --health-start-period 10s \
        -v "$POSTGRES_VOLUME:/var/lib/postgresql/data" postgres -c max_connections=250
else
    docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d \
        --health-cmd "pg_isready -U postgres" \
        --health-interval 5s \
        --health-timeout 3s \
        --health-retries 5 \
        --health-start-period 10s \
        postgres -c max_connections=250
fi

# Wait for Postgres to be healthy
echo "Waiting for PostgreSQL to be healthy..."
MAX_WAIT=60
ELAPSED=0
until [ "$(docker inspect --format='{{.State.Health.Status}}' onyx_postgres 2>/dev/null)" = "healthy" ]; do
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo "ERROR: PostgreSQL failed to become healthy within ${MAX_WAIT} seconds"
        exit 1
    fi
    echo "  PostgreSQL is not ready yet, waiting... (${ELAPSED}s elapsed)"
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done
echo "PostgreSQL is healthy and ready!"

# Start the Vespa container with optional volume
echo "Starting Vespa container..."
if [[ -n "$VESPA_VOLUME" ]]; then
    docker run --detach --name onyx_vespa --hostname vespa-container \
        --publish 8081:8081 --publish 19071:19071 \
        --health-cmd "curl -sf http://localhost:19071/state/v1/health || exit 1" \
        --health-interval 10s \
        --health-timeout 5s \
        --health-retries 5 \
        --health-start-period 30s \
        -v "$VESPA_VOLUME:/opt/vespa/var" vespaengine/vespa:8
else
    docker run --detach --name onyx_vespa --hostname vespa-container \
        --publish 8081:8081 --publish 19071:19071 \
        --health-cmd "curl -sf http://localhost:19071/state/v1/health || exit 1" \
        --health-interval 10s \
        --health-timeout 5s \
        --health-retries 5 \
        --health-start-period 30s \
        vespaengine/vespa:8
fi

# Wait for Vespa to be healthy (can take longer than other services)
echo "Waiting for Vespa to be healthy (this may take up to 90 seconds)..."
MAX_WAIT=90
ELAPSED=0
until [ "$(docker inspect --format='{{.State.Health.Status}}' onyx_vespa 2>/dev/null)" = "healthy" ]; do
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo "ERROR: Vespa failed to become healthy within ${MAX_WAIT} seconds"
        exit 1
    fi
    echo "  Vespa is not ready yet, waiting... (${ELAPSED}s elapsed)"
    sleep 3
    ELAPSED=$((ELAPSED + 3))
done
echo "Vespa is healthy and ready!"

# If OPENSEARCH_ADMIN_PASSWORD is not already set, try loading it from
# .vscode/.env so existing dev setups that stored it there aren't silently
# broken.
VSCODE_ENV="$SCRIPT_DIR/../../.vscode/.env"
if [[ -z "${OPENSEARCH_ADMIN_PASSWORD:-}" && -f "$VSCODE_ENV" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$VSCODE_ENV"
    set +a
fi

# Start the OpenSearch container only if explicitly enabled
# Set START_OPENSEARCH=true to enable OpenSearch (disabled by default)
if [[ "${START_OPENSEARCH:-false}" == "true" ]]; then
    echo "OpenSearch enabled - starting container..."
    # Delete opensearch-data volume unless --keep-opensearch-data is specified
    if [[ "$KEEP_OPENSEARCH_DATA" == "false" ]]; then
        echo "Deleting opensearch-data volume..."
        docker volume rm "${PROJECT_NAME}_opensearch-data" 2>/dev/null || true
    fi
    echo "Starting OpenSearch container..."
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_FILE" --profile opensearch-enabled up --force-recreate -d opensearch
else
    echo "OpenSearch disabled (set START_OPENSEARCH=true to enable)"
fi

# Wait for OpenSearch to be ready (only if it was started)
if [[ "${START_OPENSEARCH:-false}" == "true" ]]; then
    echo "Waiting for OpenSearch to be ready (this may take up to 90 seconds)..."
    MAX_WAIT=90
    ELAPSED=0

    # Dynamically find the OpenSearch container name (with retry loop)
    echo "Looking for OpenSearch container..."
    OPENSEARCH_CONTAINER=""
    FIND_WAIT=0
    while [[ -z "$OPENSEARCH_CONTAINER" && $FIND_WAIT -lt 10 ]]; do
        # Use docker compose ps to get the exact container name for this project's opensearch service
        CONTAINER_ID=$(docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_FILE" --profile opensearch-enabled ps -q opensearch 2>/dev/null)
        if [[ -n "$CONTAINER_ID" ]]; then
            OPENSEARCH_CONTAINER=$(docker inspect --format='{{.Name}}' "$CONTAINER_ID" 2>/dev/null | sed 's/^\///')
        fi
        if [[ -z "$OPENSEARCH_CONTAINER" ]]; then
            echo "  Container not found yet, retrying... (${FIND_WAIT}s elapsed)"
            sleep 1
            FIND_WAIT=$((FIND_WAIT + 1))
        else
            # Found the container, now check if it's running
            CONTAINER_STATE=$(docker inspect --format='{{.State.Status}}' "$OPENSEARCH_CONTAINER" 2>/dev/null)
            if [[ "$CONTAINER_STATE" != "running" ]]; then
                echo "WARNING: OpenSearch container found but not running (state: $CONTAINER_STATE)"
                if [[ "$CONTAINER_STATE" == "exited" ]]; then
                    echo "Container logs:"
                    docker logs "$OPENSEARCH_CONTAINER" --tail 50
                    exit 1
                fi
                # If it's in a transitional state (creating, restarting), keep waiting
                OPENSEARCH_CONTAINER=""
                sleep 1
                FIND_WAIT=$((FIND_WAIT + 1))
            fi
        fi
    done

    if [[ -z "$OPENSEARCH_CONTAINER" ]]; then
        echo "ERROR: OpenSearch container not found or failed to start after ${FIND_WAIT} seconds"
        echo "Compose status for project '$PROJECT_NAME':"
        docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_FILE" --profile opensearch-enabled ps
        exit 1
    fi
    echo "Found running OpenSearch container: $OPENSEARCH_CONTAINER"

    until docker exec "$OPENSEARCH_CONTAINER" curl -s -k -u "admin:${OPENSEARCH_ADMIN_PASSWORD:-StrongPassword123!}" https://localhost:9200/_cluster/health 2>&1 | grep -qE '"status":"(green|yellow)"'; do
        if [ $ELAPSED -ge $MAX_WAIT ]; then
            echo "ERROR: OpenSearch failed to become ready within ${MAX_WAIT} seconds"
            echo "Last health check output:"
            docker exec "$OPENSEARCH_CONTAINER" curl -s -k -u "admin:${OPENSEARCH_ADMIN_PASSWORD:-StrongPassword123!}" https://localhost:9200/_cluster/health 2>&1 || echo "Failed to connect"
            exit 1
        fi
        # Check if container is still running
        if ! docker ps --filter "name=$OPENSEARCH_CONTAINER" --format "{{.Names}}" | grep -q "$OPENSEARCH_CONTAINER"; then
            echo "ERROR: OpenSearch container stopped unexpectedly"
            docker logs "$OPENSEARCH_CONTAINER" --tail 50
            exit 1
        fi
        echo "  OpenSearch is not ready yet, waiting... (${ELAPSED}s elapsed)"
        sleep 3
        ELAPSED=$((ELAPSED + 3))
    done
    echo "OpenSearch is ready!"
fi

# Start the Redis container with optional volume
echo "Starting Redis container..."
if [[ -n "$REDIS_VOLUME" ]]; then
    docker run --detach --name onyx_redis --publish 6379:6379 \
        --health-cmd "redis-cli ping || exit 1" \
        --health-interval 5s \
        --health-timeout 3s \
        --health-retries 3 \
        --health-start-period 10s \
        -v "$REDIS_VOLUME:/data" redis
else
    docker run --detach --name onyx_redis --publish 6379:6379 \
        --health-cmd "redis-cli ping || exit 1" \
        --health-interval 5s \
        --health-timeout 3s \
        --health-retries 3 \
        --health-start-period 10s \
        redis
fi

# Wait for Redis to be healthy
echo "Waiting for Redis to be healthy..."
MAX_WAIT=30
ELAPSED=0
until [ "$(docker inspect --format='{{.State.Health.Status}}' onyx_redis 2>/dev/null)" = "healthy" ]; do
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo "ERROR: Redis failed to become healthy within ${MAX_WAIT} seconds"
        exit 1
    fi
    echo "  Redis is not ready yet, waiting... (${ELAPSED}s elapsed)"
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done
echo "Redis is healthy and ready!"

# Start the MinIO container with optional volume
echo "Starting MinIO container..."
if [[ -n "$MINIO_VOLUME" ]]; then
    docker run --detach --name onyx_minio --publish 9004:9000 --publish 9005:9001 \
        --health-cmd "mc ready local || exit 1" \
        --health-interval 5s \
        --health-timeout 3s \
        --health-retries 3 \
        --health-start-period 10s \
        -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
        -v "$MINIO_VOLUME:/data" minio/minio server /data --console-address ":9001"
else
    docker run --detach --name onyx_minio --publish 9004:9000 --publish 9005:9001 \
        --health-cmd "mc ready local || exit 1" \
        --health-interval 5s \
        --health-timeout 3s \
        --health-retries 3 \
        --health-start-period 10s \
        -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
        minio/minio server /data --console-address ":9001"
fi

# Wait for MinIO to be healthy
echo "Waiting for MinIO to be healthy..."
MAX_WAIT=30
ELAPSED=0
until [ "$(docker inspect --format='{{.State.Health.Status}}' onyx_minio 2>/dev/null)" = "healthy" ]; do
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo "ERROR: MinIO failed to become healthy within ${MAX_WAIT} seconds"
        exit 1
    fi
    echo "  MinIO is not ready yet, waiting... (${ELAPSED}s elapsed)"
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done
echo "MinIO is healthy and ready!"

# Start the Code Interpreter container
echo "Starting Code Interpreter container..."
docker run --detach --name onyx_code_interpreter --publish 8000:8000 --user root -v /var/run/docker.sock:/var/run/docker.sock onyxdotapp/code-interpreter:latest bash ./entrypoint.sh code-interpreter-api

# Wait for Code Interpreter to be ready
echo "Waiting for Code Interpreter to be ready..."
MAX_WAIT=30
ELAPSED=0
until curl -sf http://localhost:8000/health 2>/dev/null >/dev/null; do
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo "WARNING: Code Interpreter failed to become ready within ${MAX_WAIT} seconds (continuing anyway)"
        break
    fi
    echo "  Code Interpreter is not ready yet, waiting... (${ELAPSED}s elapsed)"
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done
echo "Code Interpreter is ready!"

# Ensure alembic runs in the correct directory (backend/)
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"

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

echo "All containers are healthy and migration completed successfully!"

# Disable cleanup on successful exit
CLEANUP_ON_EXIT=false

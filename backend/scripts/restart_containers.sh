#!/bin/bash
set -e

cleanup() {
  echo "Error occurred. Cleaning up..."
  docker stop onyx_postgres onyx_vespa onyx_redis onyx_minio 2>/dev/null || true
}

# Trap errors and output a message, then cleanup
trap 'echo "Error occurred on line $LINENO. Exiting script." >&2; cleanup' ERR

# Usage of the script with optional volume arguments
# ./restart_containers.sh [vespa_volume] [postgres_volume] [redis_volume] [minio_volume]

VESPA_VOLUME=${1:-""}  # Default is empty if not provided
POSTGRES_VOLUME=${2:-""}  # Default is empty if not provided
REDIS_VOLUME=${3:-""}  # Default is empty if not provided
MINIO_VOLUME=${4:-""}  # Default is empty if not provided

# Stop the existing containers
echo "Stopping existing containers..."
docker stop onyx_postgres onyx_vespa onyx_redis onyx_minio 2>/dev/null || true

# Start or create PostgreSQL container
echo "Starting PostgreSQL container..."
if docker ps -a --format '{{.Names}}' | grep -q "^onyx_postgres$"; then
    echo "PostgreSQL container exists, starting it..."
    docker start onyx_postgres
else
    echo "Creating new PostgreSQL container..."
    if [[ -n "$POSTGRES_VOLUME" ]]; then
        docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d -v $POSTGRES_VOLUME:/var/lib/postgresql/data postgres -c max_connections=250
    else
        docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d postgres -c max_connections=250
    fi
fi

# Start or create Vespa container
echo "Starting Vespa container..."
if docker ps -a --format '{{.Names}}' | grep -q "^onyx_vespa$"; then
    echo "Vespa container exists, starting it..."
    docker start onyx_vespa
else
    echo "Creating new Vespa container..."
    if [[ -n "$VESPA_VOLUME" ]]; then
        docker run --detach --name onyx_vespa --hostname vespa-container --publish 8081:8081 --publish 19071:19071 -v $VESPA_VOLUME:/opt/vespa/var vespaengine/vespa:8
    else
        docker run --detach --name onyx_vespa --hostname vespa-container --publish 8081:8081 --publish 19071:19071 vespaengine/vespa:8
    fi
fi

# Start or create Redis container
echo "Starting Redis container..."
if docker ps -a --format '{{.Names}}' | grep -q "^onyx_redis$"; then
    echo "Redis container exists, starting it..."
    docker start onyx_redis
else
    echo "Creating new Redis container..."
    if [[ -n "$REDIS_VOLUME" ]]; then
        docker run --detach --name onyx_redis --publish 6379:6379 -v $REDIS_VOLUME:/data redis
    else
        docker run --detach --name onyx_redis --publish 6379:6379 redis
    fi
fi

# Start or create MinIO container
echo "Starting MinIO container..."
if docker ps -a --format '{{.Names}}' | grep -q "^onyx_minio$"; then
    echo "MinIO container exists, starting it..."
    docker start onyx_minio
else
    echo "Creating new MinIO container..."
    if [[ -n "$MINIO_VOLUME" ]]; then
        docker run --detach --name onyx_minio --publish 9004:9000 --publish 9005:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin -e MINIO_DEFAULT_BUCKETS=onyx-file-store-bucket -v $MINIO_VOLUME:/data minio/minio:latest server /data --console-address ":9001"
    else
        docker run --detach --name onyx_minio --publish 9004:9000 --publish 9005:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin -e MINIO_DEFAULT_BUCKETS=onyx-file-store-bucket minio/minio:latest server /data --console-address ":9001"
    fi
fi

# Ensure alembic runs in the correct directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"

# Give Postgres a second to start
sleep 1

# Run Alembic upgrade
echo "Running Alembic migration..."
alembic upgrade head

# Run the following instead of the above if using MT cloud
# alembic -n schema_private upgrade head

echo "Containers restarted and migration completed."

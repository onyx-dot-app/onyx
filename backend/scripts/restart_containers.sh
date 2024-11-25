#!/bin/bash

# Usage of the script with optional volume arguments
# ./restart_containers.sh [vespa_volume] [postgres_volume] [redis_volume]

VESPA_VOLUME=${1:-""}  # Default is empty if not provided
POSTGRES_VOLUME=${2:-""}  # Default is empty if not provided
REDIS_VOLUME=${3:-""}  # Default is empty if not provided

# Stop and remove the existing containers
echo "Stopping and removing existing containers..."
docker stop danswer_postgres danswer_vespa danswer_redis
docker rm danswer_postgres danswer_vespa danswer_redis

# Start the PostgreSQL container with optional volume
echo "Starting PostgreSQL container..."
if [[ -n "$POSTGRES_VOLUME" ]]; then
    docker run -p 5432:5432 --name danswer_postgres -e POSTGRES_PASSWORD=password -d -v $POSTGRES_VOLUME:/var/lib/postgresql/data postgres -c max_connections=250
else
    docker run -p 5432:5432 --name danswer_postgres -e POSTGRES_PASSWORD=password -d postgres -c max_connections=250
fi

# Start the Vespa container with optional volume
echo "Starting Vespa container..."
if [[ -n "$VESPA_VOLUME" ]]; then
    docker run --detach --name danswer_vespa --hostname vespa-container --publish 8081:8081 --publish 19071:19071 -v $VESPA_VOLUME:/opt/vespa/var vespaengine/vespa:8
else
    docker run --detach --name danswer_vespa --hostname vespa-container --publish 8081:8081 --publish 19071:19071 vespaengine/vespa:8
fi

# Start the Redis container with optional volume
echo "Starting Redis container..."
if [[ -n "$REDIS_VOLUME" ]]; then
    docker run --detach --name danswer_redis --publish 6379:6379 -v $REDIS_VOLUME:/data redis
else
    docker run --detach --name danswer_redis --publish 6379:6379 redis
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

echo "Containers restarted and migration completed."

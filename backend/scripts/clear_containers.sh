#!/bin/bash
set -e

# Usage of the script
# ./clear_containers.sh

# Stop and remove the existing containers
echo "Stopping and removing existing containers..."
docker stop onyx_postgres onyx_vespa onyx_redis onyx_minio 2>/dev/null || true
docker rm onyx_postgres onyx_vespa onyx_redis onyx_minio 2>/dev/null || true

echo "Containers stopped and removed."
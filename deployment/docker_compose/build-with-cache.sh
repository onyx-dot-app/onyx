#!/bin/bash
# Script to build Docker images with improved caching

set -e

# Default values
COMPOSE_FILE="docker-compose.dev.yml"
PULL_IMAGES=true
BUILD_IMAGES=true
PUSH_IMAGES=false
IMAGE_TAG="latest"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --file|-f)
      COMPOSE_FILE="$2"
      shift 2
      ;;
    --no-pull)
      PULL_IMAGES=false
      shift
      ;;
    --no-build)
      BUILD_IMAGES=false
      shift
      ;;
    --push)
      PUSH_IMAGES=true
      shift
      ;;
    --tag|-t)
      IMAGE_TAG="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Ensure we're in the right directory
cd "$(dirname "$0")"

# Pull latest images if requested
if [ "$PULL_IMAGES" = true ]; then
  echo "Pulling latest images..."
  docker compose -f "$COMPOSE_FILE" pull
fi

# Build images with improved caching if requested
if [ "$BUILD_IMAGES" = true ]; then
  echo "Building images with improved caching..."
  
  # Enable BuildKit for better caching
  export DOCKER_BUILDKIT=1
  export COMPOSE_DOCKER_CLI_BUILD=1
  
  # Build with cache-from and inline cache
  docker compose -f "$COMPOSE_FILE" build \
    --build-arg BUILDKIT_INLINE_CACHE=1 \
    --build-arg IMAGE_TAG="$IMAGE_TAG"
fi

# Push images if requested
if [ "$PUSH_IMAGES" = true ]; then
  echo "Pushing images..."
  docker compose -f "$COMPOSE_FILE" push
fi

echo "Done!" 
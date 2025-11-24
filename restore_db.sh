#!/bin/bash
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
BACKUP_FILE="backup.agent.sql"
CONTAINER_NAME="onyx-relational_db-1"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-postgres}"

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_PATH="${SCRIPT_DIR}/${BACKUP_FILE}"

# Backup exists?
if [ ! -f "$BACKUP_PATH" ]; then
    echo -e "${RED}Error: Backup file '$BACKUP_PATH' not found.${NC}"
    exit 1
fi

# Docker running?
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running.${NC}"
    exit 1
fi

# Container exists?
if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}Error: Container '${CONTAINER_NAME}' not found.${NC}"
    exit 1
fi

# Container running?
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${YELLOW}Container '${CONTAINER_NAME}' is not running. Starting it...${NC}"
    docker start "$CONTAINER_NAME" >/dev/null
    sleep 2
fi

# Summary
echo -e "${YELLOW}=======================================${NC}"
echo -e "${YELLOW}     PostgreSQL Restore Script         ${NC}"
echo -e "${YELLOW}=======================================${NC}"
echo "Backup file: $BACKUP_PATH"
echo "Container:   $CONTAINER_NAME"
echo "Database:    $POSTGRES_DB"
echo "User:        $POSTGRES_USER"
echo ""
echo -e "${RED}WARNING: This will overwrite existing data in '${POSTGRES_DB}'.${NC}"
echo ""

# Confirmation
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Restore cancelled.${NC}"
    exit 0
fi

echo -e "${GREEN}Starting restore...${NC}"

# Copy backup to container
echo "Copying backup file to container..."
docker cp "$BACKUP_PATH" "${CONTAINER_NAME}:/tmp/${BACKUP_FILE}"

# Restore using TCP, avoids socket issues
echo "Executing backup inside PostgreSQL..."
docker exec "$CONTAINER_NAME" \
    psql -h localhost -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "/tmp/${BACKUP_FILE}"

# Clean up
echo "Cleaning temporary file..."
docker exec "$CONTAINER_NAME" rm -f "/tmp/${BACKUP_FILE}"

echo -e "${GREEN}✓ Restore completed successfully!${NC}"

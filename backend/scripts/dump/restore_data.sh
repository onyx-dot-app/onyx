#!/bin/bash
# =============================================================================
# Onyx Data Restore Script
# =============================================================================
# This script restores PostgreSQL, Vespa, and MinIO data from a backup.
#
# The script auto-detects the backup mode based on files present:
#   - *_volume.tar.gz files -> volume restore
#   - postgres_dump.backup / vespa_documents.jsonl -> api restore
#
# Usage:
#   ./restore_data.sh [OPTIONS]
#
# Options:
#   --input <dir>           Backup directory (required, or use 'latest')
#   --project <name>        Docker Compose project name (default: onyx)
#   --postgres-only         Only restore PostgreSQL
#   --vespa-only            Only restore Vespa
#   --minio-only            Only restore MinIO
#   --no-minio              Skip MinIO restore
#   --force                 Skip confirmation prompts
#   --help                  Show this help message
#
# Examples:
#   ./restore_data.sh --input ./onyx_backup/latest
#   ./restore_data.sh --input ./onyx_backup/20240115_120000 --force
#   ./restore_data.sh --input ./onyx_backup/latest --postgres-only
#
# WARNING: This will overwrite existing data in the target instance!
# =============================================================================

set -e

# Default configuration
INPUT_DIR=""
PROJECT_NAME="onyx"
RESTORE_POSTGRES=true
RESTORE_VESPA=true
RESTORE_MINIO=true
FORCE=false

# PostgreSQL defaults
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-password}"
POSTGRES_DB="${POSTGRES_DB:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

# Vespa defaults
VESPA_HOST="${VESPA_HOST:-localhost}"
VESPA_PORT="${VESPA_PORT:-8081}"
VESPA_INDEX="${VESPA_INDEX:-danswer_index}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_help() {
    head -36 "$0" | tail -33
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --input)
            INPUT_DIR="$2"
            shift 2
            ;;
        --project)
            PROJECT_NAME="$2"
            shift 2
            ;;
        --postgres-only)
            RESTORE_POSTGRES=true
            RESTORE_VESPA=false
            RESTORE_MINIO=false
            shift
            ;;
        --vespa-only)
            RESTORE_POSTGRES=false
            RESTORE_VESPA=true
            RESTORE_MINIO=false
            shift
            ;;
        --minio-only)
            RESTORE_POSTGRES=false
            RESTORE_VESPA=false
            RESTORE_MINIO=true
            shift
            ;;
        --no-minio)
            RESTORE_MINIO=false
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --help)
            show_help
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate input directory
if [[ -z "$INPUT_DIR" ]]; then
    log_error "Input directory is required. Use --input <dir>"
    exit 1
fi

# Resolve symlinks (e.g., 'latest')
INPUT_DIR=$(cd "$INPUT_DIR" && pwd)

if [[ ! -d "$INPUT_DIR" ]]; then
    log_error "Input directory not found: $INPUT_DIR"
    exit 1
fi

# Load metadata if available
METADATA_FILE="${INPUT_DIR}/metadata.json"
if [[ -f "$METADATA_FILE" ]]; then
    log_info "Loading backup metadata..."
    BACKUP_MODE=$(jq -r '.mode // "unknown"' "$METADATA_FILE")
    BACKUP_TIMESTAMP=$(jq -r '.timestamp // "unknown"' "$METADATA_FILE")
    log_info "  Backup timestamp: $BACKUP_TIMESTAMP"
    log_info "  Backup mode: $BACKUP_MODE"
fi

# Auto-detect backup mode based on files present
detect_backup_mode() {
    if [[ -f "${INPUT_DIR}/postgres_volume.tar.gz" ]] || [[ -f "${INPUT_DIR}/vespa_volume.tar.gz" ]]; then
        echo "volume"
    elif [[ -f "${INPUT_DIR}/postgres_dump.backup" ]] || [[ -f "${INPUT_DIR}/vespa_documents.jsonl" ]]; then
        echo "api"
    else
        echo "unknown"
    fi
}

DETECTED_MODE=$(detect_backup_mode)
log_info "Detected backup mode: $DETECTED_MODE"

# Get container names
POSTGRES_CONTAINER="${PROJECT_NAME}-relational_db-1"
VESPA_CONTAINER="${PROJECT_NAME}-index-1"
MINIO_CONTAINER="${PROJECT_NAME}-minio-1"

# Confirmation prompt
if [[ "$FORCE" != true ]]; then
    echo ""
    log_warning "==================================="
    log_warning "WARNING: This will overwrite existing data!"
    log_warning "==================================="
    echo ""
    echo "Restore configuration:"
    echo "  Input directory: $INPUT_DIR"
    echo "  Project name: $PROJECT_NAME"
    echo "  Restore PostgreSQL: $RESTORE_POSTGRES"
    echo "  Restore Vespa: $RESTORE_VESPA"
    echo "  Restore MinIO: $RESTORE_MINIO"
    echo ""
    read -p "Are you sure you want to continue? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        log_info "Restore cancelled."
        exit 0
    fi
fi

# =============================================================================
# Volume-based restore functions
# =============================================================================

restore_postgres_volume() {
    log_info "Restoring PostgreSQL from volume backup..."

    local volume_name="${PROJECT_NAME}_db_volume"
    local backup_file="${INPUT_DIR}/postgres_volume.tar.gz"

    if [[ ! -f "$backup_file" ]]; then
        log_error "PostgreSQL volume backup not found: $backup_file"
        return 1
    fi

    # Stop PostgreSQL container if running
    if docker ps --format '{{.Names}}' | grep -q "^${POSTGRES_CONTAINER}$"; then
        log_info "Stopping PostgreSQL container..."
        docker stop "$POSTGRES_CONTAINER" || true
    fi

    # Remove existing volume and create new one
    log_info "Recreating PostgreSQL volume..."
    docker volume rm "$volume_name" 2>/dev/null || true
    docker volume create "$volume_name"

    # Restore volume from tar
    docker run --rm \
        -v "${volume_name}:/target" \
        -v "${INPUT_DIR}:/backup:ro" \
        alpine sh -c "cd /target && tar xzf /backup/postgres_volume.tar.gz"

    log_success "PostgreSQL volume restored"
}

restore_vespa_volume() {
    log_info "Restoring Vespa from volume backup..."

    local volume_name="${PROJECT_NAME}_vespa_volume"
    local backup_file="${INPUT_DIR}/vespa_volume.tar.gz"

    if [[ ! -f "$backup_file" ]]; then
        log_error "Vespa volume backup not found: $backup_file"
        return 1
    fi

    # Stop Vespa container if running
    if docker ps --format '{{.Names}}' | grep -q "^${VESPA_CONTAINER}$"; then
        log_info "Stopping Vespa container..."
        docker stop "$VESPA_CONTAINER" || true
    fi

    # Remove existing volume and create new one
    log_info "Recreating Vespa volume..."
    docker volume rm "$volume_name" 2>/dev/null || true
    docker volume create "$volume_name"

    # Restore volume from tar
    docker run --rm \
        -v "${volume_name}:/target" \
        -v "${INPUT_DIR}:/backup:ro" \
        alpine sh -c "cd /target && tar xzf /backup/vespa_volume.tar.gz"

    log_success "Vespa volume restored"
}

restore_minio_volume() {
    log_info "Restoring MinIO from volume backup..."

    local volume_name="${PROJECT_NAME}_minio_data"
    local backup_file="${INPUT_DIR}/minio_volume.tar.gz"

    if [[ ! -f "$backup_file" ]]; then
        log_error "MinIO volume backup not found: $backup_file"
        return 1
    fi

    # Stop MinIO container if running
    if docker ps --format '{{.Names}}' | grep -q "^${MINIO_CONTAINER}$"; then
        log_info "Stopping MinIO container..."
        docker stop "$MINIO_CONTAINER" || true
    fi

    # Remove existing volume and create new one
    log_info "Recreating MinIO volume..."
    docker volume rm "$volume_name" 2>/dev/null || true
    docker volume create "$volume_name"

    # Restore volume from tar
    docker run --rm \
        -v "${volume_name}:/target" \
        -v "${INPUT_DIR}:/backup:ro" \
        alpine sh -c "cd /target && tar xzf /backup/minio_volume.tar.gz"

    log_success "MinIO volume restored"
}

# =============================================================================
# API-based restore functions
# =============================================================================

restore_postgres_api() {
    log_info "Restoring PostgreSQL from pg_dump backup..."

    local backup_file="${INPUT_DIR}/postgres_dump.backup"

    if [[ ! -f "$backup_file" ]]; then
        log_error "PostgreSQL dump not found: $backup_file"
        return 1
    fi

    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${POSTGRES_CONTAINER}$"; then
        log_error "PostgreSQL container '$POSTGRES_CONTAINER' is not running"
        log_info "Please start the containers first: docker compose up -d relational_db"
        return 1
    fi

    # Copy backup file to container
    log_info "Copying backup file to container..."
    docker cp "$backup_file" "${POSTGRES_CONTAINER}:/tmp/postgres_dump.backup"

    # Drop and recreate database (optional, pg_restore --clean should handle this)
    log_info "Restoring database..."

    # Use pg_restore with --clean to drop objects before recreating
    docker exec "$POSTGRES_CONTAINER" \
        pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --clean --if-exists --no-owner --no-privileges \
        /tmp/postgres_dump.backup 2>&1 || {
            # pg_restore may return non-zero even on success due to warnings
            log_warning "pg_restore completed with warnings (this is often normal)"
        }

    # Cleanup
    docker exec "$POSTGRES_CONTAINER" rm -f /tmp/postgres_dump.backup

    log_success "PostgreSQL restored"
}

restore_vespa_api() {
    log_info "Restoring Vespa from JSONL backup..."

    local backup_file="${INPUT_DIR}/vespa_documents.jsonl"

    if [[ ! -f "$backup_file" ]]; then
        log_error "Vespa backup not found: $backup_file"
        return 1
    fi

    local endpoint="http://${VESPA_HOST}:${VESPA_PORT}/document/v1/default/${VESPA_INDEX}/docid"
    local total_docs=0
    local failed_docs=0

    # Check if Vespa is accessible
    if ! curl -s -o /dev/null -w "%{http_code}" "http://${VESPA_HOST}:${VESPA_PORT}/state/v1/health" | grep -q "200"; then
        log_error "Cannot connect to Vespa at ${VESPA_HOST}:${VESPA_PORT}"
        log_info "Please ensure Vespa is running and accessible"
        return 1
    fi

    # Wait for Vespa to be fully ready
    log_info "Waiting for Vespa to be fully ready..."
    local max_wait=60
    local waited=0
    while ! curl -s "http://${VESPA_HOST}:${VESPA_PORT}/state/v1/health" | grep -q '"status":{"code":"up"}'; do
        if [[ $waited -ge $max_wait ]]; then
            log_error "Vespa did not become ready within ${max_wait} seconds"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done

    # Restore documents
    log_info "Restoring documents..."
    while IFS= read -r line; do
        if [[ -z "$line" ]]; then
            continue
        fi

        # Extract document ID
        local doc_id
        doc_id=$(echo "$line" | jq -r '.update' | sed 's/.*:://')

        # Post document
        local response
        response=$(curl -s -w "\n%{http_code}" -X POST \
            -H "Content-Type: application/json" \
            -d "$line" \
            "${endpoint}/${doc_id}")

        local http_code
        http_code=$(echo "$response" | tail -1)

        total_docs=$((total_docs + 1))

        if [[ "$http_code" != "200" ]]; then
            failed_docs=$((failed_docs + 1))
            if [[ $failed_docs -le 5 ]]; then
                log_warning "Failed to restore document $doc_id (HTTP $http_code)"
            fi
        fi

        # Progress update
        if [[ $((total_docs % 100)) -eq 0 ]]; then
            log_info "  Restored $total_docs documents..."
        fi
    done < "$backup_file"

    if [[ $failed_docs -gt 0 ]]; then
        log_warning "Vespa restored with $failed_docs failures out of $total_docs documents"
    else
        log_success "Vespa restored ($total_docs documents)"
    fi
}

restore_minio_api() {
    log_info "Restoring MinIO data..."

    local backup_file="${INPUT_DIR}/minio_data.tar.gz"

    if [[ ! -f "$backup_file" ]]; then
        log_warning "MinIO backup not found: $backup_file"
        # Try volume backup as fallback
        if [[ -f "${INPUT_DIR}/minio_volume.tar.gz" ]]; then
            log_info "Found volume backup, using that instead"
            restore_minio_volume
            return
        fi
        return 1
    fi

    # Extract to temp directory
    local temp_dir
    temp_dir=$(mktemp -d)
    tar xzf "$backup_file" -C "$temp_dir"

    # Check if mc (MinIO client) is available
    if command -v mc &>/dev/null; then
        # Configure mc alias for local minio
        mc alias set onyx-restore http://localhost:9004 minioadmin minioadmin 2>/dev/null || true

        # Mirror data to minio
        mc mirror "$temp_dir/" onyx-restore/ 2>/dev/null || {
            log_warning "mc mirror failed"
        }
    else
        # Fallback: copy to container
        if docker ps --format '{{.Names}}' | grep -q "^${MINIO_CONTAINER}$"; then
            docker cp "$temp_dir/." "${MINIO_CONTAINER}:/data/"
        else
            log_error "MinIO container not running and mc not available"
            rm -rf "$temp_dir"
            return 1
        fi
    fi

    rm -rf "$temp_dir"
    log_success "MinIO restored"
}

# =============================================================================
# Main restore logic
# =============================================================================

log_info "Starting Onyx data restore..."
log_info "Input directory: $INPUT_DIR"
log_info "Project name: $PROJECT_NAME"

# Run restores based on detected mode
if [[ "$DETECTED_MODE" == "volume" ]]; then
    log_info "Using volume-based restore"
    log_warning "Services will be stopped during restore"

    if $RESTORE_POSTGRES; then
        restore_postgres_volume || log_warning "PostgreSQL restore failed"
    fi

    if $RESTORE_VESPA; then
        restore_vespa_volume || log_warning "Vespa restore failed"
    fi

    if $RESTORE_MINIO; then
        restore_minio_volume || log_warning "MinIO restore failed"
    fi

    log_info ""
    log_info "Volume restore complete. Please restart the services:"
    log_info "  cd deployment/docker_compose && docker compose up -d"

elif [[ "$DETECTED_MODE" == "api" ]]; then
    log_info "Using API-based restore"
    log_info "Services must be running for API restore"

    if $RESTORE_POSTGRES; then
        restore_postgres_api || log_warning "PostgreSQL restore failed"
    fi

    if $RESTORE_VESPA; then
        restore_vespa_api || log_warning "Vespa restore failed"
    fi

    if $RESTORE_MINIO; then
        restore_minio_api || log_warning "MinIO restore failed"
    fi

else
    log_error "Could not detect backup mode. Ensure backup files exist in $INPUT_DIR"
    exit 1
fi

log_success "==================================="
log_success "Restore completed!"
log_success "==================================="

# Post-restore recommendations
echo ""
log_info "Post-restore steps:"
log_info "  1. Restart all services if using volume restore"
log_info "  2. Run database migrations: docker compose exec api_server alembic upgrade head"
log_info "  3. Verify data integrity in the application"

#!/bin/bash
# =============================================================================
# Onyx Data Dump Script
# =============================================================================
# This script creates a backup of PostgreSQL, Vespa, and MinIO data.
#
# Two modes available:
#   - volume: Exports Docker volumes directly (faster, complete backup)
#   - api: Uses pg_dump and Vespa API (more portable)
#
# Usage:
#   ./dump_data.sh [OPTIONS]
#
# Options:
#   --mode <volume|api>     Backup mode (default: volume)
#   --output <dir>          Output directory (default: ./onyx_backup)
#   --project <name>        Docker Compose project name (default: onyx)
#   --postgres-only         Only backup PostgreSQL
#   --vespa-only            Only backup Vespa
#   --minio-only            Only backup MinIO
#   --no-minio              Skip MinIO backup
#   --help                  Show this help message
#
# Examples:
#   ./dump_data.sh                              # Full volume backup
#   ./dump_data.sh --mode api                   # API-based backup
#   ./dump_data.sh --output /tmp/backup         # Custom output directory
#   ./dump_data.sh --postgres-only --mode api   # Only PostgreSQL via pg_dump
# =============================================================================

set -e

# Default configuration
MODE="volume"
OUTPUT_DIR="./onyx_backup"
PROJECT_NAME="onyx"
BACKUP_POSTGRES=true
BACKUP_VESPA=true
BACKUP_MINIO=true

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
    head -35 "$0" | tail -32
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --project)
            PROJECT_NAME="$2"
            shift 2
            ;;
        --postgres-only)
            BACKUP_POSTGRES=true
            BACKUP_VESPA=false
            BACKUP_MINIO=false
            shift
            ;;
        --vespa-only)
            BACKUP_POSTGRES=false
            BACKUP_VESPA=true
            BACKUP_MINIO=false
            shift
            ;;
        --minio-only)
            BACKUP_POSTGRES=false
            BACKUP_VESPA=false
            BACKUP_MINIO=true
            shift
            ;;
        --no-minio)
            BACKUP_MINIO=false
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

# Validate mode
if [[ "$MODE" != "volume" && "$MODE" != "api" ]]; then
    log_error "Invalid mode: $MODE. Use 'volume' or 'api'"
    exit 1
fi

# Create output directory with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${OUTPUT_DIR}/${TIMESTAMP}"
mkdir -p "$BACKUP_DIR"

log_info "Starting Onyx data backup..."
log_info "Mode: $MODE"
log_info "Output directory: $BACKUP_DIR"
log_info "Project name: $PROJECT_NAME"

# Get container names
POSTGRES_CONTAINER="${PROJECT_NAME}-relational_db-1"
VESPA_CONTAINER="${PROJECT_NAME}-index-1"
MINIO_CONTAINER="${PROJECT_NAME}-minio-1"

# =============================================================================
# Volume-based backup functions
# =============================================================================

backup_postgres_volume() {
    log_info "Backing up PostgreSQL volume..."

    local volume_name="${PROJECT_NAME}_db_volume"

    # Check if volume exists
    if ! docker volume inspect "$volume_name" &>/dev/null; then
        log_error "PostgreSQL volume '$volume_name' not found"
        return 1
    fi

    # Export volume to tar
    docker run --rm \
        -v "${volume_name}:/source:ro" \
        -v "${BACKUP_DIR}:/backup" \
        alpine tar czf /backup/postgres_volume.tar.gz -C /source .

    log_success "PostgreSQL volume backed up to postgres_volume.tar.gz"
}

backup_vespa_volume() {
    log_info "Backing up Vespa volume..."

    local volume_name="${PROJECT_NAME}_vespa_volume"

    # Check if volume exists
    if ! docker volume inspect "$volume_name" &>/dev/null; then
        log_error "Vespa volume '$volume_name' not found"
        return 1
    fi

    # Export volume to tar
    docker run --rm \
        -v "${volume_name}:/source:ro" \
        -v "${BACKUP_DIR}:/backup" \
        alpine tar czf /backup/vespa_volume.tar.gz -C /source .

    log_success "Vespa volume backed up to vespa_volume.tar.gz"
}

backup_minio_volume() {
    log_info "Backing up MinIO volume..."

    local volume_name="${PROJECT_NAME}_minio_data"

    # Check if volume exists
    if ! docker volume inspect "$volume_name" &>/dev/null; then
        log_error "MinIO volume '$volume_name' not found"
        return 1
    fi

    # Export volume to tar
    docker run --rm \
        -v "${volume_name}:/source:ro" \
        -v "${BACKUP_DIR}:/backup" \
        alpine tar czf /backup/minio_volume.tar.gz -C /source .

    log_success "MinIO volume backed up to minio_volume.tar.gz"
}

# =============================================================================
# API-based backup functions
# =============================================================================

backup_postgres_api() {
    log_info "Backing up PostgreSQL via pg_dump..."

    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${POSTGRES_CONTAINER}$"; then
        log_error "PostgreSQL container '$POSTGRES_CONTAINER' is not running"
        return 1
    fi

    # Create dump using pg_dump inside container
    docker exec "$POSTGRES_CONTAINER" \
        pg_dump -U "$POSTGRES_USER" -F c -b -v "$POSTGRES_DB" \
        > "${BACKUP_DIR}/postgres_dump.backup"

    log_success "PostgreSQL backed up to postgres_dump.backup"
}

backup_vespa_api() {
    log_info "Backing up Vespa via API..."

    local endpoint="http://${VESPA_HOST}:${VESPA_PORT}/document/v1/default/${VESPA_INDEX}/docid"
    local output_file="${BACKUP_DIR}/vespa_documents.jsonl"
    local continuation=""
    local total_docs=0

    # Check if Vespa is accessible
    if ! curl -s -o /dev/null -w "%{http_code}" "$endpoint" | grep -q "200\|404"; then
        # Try via container if localhost doesn't work
        if docker ps --format '{{.Names}}' | grep -q "^${VESPA_CONTAINER}$"; then
            log_warning "Vespa not accessible on $VESPA_HOST:$VESPA_PORT, trying via container..."
            endpoint="http://localhost:8081/document/v1/default/${VESPA_INDEX}/docid"
        else
            log_error "Cannot connect to Vespa at $endpoint"
            return 1
        fi
    fi

    # Clear output file
    > "$output_file"

    # Fetch documents with pagination
    while true; do
        local url="$endpoint"
        if [[ -n "$continuation" ]]; then
            url="${endpoint}?continuation=${continuation}"
        fi

        local response
        response=$(curl -s "$url")

        # Extract continuation token
        continuation=$(echo "$response" | jq -r '.continuation // empty')

        # Extract and save documents
        local docs
        docs=$(echo "$response" | jq -c '.documents[]? | {update: .id, create: true, fields: .fields}')

        if [[ -n "$docs" ]]; then
            echo "$docs" >> "$output_file"
            local count
            count=$(echo "$docs" | wc -l)
            total_docs=$((total_docs + count))
            log_info "  Fetched $total_docs documents so far..."
        fi

        # Check if we're done
        if [[ -z "$continuation" ]]; then
            break
        fi
    done

    log_success "Vespa backed up to vespa_documents.jsonl ($total_docs documents)"
}

backup_minio_api() {
    log_info "Backing up MinIO data..."

    local minio_dir="${BACKUP_DIR}/minio_data"
    mkdir -p "$minio_dir"

    # Check if mc (MinIO client) is available
    if command -v mc &>/dev/null; then
        # Configure mc alias for local minio
        mc alias set onyx-backup http://localhost:9004 minioadmin minioadmin 2>/dev/null || true

        # Mirror all buckets
        mc mirror onyx-backup/ "$minio_dir/" 2>/dev/null || {
            log_warning "mc mirror failed, falling back to volume backup"
            backup_minio_volume
            return
        }
    else
        # Fallback: copy from container
        if docker ps --format '{{.Names}}' | grep -q "^${MINIO_CONTAINER}$"; then
            docker cp "${MINIO_CONTAINER}:/data/." "$minio_dir/"
        else
            log_warning "MinIO container not running and mc not available, using volume backup"
            backup_minio_volume
            return
        fi
    fi

    # Compress the data
    tar czf "${BACKUP_DIR}/minio_data.tar.gz" -C "$minio_dir" .
    rm -rf "$minio_dir"

    log_success "MinIO backed up to minio_data.tar.gz"
}

# =============================================================================
# Main backup logic
# =============================================================================

# Save metadata
cat > "${BACKUP_DIR}/metadata.json" << EOF
{
    "timestamp": "$TIMESTAMP",
    "mode": "$MODE",
    "project_name": "$PROJECT_NAME",
    "postgres_db": "$POSTGRES_DB",
    "vespa_index": "$VESPA_INDEX",
    "components": {
        "postgres": $BACKUP_POSTGRES,
        "vespa": $BACKUP_VESPA,
        "minio": $BACKUP_MINIO
    }
}
EOF

# Run backups based on mode
if [[ "$MODE" == "volume" ]]; then
    log_info "Using volume-based backup (services should be stopped for consistency)"

    if $BACKUP_POSTGRES; then
        backup_postgres_volume || log_warning "PostgreSQL backup failed"
    fi

    if $BACKUP_VESPA; then
        backup_vespa_volume || log_warning "Vespa backup failed"
    fi

    if $BACKUP_MINIO; then
        backup_minio_volume || log_warning "MinIO backup failed"
    fi
else
    log_info "Using API-based backup (services must be running)"

    if $BACKUP_POSTGRES; then
        backup_postgres_api || log_warning "PostgreSQL backup failed"
    fi

    if $BACKUP_VESPA; then
        backup_vespa_api || log_warning "Vespa backup failed"
    fi

    if $BACKUP_MINIO; then
        backup_minio_api || log_warning "MinIO backup failed"
    fi
fi

# Calculate total size
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)

log_success "==================================="
log_success "Backup completed!"
log_success "Location: $BACKUP_DIR"
log_success "Total size: $TOTAL_SIZE"
log_success "==================================="

# Create a symlink to latest backup
ln -sfn "$TIMESTAMP" "${OUTPUT_DIR}/latest"
log_info "Symlink created: ${OUTPUT_DIR}/latest -> $TIMESTAMP"

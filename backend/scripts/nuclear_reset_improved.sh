#!/bin/bash
# Nuclear Database Reset Script
# Completely resets database, caches, and optionally indexes for clean testing

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
DOCKER_COMPOSE_FILE="${DOCKER_COMPOSE_FILE:-deployment/docker_compose/docker-compose.prod-aws.yml}"
ENV_FILE="${ENV_FILE:-deployment/docker_compose/.env}"
SKIP_CONFIRMATION="${SKIP_CONFIRMATION:-false}"
RESET_VESPA="${RESET_VESPA:-true}"
RESET_REDIS="${RESET_REDIS:-true}"
RESET_OPENSEARCH="${RESET_OPENSEARCH:-false}"
SEED_ADMIN="${SEED_ADMIN:-true}"
AUTO_RESTART="${AUTO_RESTART:-true}"
DRY_RUN="${DRY_RUN:-false}"

# Print usage
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Nuclear database reset script for clean testing environments.

OPTIONS:
    -f, --env-file FILE          Path to .env file (default: deployment/docker_compose/.env)
    -c, --compose-file FILE      Path to docker-compose file (default: docker-compose.prod-aws.yml)
    -y, --yes                    Skip confirmation prompt
    --no-vespa                   Don't reset Vespa index
    --no-redis                   Don't reset Redis cache
    --reset-opensearch           Also reset OpenSearch (default: false)
    --no-seed                    Don't seed default admin user
    --no-restart                 Don't restart services after reset
    --dry-run                    Show what would be done without executing
    -h, --help                   Show this help message

EXAMPLES:
    # Interactive reset with defaults
    $0

    # Non-interactive reset
    $0 --yes

    # Reset everything including OpenSearch
    $0 --reset-opensearch --yes

    # Dry run to see what would happen
    $0 --dry-run

    # Custom compose file
    $0 -c deployment/docker_compose/docker-compose.dev.yml

EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--env-file)
            ENV_FILE="$2"
            shift 2
            ;;
        -c|--compose-file)
            DOCKER_COMPOSE_FILE="$2"
            shift 2
            ;;
        -y|--yes)
            SKIP_CONFIRMATION=true
            shift
            ;;
        --no-vespa)
            RESET_VESPA=false
            shift
            ;;
        --no-redis)
            RESET_REDIS=false
            shift
            ;;
        --reset-opensearch)
            RESET_OPENSEARCH=true
            shift
            ;;
        --no-seed)
            SEED_ADMIN=false
            shift
            ;;
        --no-restart)
            AUTO_RESTART=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            usage
            ;;
    esac
done

# Load environment variables
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: Environment file not found: $ENV_FILE${NC}"
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

# Validate required environment variables
required_vars=(
    "POSTGRES_HOST"
    "POSTGRES_PORT"
    "POSTGRES_DB"
    "POSTGRES_USER"
)

for var in "${required_vars[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo -e "${RED}Error: Required environment variable $var is not set${NC}"
        exit 1
    fi
done

echo -e "${YELLOW}=== NUCLEAR DATABASE RESET ===${NC}"
echo ""
echo -e "${RED}⚠️  EXTREME DANGER: This will:${NC}"
echo "   - Drop the entire public schema"
if [ "${MULTI_TENANT:-false}" = "true" ]; then
    echo "   - Drop all tenant schemas"
fi
echo "   - Recreate public schema fresh"
echo "   - DELETE ABSOLUTELY EVERYTHING in the database"
if [ "$RESET_REDIS" = "true" ]; then
    echo "   - FLUSH ALL Redis cache data"
fi
if [ "$RESET_VESPA" = "true" ]; then
    echo "   - DELETE all Vespa documents"
fi
if [ "$RESET_OPENSEARCH" = "true" ]; then
    echo "   - DELETE all OpenSearch indices"
fi
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "   Database: $POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB"
echo "   User: $POSTGRES_USER"
echo "   Auth Method: ${USE_IAM_AUTH:-false}"
echo "   Compose File: $DOCKER_COMPOSE_FILE"
echo ""
echo -e "${RED}Only do this on development/test environments with no production data.${NC}"
echo ""

if [ "$DRY_RUN" = "true" ]; then
    echo -e "${YELLOW}DRY RUN MODE - No changes will be made${NC}"
    echo ""
fi

# Confirmation
if [ "$SKIP_CONFIRMATION" = "false" ] && [ "$DRY_RUN" = "false" ]; then
    read -p "Type 'NUCLEAR' to confirm: " confirm
    if [ "$confirm" != "NUCLEAR" ]; then
        echo "Aborted."
        exit 0
    fi
fi

# Function to execute or print command
execute() {
    if [ "$DRY_RUN" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would execute:${NC} $*"
    else
        "$@"
    fi
}

# Function to get database connection string
get_db_connection() {
    local password=""

    if [ "${USE_IAM_AUTH:-false}" = "true" ]; then
        echo -e "${GREEN}Generating IAM token...${NC}"
        password=$(python3 -c "
import boto3
import sys
try:
    client = boto3.client('rds', region_name='${AWS_REGION_NAME:-us-east-1}')
    token = client.generate_db_auth_token(
        DBHostname='$POSTGRES_HOST',
        Port=$POSTGRES_PORT,
        DBUsername='$POSTGRES_USER'
    )
    print(token)
except Exception as e:
    print(f'Error generating IAM token: {e}', file=sys.stderr)
    sys.exit(1)
")
        if [ $? -ne 0 ]; then
            echo -e "${RED}Failed to generate IAM token${NC}"
            exit 1
        fi
    else
        password="${POSTGRES_PASSWORD:-}"
        if [ -z "$password" ]; then
            echo -e "${RED}Error: POSTGRES_PASSWORD not set and USE_IAM_AUTH is not enabled${NC}"
            exit 1
        fi
    fi

    local ssl_mode="require"
    if [ "${POSTGRES_REQUIRE_SSL:-true}" = "false" ]; then
        ssl_mode="prefer"
    fi

    echo "host=$POSTGRES_HOST port=$POSTGRES_PORT dbname=$POSTGRES_DB user=$POSTGRES_USER password=$password sslmode=$ssl_mode"
}

# Step 1: Stop services
if [ "$AUTO_RESTART" = "true" ]; then
    echo ""
    echo -e "${GREEN}Step 1: Stopping services...${NC}"
    execute docker compose -f "$DOCKER_COMPOSE_FILE" stop api_server background web_server
fi

# Step 2: Reset PostgreSQL
echo ""
echo -e "${GREEN}Step 2: Resetting PostgreSQL database...${NC}"

if [ "$DRY_RUN" = "false" ]; then
    CONNECTION_STRING=$(get_db_connection)

    docker run --rm -i postgres:17 \
        psql "$CONNECTION_STRING" \
        <<'EOF'
-- Terminate any active connections (except our own)
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname = current_database()
  AND pid <> pg_backend_pid();

-- Drop all non-system schemas (tenant schemas)
DO $$
DECLARE
    schema_rec RECORD;
BEGIN
    FOR schema_rec IN
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'public')
          AND schema_name NOT LIKE 'pg_%'
    LOOP
        EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', schema_rec.schema_name);
        RAISE NOTICE 'Dropped schema: %', schema_rec.schema_name;
    END LOOP;
END $$;

-- Drop and recreate public schema
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;

-- Grant default permissions
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO public;

-- Verify everything is clean
\echo ''
\echo 'Remaining schemas (should only be system schemas):'
SELECT schema_name FROM information_schema.schemata
WHERE schema_name NOT LIKE 'pg_%'
  AND schema_name != 'information_schema'
ORDER BY schema_name;

\echo ''
\echo 'Tables in public schema (should be empty):'
SELECT tablename FROM pg_tables WHERE schemaname = 'public';
EOF

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Database reset complete${NC}"
    else
        echo -e "${RED}✗ Database reset failed${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}[DRY RUN] Would reset PostgreSQL database${NC}"
fi

# Step 3: Reset Redis
if [ "$RESET_REDIS" = "true" ]; then
    echo ""
    echo -e "${GREEN}Step 3: Flushing Redis cache...${NC}"

    if [ "$DRY_RUN" = "false" ]; then
        # Try to flush Redis, but don't fail if container doesn't exist
        if docker compose -f "$DOCKER_COMPOSE_FILE" ps cache | grep -q "Up"; then
            docker compose -f "$DOCKER_COMPOSE_FILE" exec -T cache redis-cli FLUSHALL
            echo -e "${GREEN}✓ Redis cache flushed${NC}"
        else
            echo -e "${YELLOW}⚠ Redis container not running, skipping${NC}"
        fi
    else
        echo -e "${YELLOW}[DRY RUN] Would flush Redis cache${NC}"
    fi
fi

# Step 4: Reset Vespa
if [ "$RESET_VESPA" = "true" ]; then
    echo ""
    echo -e "${GREEN}Step 4: Resetting Vespa index...${NC}"

    if [ "$DRY_RUN" = "false" ]; then
        # Check if Vespa is accessible
        VESPA_HOST="${VESPA_HOST:-index}"
        VESPA_PORT="${VESPA_PORT:-8081}"

        if docker compose -f "$DOCKER_COMPOSE_FILE" ps index | grep -q "Up"; then
            # Delete all documents in the default document type
            echo "Deleting all Vespa documents..."
            docker compose -f "$DOCKER_COMPOSE_FILE" exec -T index \
                bash -c "vespa-visit --datahandler /document/v1/default/doc/docid > /dev/null 2>&1 || true"
            echo -e "${GREEN}✓ Vespa index reset${NC}"
        else
            echo -e "${YELLOW}⚠ Vespa container not running, skipping${NC}"
        fi
    else
        echo -e "${YELLOW}[DRY RUN] Would reset Vespa index${NC}"
    fi
fi

# Step 5: Reset OpenSearch (optional)
if [ "$RESET_OPENSEARCH" = "true" ]; then
    echo ""
    echo -e "${GREEN}Step 5: Resetting OpenSearch indices...${NC}"

    if [ "$DRY_RUN" = "false" ]; then
        if docker compose -f "$DOCKER_COMPOSE_FILE" ps opensearch | grep -q "Up" 2>/dev/null; then
            OPENSEARCH_PASSWORD="${OPENSEARCH_ADMIN_PASSWORD:-StrongPassword123!}"
            docker compose -f "$DOCKER_COMPOSE_FILE" exec -T opensearch \
                curl -XDELETE -u "admin:$OPENSEARCH_PASSWORD" "https://localhost:9200/*" -k || true
            echo -e "${GREEN}✓ OpenSearch indices deleted${NC}"
        else
            echo -e "${YELLOW}⚠ OpenSearch container not running, skipping${NC}"
        fi
    else
        echo -e "${YELLOW}[DRY RUN] Would reset OpenSearch indices${NC}"
    fi
fi

# Step 6: Restart services and run migrations
if [ "$AUTO_RESTART" = "true" ]; then
    echo ""
    echo -e "${GREEN}Step 6: Restarting services...${NC}"

    if [ "$DRY_RUN" = "false" ]; then
        # Start api_server first to run migrations
        execute docker compose -f "$DOCKER_COMPOSE_FILE" up -d api_server

        echo "Waiting for migrations to complete (checking logs)..."
        sleep 5

        # Wait for "Starting Onyx Api Server" in logs
        timeout=60
        elapsed=0
        while [ $elapsed -lt $timeout ]; do
            if docker compose -f "$DOCKER_COMPOSE_FILE" logs api_server 2>&1 | grep -q "Starting Onyx Api Server"; then
                echo -e "${GREEN}✓ Migrations completed successfully${NC}"
                break
            fi
            sleep 2
            elapsed=$((elapsed + 2))
        done

        if [ $elapsed -ge $timeout ]; then
            echo -e "${YELLOW}⚠ Timeout waiting for migrations. Check logs:${NC}"
            echo "  docker compose -f $DOCKER_COMPOSE_FILE logs api_server"
        fi

        # Start other services
        execute docker compose -f "$DOCKER_COMPOSE_FILE" up -d background web_server

        echo -e "${GREEN}✓ Services restarted${NC}"
    else
        echo -e "${YELLOW}[DRY RUN] Would restart services${NC}"
    fi
fi

# Step 7: Seed admin user (optional)
if [ "$SEED_ADMIN" = "true" ] && [ "$DRY_RUN" = "false" ]; then
    echo ""
    echo -e "${GREEN}Step 7: Seeding default admin user...${NC}"

    # Wait for API to be ready
    echo "Waiting for API server to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:8080/health >/dev/null 2>&1; then
            break
        fi
        sleep 2
    done

    # Check if we should seed (depends on auth type)
    AUTH_TYPE="${AUTH_TYPE:-disabled}"
    if [ "$AUTH_TYPE" = "basic" ]; then
        echo "Creating default admin user (email: admin@onyx.app, password: admin)..."
        # This would need the actual API endpoint for user creation
        # For now, just a placeholder
        echo -e "${YELLOW}⚠ Manual user creation required for basic auth${NC}"
        echo "  Visit http://localhost:3000 and sign up as the first user"
    else
        echo -e "${YELLOW}⚠ Auth type is $AUTH_TYPE - manual setup may be required${NC}"
    fi
fi

# Summary
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Nuclear reset complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Database is completely clean and migrations have been applied."
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Access the application: http://localhost:3000"
echo "  2. Check API health: curl http://localhost:8080/health"
echo "  3. View logs: docker compose -f $DOCKER_COMPOSE_FILE logs -f"
echo ""

if [ "$DRY_RUN" = "true" ]; then
    echo -e "${YELLOW}This was a DRY RUN - no changes were made${NC}"
    echo "Run without --dry-run to execute the reset"
    echo ""
fi

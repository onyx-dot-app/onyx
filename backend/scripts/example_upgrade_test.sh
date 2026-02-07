#!/bin/bash
#
# Example script showing how to test multi-tenant upgrades
# with a populated database
#
set -e

echo "========================================"
echo "Multi-Tenant Upgrade Testing Workflow"
echo "========================================"

# Configuration
COMPOSE_FILE="../deployment/docker_compose/docker-compose.multitenant-dev.yml"
NUM_TENANTS=5
SESSIONS_PER_TENANT=50
DOCS_PER_TENANT=100

# Step 1: Start multi-tenant environment
echo ""
echo "Step 1: Starting multi-tenant dev environment..."
docker-compose -f "$COMPOSE_FILE" up -d

echo "Waiting for services to be ready..."
sleep 30

# Wait for API server
echo "Checking API server health..."
until curl -sf http://localhost:8080/health > /dev/null; do
    echo "  Waiting for API server..."
    sleep 5
done
echo "✓ API server is ready"

# Step 2: Seed the database
echo ""
echo "Step 2: Seeding database with $NUM_TENANTS tenants..."
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py \
    --tenants "$NUM_TENANTS" \
    --sessions-per-tenant "$SESSIONS_PER_TENANT" \
    --docs-per-tenant "$DOCS_PER_TENANT"

# Step 3: Take a backup before upgrade
echo ""
echo "Step 3: Taking database backup before upgrade..."
docker exec onyx-relational_db-1 pg_dump -U postgres > /tmp/backup_before_upgrade_$(date +%Y%m%d_%H%M%S).sql
echo "✓ Backup saved"

# Step 4: Record current state
echo ""
echo "Step 4: Recording current database state..."
cat > /tmp/pre_upgrade_state.txt << EOF
Pre-upgrade state recorded at: $(date)
Number of tenants: $NUM_TENANTS
Expected chat sessions: $((NUM_TENANTS * SESSIONS_PER_TENANT))
Expected documents: $((NUM_TENANTS * DOCS_PER_TENANT))
EOF

# Query some stats (customize based on your needs)
docker exec onyx-relational_db-1 psql -U postgres -c "
SELECT
    schemaname as tenant_schema,
    COUNT(*) as table_count
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'public')
GROUP BY schemaname;
" >> /tmp/pre_upgrade_state.txt

echo "✓ State recorded to /tmp/pre_upgrade_state.txt"

# Step 5: Run your upgrade/migration
echo ""
echo "Step 5: Running database migration..."
echo "NOTE: Replace this with your actual upgrade command"
echo ""
# Example:
# docker exec onyx-api_server-1 alembic upgrade head
# OR
# docker-compose -f "$COMPOSE_FILE" run --rm api_server alembic upgrade head

echo "⚠️  MANUAL STEP REQUIRED:"
echo "   Run your upgrade/migration commands here"
echo "   Press Enter when complete..."
read -r

# Step 6: Verify data integrity
echo ""
echo "Step 6: Verifying data integrity..."

# Check that all schemas still exist
echo "Checking tenant schemas..."
docker exec onyx-relational_db-1 psql -U postgres -c "
SELECT
    schemaname as tenant_schema,
    COUNT(*) as table_count
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'public')
GROUP BY schemaname;
"

# Step 7: Manual verification checklist
echo ""
echo "========================================"
echo "Manual Verification Checklist:"
echo "========================================"
echo ""
echo "Please verify the following for each tenant:"
echo ""
echo "1. Login with tenant credentials (see seeding output)"
echo "2. Check that chat history is intact and accessible"
echo "3. Verify documents are searchable"
echo "4. Test that queries return results"
echo "5. Verify no data leakage between tenants"
echo "6. Check that all features work correctly"
echo ""
echo "Tenant credentials can be found in the seeding script output above."
echo ""

# Step 8: Performance testing (optional)
echo ""
echo "Would you like to run performance tests? (y/n)"
read -r response
if [ "$response" = "y" ]; then
    echo "Running query time tests..."
    cd backend/scripts/query_time_check
    PYTHONPATH=../.. python test_query_times.py
fi

echo ""
echo "========================================"
echo "Upgrade Testing Complete!"
echo "========================================"
echo ""
echo "Logs and backups are in /tmp/"
echo "To restore from backup if needed:"
echo "  docker exec -i onyx-relational_db-1 psql -U postgres < /tmp/backup_before_upgrade_*.sql"
echo ""


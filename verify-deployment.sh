#!/bin/bash
set -e

# Onyx Deployment Verification Script
# Checks that all services are healthy and operational

DOMAIN="klugermax.com"
DEPLOY_DIR="/opt/onyx"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_fail() {
    echo -e "${RED}[✗]${NC} $1"
}

log_section() {
    echo ""
    echo -e "${BLUE}=== $1 ===${NC}"
}

cd $DEPLOY_DIR || {
    log_fail "Could not navigate to $DEPLOY_DIR"
    exit 1
}

log_section "Docker Services Status"

# Check if docker is running
if ! sudo docker ps > /dev/null 2>&1; then
    log_fail "Docker is not running"
    exit 1
fi

# Check docker-compose status
services=$(sudo docker-compose ps --format "{{.Service}}")
log_info "Checking services..."

for service in $services; do
    status=$(sudo docker-compose ps $service --format "{{.Status}}")
    if echo "$status" | grep -q "Up"; then
        log_success "$service: $status"
    else
        log_fail "$service: $status"
    fi
done

log_section "Health Checks"

# Check Backend API
log_info "Backend API (port 8080)..."
if curl -s http://localhost:8080/health > /dev/null 2>&1; then
    log_success "Backend API is responding"
else
    log_fail "Backend API is not responding"
fi

# Check Model Server
log_info "Model Server (port 9000)..."
if curl -s http://localhost:9000/health > /dev/null 2>&1; then
    log_success "Model Server is responding"
else
    log_fail "Model Server is not responding"
fi

# Check Frontend
log_info "Frontend (port 3000)..."
if curl -s http://localhost:3000 > /dev/null 2>&1; then
    log_success "Frontend is responding"
else
    log_fail "Frontend is not responding"
fi

# Check PostgreSQL
log_info "PostgreSQL..."
if sudo docker-compose exec -T relational_db pg_isready -U postgres > /dev/null 2>&1; then
    log_success "PostgreSQL is responsive"
else
    log_fail "PostgreSQL is not responsive"
fi

# Check Redis
log_info "Redis..."
if sudo docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; then
    log_success "Redis is responsive"
else
    log_fail "Redis is not responsive"
fi

log_section "DNS & SSL Verification"

log_info "Domain: $DOMAIN"
if nslookup $DOMAIN > /dev/null 2>&1; then
    ip=$(nslookup $DOMAIN | grep -oP '(?<=Address: ).*' | tail -1)
    log_success "DNS resolution: $ip"

    # Check if it resolves to our droplet IP
    if [ -f ".env" ] && grep -q "45.55.68.178" .env; then
        log_info "Expected IP: 45.55.68.178"
        if [ "$ip" = "45.55.68.178" ]; then
            log_success "DNS resolves to correct droplet IP"
        else
            log_fail "DNS resolves to $ip (expected 45.55.68.178)"
        fi
    fi
else
    log_fail "Cannot resolve domain $DOMAIN"
fi

# Check SSL certificate (if HTTPS is available)
log_info "Checking SSL certificate..."
if timeout 5 openssl s_client -connect $DOMAIN:443 </dev/null 2>/dev/null | grep -q "Verify return code: 0"; then
    log_success "SSL certificate is valid"
else
    log_fail "SSL certificate check failed (may still be initializing)"
fi

log_section "Database Migration Status"

# Check if migrations ran
if sudo docker-compose exec -T relational_db psql -U postgres -d onyx -c "SELECT 1 FROM alembic_version LIMIT 1" > /dev/null 2>&1; then
    version=$(sudo docker-compose exec -T relational_db psql -U postgres -d onyx -c "SELECT version_num FROM alembic_version ORDER BY installed_on DESC LIMIT 1" -t | tr -d ' ')
    log_success "Database migrations completed (version: $version)"
else
    log_fail "Database migrations may not have completed"
fi

log_section "Disk Space"

disk_usage=$(df -h $DEPLOY_DIR | awk 'NR==2 {print $5}')
log_info "Disk usage: $disk_usage"

log_section "Summary"

log_info "Deployment verification complete!"
log_info ""
log_info "Access your Onyx instance:"
log_info "  - HTTP:  http://$DOMAIN (redirects to HTTPS)"
log_info "  - HTTPS: https://$DOMAIN"
log_info ""
log_info "View logs:"
log_info "  cd $DEPLOY_DIR && sudo docker-compose logs -f"
log_info ""
log_info "Create admin user (if not already done):"
log_info "  curl -X POST http://localhost:8080/api/admin/create-user \\"
log_info "    -H 'Content-Type: application/json' \\"
log_info "    -d '{\"username\": \"admin\", \"password\": \"your-password\"}'"

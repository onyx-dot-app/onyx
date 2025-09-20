#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Step counter variables
CURRENT_STEP=0
TOTAL_STEPS=10

# Print colored output
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

print_step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo ""
    echo -e "${BLUE}${BOLD}=== $1 - Step ${CURRENT_STEP}/${TOTAL_STEPS} ===${NC}"
    echo ""
}

print_warning() {
    echo -e "${YELLOW}⚠${NC}  $1"
}

# ASCII Art Banner
echo ""
echo -e "${BLUE}${BOLD}"
echo "  ____                    "
echo " / __ \                   "
echo "| |  | |_ __  _   ___  __ "
echo "| |  | | '_ \| | | \ \/ / "
echo "| |__| | | | | |_| |>  <  "
echo " \____/|_| |_|\__, /_/\_\ "
echo "               __/ |      "
echo "              |___/       "
echo -e "${NC}"
echo "Welcome to Onyx Installation Script"
echo "===================================="
echo ""

# GitHub repo base URL - using docker-compose-easy branch
GITHUB_RAW_URL="https://raw.githubusercontent.com/onyx-dot-app/onyx/docker-compose-easy/deployment/docker_compose"

# Check system requirements
print_step "Verifying Docker installation"

# Check Docker
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    echo "Visit: https://docs.docker.com/get-docker/"
    exit 1
fi
DOCKER_VERSION=$(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
print_success "Docker $DOCKER_VERSION is installed"

# Check Docker Compose
if docker compose version &> /dev/null; then
    COMPOSE_VERSION=$(docker compose version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    COMPOSE_CMD="docker compose"
    print_success "Docker Compose $COMPOSE_VERSION is installed (plugin)"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(docker-compose --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    COMPOSE_CMD="docker-compose"
    print_success "Docker Compose $COMPOSE_VERSION is installed (standalone)"
else
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    echo "Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

# Check Docker daemon
if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running. Please start Docker."
    exit 1
fi
print_success "Docker daemon is running"

# Check Docker resources
print_step "Verifying Docker resources"

# Get Docker system info
DOCKER_INFO=$(docker system info 2>/dev/null)

# Try to get memory allocation (method varies by platform)
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS - Docker Desktop
    if command -v jq &> /dev/null && [ -f ~/Library/Group\ Containers/group.com.docker/settings.json ]; then
        MEMORY_MB=$(cat ~/Library/Group\ Containers/group.com.docker/settings.json 2>/dev/null | jq '.memoryMiB // 0' 2>/dev/null || echo "0")
    else
        # Try to get from docker system info
        MEMORY_BYTES=$(docker system info 2>/dev/null | grep -i "total memory" | grep -oE '[0-9]+\.[0-9]+' | head -1)
        if [ -n "$MEMORY_BYTES" ]; then
            # Convert from GiB to MB (multiply by 1024)
            MEMORY_MB=$(echo "$MEMORY_BYTES * 1024" | bc 2>/dev/null | cut -d. -f1)
            if [ -z "$MEMORY_MB" ]; then
                MEMORY_MB="0"
            fi
        else
            MEMORY_MB="0"
        fi
    fi
else
    # Linux - Native Docker
    MEMORY_KB=$(grep MemTotal /proc/meminfo | grep -oE '[0-9]+' || echo "0")
    MEMORY_MB=$((MEMORY_KB / 1024))
fi

# Convert to GB for display
if [ "$MEMORY_MB" -gt 0 ]; then
    MEMORY_GB=$((MEMORY_MB / 1024))
    print_info "Docker memory allocation: ~${MEMORY_GB}GB"
else
    print_warning "Could not determine Docker memory allocation"
    MEMORY_MB=0
fi

# Check disk space (different commands for macOS vs Linux)
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS uses -g for GB
    DISK_AVAILABLE=$(df -g . | awk 'NR==2 {print $4}')
else
    # Linux uses -BG for GB
    DISK_AVAILABLE=$(df -BG . | awk 'NR==2 {print $4}' | sed 's/G//')
fi
print_info "Available disk space: ${DISK_AVAILABLE}GB"

# Resource requirements check
RESOURCE_WARNING=false
if [ "$MEMORY_MB" -gt 0 ] && [ "$MEMORY_MB" -lt 16384 ]; then
    print_warning "Docker has less than 16GB RAM allocated (found: ~${MEMORY_GB}GB)"
    RESOURCE_WARNING=true
fi

if [ "$DISK_AVAILABLE" -lt 50 ]; then
    print_warning "Less than 50GB disk space available (found: ${DISK_AVAILABLE}GB)"
    RESOURCE_WARNING=true
fi

if [ "$RESOURCE_WARNING" = true ]; then
    echo ""
    print_warning "Onyx recommends at least 16GB RAM and 50GB disk space for optimal performance."
    echo ""
    read -p "Do you want to continue anyway? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Installation cancelled. Please allocate more resources and try again."
        exit 1
    fi
    print_info "Proceeding with installation despite resource limitations..."
fi

# Create directory structure
print_step "Creating directory structure"
mkdir -p onyx_data/deployment
mkdir -p onyx_data/data/nginx/local
print_success "Directory structure created"

# Download Docker Compose file
print_step "Downloading Docker Compose configuration"
COMPOSE_FILE="onyx_data/deployment/docker-compose.yml"
print_info "Downloading docker-compose.yml..."
if curl -fsSL -o "$COMPOSE_FILE" "${GITHUB_RAW_URL}/docker-compose.yml" 2>/dev/null; then
    print_success "Docker Compose file downloaded successfully"
else
    print_error "Failed to download Docker Compose file"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Download env.template file
print_step "Downloading environment template"
ENV_TEMPLATE="onyx_data/deployment/env.template"
print_info "Downloading env.template..."
if curl -fsSL -o "$ENV_TEMPLATE" "${GITHUB_RAW_URL}/env.template" 2>/dev/null; then
    print_success "Environment template downloaded successfully"
else
    print_error "Failed to download env.template"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Download nginx config files
print_step "Setting up nginx configuration"

# Base URL for nginx files
NGINX_BASE_URL="https://raw.githubusercontent.com/onyx-dot-app/onyx/docker-compose-easy/deployment/data/nginx"

# Download app.conf.template
NGINX_CONFIG="onyx_data/data/nginx/app.conf.template"
print_info "Downloading nginx configuration template..."
if curl -fsSL -o "$NGINX_CONFIG" "$NGINX_BASE_URL/app.conf.template" 2>/dev/null; then
    print_success "Nginx configuration template downloaded"
else
    print_error "Failed to download nginx configuration template"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Download run-nginx.sh script
NGINX_RUN_SCRIPT="onyx_data/data/nginx/run-nginx.sh"
print_info "Downloading nginx startup script..."
if curl -fsSL -o "$NGINX_RUN_SCRIPT" "$NGINX_BASE_URL/run-nginx.sh" 2>/dev/null; then
    chmod +x "$NGINX_RUN_SCRIPT"
    print_success "Nginx startup script downloaded and made executable"
else
    print_error "Failed to download nginx startup script"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Create empty local directory marker (if needed)
touch "onyx_data/data/nginx/local/.gitkeep"
print_success "Nginx configuration setup complete"

# Create .env file from template
print_step "Setting up environment configuration"
ENV_FILE="onyx_data/deployment/.env"
if [ ! -f "$ENV_FILE" ]; then
    print_info "Creating .env file from template..."
    cp "$ENV_TEMPLATE" "$ENV_FILE"
    print_success ".env file created"
    echo ""
    print_info "IMPORTANT: The .env file has been created with default settings."
    print_info "You may want to customize it later for:"
    echo "  • Authentication settings (OAuth, SAML, etc.)"
    echo "  • AI model configuration"
    echo "  • Domain settings (for production)"
    echo ""
else
    print_success ".env file already exists, keeping existing configuration"
fi

# Pull Docker images with visible output
print_step "Pulling Docker images"
print_info "This may take several minutes depending on your internet connection..."
echo ""
cd onyx_data/deployment && $COMPOSE_CMD -f docker-compose.yml pull && cd ../..

# Start services
print_step "Starting Onyx services"
print_info "Launching containers..."
echo ""
cd onyx_data/deployment && $COMPOSE_CMD -f docker-compose.yml up -d && cd ../..

# Monitor container startup
print_step "Verifying service health"
print_info "Waiting for services to initialize (30 seconds)..."

# Progress bar for waiting
for i in {1..30}; do
    printf "\r[%-30s] %d%%" $(printf '#%.0s' $(seq 1 $((i*30/30)))) $((i*100/30))
    sleep 1
done
echo ""
echo ""

# Check for restart loops
print_info "Checking container health status..."
RESTART_ISSUES=false
CONTAINERS=$(cd onyx_data/deployment && $COMPOSE_CMD -f docker-compose.yml ps -q)

for CONTAINER in $CONTAINERS; do
    CONTAINER_NAME=$(docker inspect --format '{{.Name}}' "$CONTAINER" | sed 's/^\/\|^onyx_data_deployment_//g')
    RESTART_COUNT=$(docker inspect --format '{{.RestartCount}}' "$CONTAINER")
    STATUS=$(docker inspect --format '{{.State.Status}}' "$CONTAINER")

    if [ "$STATUS" = "running" ]; then
        if [ "$RESTART_COUNT" -gt 2 ]; then
            print_error "$CONTAINER_NAME is in a restart loop (restarted $RESTART_COUNT times)"
            RESTART_ISSUES=true
        else
            print_success "$CONTAINER_NAME is healthy"
        fi
    elif [ "$STATUS" = "restarting" ]; then
        print_error "$CONTAINER_NAME is stuck restarting"
        RESTART_ISSUES=true
    else
        print_warning "$CONTAINER_NAME status: $STATUS"
    fi
done

echo ""

if [ "$RESTART_ISSUES" = true ]; then
    print_error "Some containers are experiencing issues!"
    echo ""
    print_info "Please check the logs for more information:"
    echo "  cd onyx_data/deployment && $COMPOSE_CMD -f docker-compose.yml logs"
    echo ""
    print_info "If the issue persists, please contact: founders@onyx.app"
    echo "Include the output of the logs command in your message."
    exit 1
fi

# Success message
print_step "Installation Complete!"
print_success "All services are running successfully!"
echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}   🎉 Onyx is ready to use! 🎉${NC}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
print_info "Access Onyx at:"
echo -e "   ${BOLD}http://localhost:3000${NC}"
echo ""
print_info "IMPORTANT: First-time setup required!"
echo "   • Visit http://localhost:3000 to create your admin account"
echo "   • The first user you create will automatically have admin privileges"
echo ""
print_info "For help or issues, contact: founders@onyx.app"
echo ""
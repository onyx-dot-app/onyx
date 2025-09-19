#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

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
    echo ""
    echo -e "${BLUE}${BOLD}=== $1 ===${NC}"
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

# GitHub repo base URL
GITHUB_RAW_URL="https://raw.githubusercontent.com/danswer-ai/danswer/main/deployment/docker_compose"

# Check system requirements
print_step "Step 1: Verifying Docker installation"

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
print_step "Step 2: Verifying Docker resources"

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

# Set default values
ENV_FILE=".env"

# Always use the default docker-compose.yml file
print_step "Step 3: Setting up configuration"
COMPOSE_FILE="docker-compose.yml"
print_info "Using default Docker Compose configuration"

# Check if we're in the docker_compose directory or need to download files
if [ -f "$COMPOSE_FILE" ] && [ -f "env.template" ]; then
    print_step "Step 4: Using local Docker Compose configuration"
    print_success "Found local configuration files"
    LOCAL_MODE=true
else
    LOCAL_MODE=false
    # Download Docker Compose file
    print_step "Step 4: Downloading Docker Compose configuration"
    print_info "Downloading $COMPOSE_FILE..."
    if ! curl -fsSL -o "$COMPOSE_FILE" "${GITHUB_RAW_URL}/${COMPOSE_FILE}" 2>/dev/null; then
        # Try alternative branch name
        GITHUB_RAW_URL="https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose"
        if curl -fsSL -o "$COMPOSE_FILE" "${GITHUB_RAW_URL}/${COMPOSE_FILE}" 2>/dev/null; then
            print_success "Docker Compose file downloaded successfully"
        else
            print_error "Failed to download Docker Compose file"
            print_info "Please ensure you're running this from the deployment/docker_compose directory"
            exit 1
        fi
    else
        print_success "Docker Compose file downloaded successfully"
    fi

    # Download env.template file
    print_step "Step 5: Downloading environment template"
    print_info "Downloading env.template..."
    if ! curl -fsSL -o "env.template" "${GITHUB_RAW_URL}/env.template" 2>/dev/null; then
        print_warning "Failed to download env.template from GitHub"
        print_info "Creating minimal env.template..."
        # Create a minimal env.template
        cat > env.template << 'EOF'
# Onyx Configuration
AUTH_TYPE=disabled
SESSION_EXPIRE_TIME_SECONDS=86400
POSTGRES_HOST=relational_db
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=postgres
VESPA_HOST=index
VESPA_PORT=8081
WEB_DOMAIN=http://localhost:3000

# Model Configuration
GEN_AI_MODEL_PROVIDER=openai
GEN_AI_MODEL_VERSION=gpt-4
FAST_GEN_AI_MODEL_VERSION=gpt-3.5-turbo
GEN_AI_API_KEY=

# Disable Telemetry
DISABLE_TELEMETRY=true
EOF
        print_success "Created basic env.template"
    else
        print_success "Environment template downloaded successfully"
    fi
fi

# Create nginx directory if needed
if [ "$LOCAL_MODE" = false ]; then
    print_step "Step 6: Setting up nginx configuration"
else
    print_step "Step 5: Setting up nginx configuration"
fi
mkdir -p nginx
print_success "Created nginx directory"

# Create a default nginx config if it doesn't exist
NGINX_CONFIG="nginx/default.conf"
if [ ! -f "$NGINX_CONFIG" ]; then
    print_info "Creating default nginx configuration..."
    cat > "$NGINX_CONFIG" << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://web_server:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api {
        proxy_pass http://api_server:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
    print_success "Default nginx configuration created"
else
    print_success "Nginx configuration already exists"
fi

# Create .env file from template
if [ "$LOCAL_MODE" = false ]; then
    print_step "Step 7: Setting up environment configuration"
else
    print_step "Step 6: Setting up environment configuration"
fi
if [ ! -f "$ENV_FILE" ]; then
    print_info "Creating .env file from template..."
    cp env.template "$ENV_FILE"
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

# Create necessary directories
if [ "$LOCAL_MODE" = false ]; then
    print_step "Step 8: Creating data directories"
else
    print_step "Step 7: Creating data directories"
fi
mkdir -p data/postgres
mkdir -p data/vespa
mkdir -p data/redis
mkdir -p data/model_cache
print_success "Data directories created"

# Pull Docker images with visible output
if [ "$LOCAL_MODE" = false ]; then
    print_step "Step 9: Pulling Docker images"
else
    print_step "Step 8: Pulling Docker images"
fi
print_info "This may take several minutes depending on your internet connection..."
echo ""
$COMPOSE_CMD -f "$COMPOSE_FILE" pull

# Start services
if [ "$LOCAL_MODE" = false ]; then
    print_step "Step 10: Starting Onyx services"
else
    print_step "Step 9: Starting Onyx services"
fi
print_info "Launching containers..."
echo ""
$COMPOSE_CMD -f "$COMPOSE_FILE" up -d

# Monitor container startup
if [ "$LOCAL_MODE" = false ]; then
    print_step "Step 11: Verifying service health"
else
    print_step "Step 10: Verifying service health"
fi
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
CONTAINERS=$($COMPOSE_CMD -f "$COMPOSE_FILE" ps -q)

for CONTAINER in $CONTAINERS; do
    CONTAINER_NAME=$(docker inspect --format '{{.Name}}' "$CONTAINER" | sed 's/^\/\|^docker_compose_//g')
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
    echo "  $COMPOSE_CMD -f $COMPOSE_FILE logs"
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
echo -e "${BOLD}   http://localhost:3000${NC}"
echo ""
print_info "Default credentials:"
echo "   Email:    ${BOLD}admin@onyx.test${NC}"
echo "   Password: ${BOLD}admin${NC}"
echo ""
print_info "Useful commands:"
echo "   View logs:     ${BOLD}$COMPOSE_CMD -f $COMPOSE_FILE logs -f${NC}"
echo "   Stop Onyx:     ${BOLD}$COMPOSE_CMD -f $COMPOSE_FILE down${NC}"
echo "   Restart Onyx:  ${BOLD}$COMPOSE_CMD -f $COMPOSE_FILE restart${NC}"
echo "   Update Onyx:   ${BOLD}$COMPOSE_CMD -f $COMPOSE_FILE pull && $COMPOSE_CMD -f $COMPOSE_FILE up -d${NC}"
echo ""
print_info "For help or issues, contact: founders@onyx.app"
echo ""
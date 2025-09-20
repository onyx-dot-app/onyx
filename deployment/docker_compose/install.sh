#!/bin/bash

set -e

# Parse command line arguments
SHUTDOWN_MODE=false
DELETE_DATA_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --shutdown)
            SHUTDOWN_MODE=true
            shift
            ;;
        --delete-data)
            DELETE_DATA_MODE=true
            shift
            ;;
        --help|-h)
            echo "Onyx Installation Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --shutdown     Stop and remove Onyx containers"
            echo "  --delete-data  Remove all Onyx data (containers, volumes, and files)"
            echo "  --help, -h     Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Install Onyx"
            echo "  $0 --shutdown         # Stop Onyx services"
            echo "  $0 --delete-data      # Completely remove Onyx and all data"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Step counter variables
CURRENT_STEP=0
TOTAL_STEPS=8

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

# Handle shutdown mode
if [ "$SHUTDOWN_MODE" = true ]; then
    echo ""
    echo -e "${BLUE}${BOLD}=== Shutting down Onyx ===${NC}"
    echo ""
    
    if [ -d "onyx_data/deployment" ]; then
        print_info "Stopping Onyx containers..."
        cd onyx_data/deployment
        
        # Check if docker-compose.yml exists
        if [ -f "docker-compose.yml" ]; then
            # Determine compose command
            if docker compose version &> /dev/null; then
                COMPOSE_CMD="docker compose"
            elif command -v docker-compose &> /dev/null; then
                COMPOSE_CMD="docker-compose"
            else
                print_error "Docker Compose not found. Cannot stop containers."
                exit 1
            fi
            
            # Stop and remove containers
            $COMPOSE_CMD -f docker-compose.yml down
            print_success "Onyx containers stopped and removed"
        else
            print_warning "docker-compose.yml not found in onyx_data/deployment"
        fi
        
        cd ../..
    else
        print_warning "Onyx data directory not found. Nothing to shutdown."
    fi
    
    echo ""
    print_success "Onyx shutdown complete!"
    exit 0
fi

# Handle delete data mode
if [ "$DELETE_DATA_MODE" = true ]; then
    echo ""
    echo -e "${RED}${BOLD}=== WARNING: This will permanently delete all Onyx data ===${NC}"
    echo ""
    print_warning "This action will remove:"
    echo "  • All Onyx containers and volumes"
    echo "  • All downloaded files and configurations"
    echo "  • All user data and documents"
    echo ""
    read -p "Are you sure you want to continue? Type 'DELETE' to confirm: " -r
    echo ""
    
    if [ "$REPLY" != "DELETE" ]; then
        print_info "Operation cancelled."
        exit 0
    fi
    
    print_info "Removing Onyx containers and volumes..."
    
    if [ -d "onyx_data/deployment" ]; then
        cd onyx_data/deployment
        
        # Check if docker-compose.yml exists
        if [ -f "docker-compose.yml" ]; then
            # Determine compose command
            if docker compose version &> /dev/null; then
                COMPOSE_CMD="docker compose"
            elif command -v docker-compose &> /dev/null; then
                COMPOSE_CMD="docker-compose"
            else
                print_error "Docker Compose not found. Cannot remove containers."
                exit 1
            fi
            
            # Stop and remove containers with volumes
            $COMPOSE_CMD -f docker-compose.yml down -v
            print_success "Onyx containers and volumes removed"
        fi
        
        cd ../..
    fi
    
    print_info "Removing data directories..."
    if [ -d "onyx_data" ]; then
        rm -rf onyx_data
        print_success "Data directories removed"
    else
        print_warning "No onyx_data directory found"
    fi
    
    echo ""
    print_success "All Onyx data has been permanently deleted!"
    exit 0
fi

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
if [ -d "onyx_data" ]; then
    print_info "Directory structure already exists"
    print_success "Using existing onyx_data directory"
else
    mkdir -p onyx_data/deployment
    mkdir -p onyx_data/data/nginx/local
    print_success "Directory structure created"
fi

# Download all required files
print_step "Downloading Onyx configuration files"
print_info "This step downloads all necessary configuration files from GitHub..."
echo ""
print_info "Downloading the following files:"
echo "  • docker-compose.yml - Main Docker Compose configuration"
echo "  • env.template - Environment variables template"
echo "  • nginx/app.conf.template - Nginx web server configuration"
echo "  • nginx/run-nginx.sh - Nginx startup script"
echo "  • README.md - Documentation and setup instructions"
echo ""

# Download Docker Compose file
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

# Download README file
README_FILE="onyx_data/README.md"
print_info "Downloading README.md..."
if curl -fsSL -o "$README_FILE" "${GITHUB_RAW_URL}/README.md" 2>/dev/null; then
    print_success "README.md downloaded successfully"
else
    print_error "Failed to download README.md"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Create empty local directory marker (if needed)
touch "onyx_data/data/nginx/local/.gitkeep"
print_success "All configuration files downloaded successfully"

# Set up deployment configuration
print_step "Setting up deployment configs"
ENV_FILE="onyx_data/deployment/.env"

# Check if services are already running
if [ -d "onyx_data/deployment" ] && [ -f "onyx_data/deployment/docker-compose.yml" ]; then
    cd onyx_data/deployment
    
    # Determine compose command
    if docker compose version &> /dev/null; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        COMPOSE_CMD=""
    fi
    
    if [ -n "$COMPOSE_CMD" ]; then
        # Check if any containers are running
        RUNNING_CONTAINERS=$($COMPOSE_CMD -f docker-compose.yml ps -q 2>/dev/null | wc -l)
        if [ "$RUNNING_CONTAINERS" -gt 0 ]; then
            print_error "Onyx services are currently running!"
            echo ""
            print_info "To make configuration changes, you must first shut down the services."
            echo ""
            print_info "Please run the following command to shut down Onyx:"
            echo -e "   ${BOLD}./install.sh --shutdown${NC}"
            echo ""
            print_info "Then run this script again to make your changes."
            exit 1
        fi
    fi
    
    cd ../..
fi

if [ -f "$ENV_FILE" ]; then
    print_info "Existing .env file found. What would you like to do?"
    echo ""
    echo "1) Restart - Keep current configuration and restart services"
    echo "2) Upgrade - Update to a newer version"
    echo ""
    read -p "Choose an option (1-2) [default 1]: " -r
    echo ""
    
    case "${REPLY:-1}" in
        1)
            print_info "Keeping existing configuration..."
            print_success "Will restart with current settings"
            ;;
        2)
            print_info "Upgrade selected. Which tag would you like to deploy?"
            echo ""
            echo "1) Latest (recommended)"
            echo "2) Specific tag"
            echo ""
            read -p "Choose an option (1-2) [default 1]: " -r VERSION_CHOICE
            echo ""
            
            case "${VERSION_CHOICE:-1}" in
                1)
                    VERSION="latest"
                    print_info "Selected: Latest version"
                    ;;
                2)
                    read -p "Enter version (e.g., v0.1.0): " -r VERSION
                    if [ -z "$VERSION" ]; then
                        VERSION="latest"
                        print_info "No version specified, using latest"
                    else
                        print_info "Selected: $VERSION"
                    fi
                    ;;
            esac
            
            # Update .env file with new version
            print_info "Updating configuration for version $VERSION..."
            if grep -q "^IMAGE_TAG=" "$ENV_FILE"; then
                # Update existing IMAGE_TAG line
                sed -i.bak "s/^IMAGE_TAG=.*/IMAGE_TAG=$VERSION/" "$ENV_FILE"
            else
                # Add IMAGE_TAG line if it doesn't exist
                echo "IMAGE_TAG=$VERSION" >> "$ENV_FILE"
            fi
            print_success "Updated IMAGE_TAG to $VERSION in .env file"
            print_success "Configuration updated for upgrade"
            ;;
        *)
            print_info "Invalid choice, keeping existing configuration..."
            ;;
    esac
else
    print_info "No existing .env file found. Setting up new deployment..."
    echo ""
    
    # Ask for version
    print_info "Which tag would you like to deploy?"
    echo ""
    echo "1) Latest (recommended)"
    echo "2) Specific tag"
    echo ""
    read -p "Choose an option (1-2) [default 1]: " -r VERSION_CHOICE
    echo ""
    
    case "${VERSION_CHOICE:-1}" in
        1)
            VERSION="latest"
            print_info "Selected: Latest tag"
            ;;
        2)
            read -p "Enter tag (e.g., v0.1.0): " -r VERSION
            if [ -z "$VERSION" ]; then
                VERSION="latest"
                print_info "No tag specified, using latest"
            else
                print_info "Selected: $VERSION"
            fi
            ;;
    esac
    
    # Ask for authentication schema
    echo ""
    print_info "Which authentication schema would you like to set up?"
    echo ""
    echo "1) No Auth - Open access (development/testing)"
    echo "2) Basic - Username/password authentication"
    echo ""
    read -p "Choose an option (1-2) [default 1]: " -r AUTH_CHOICE
    echo ""
    
    case "${AUTH_CHOICE:-1}" in
        1)
            AUTH_SCHEMA="disabled"
            print_info "Selected: No authentication"
            ;;
        2)
            AUTH_SCHEMA="basic"
            print_info "Selected: Basic authentication"
            ;;
        *)
            AUTH_SCHEMA="disabled"
            print_info "Invalid choice, using no authentication"
            ;;
    esac
    
    # Create .env file from template
    print_info "Creating .env file with your selections..."
    cp "$ENV_TEMPLATE" "$ENV_FILE"
    
    # Update IMAGE_TAG with selected version
    print_info "Setting IMAGE_TAG to $VERSION..."
    sed -i.bak "s/^IMAGE_TAG=.*/IMAGE_TAG=$VERSION/" "$ENV_FILE"
    print_success "IMAGE_TAG set to $VERSION"
    
    # Configure authentication settings based on selection
    if [ "$AUTH_SCHEMA" = "disabled" ]; then
        # Disable authentication in .env file
        sed -i.bak 's/^AUTH_TYPE=.*/AUTH_TYPE=disabled/' "$ENV_FILE" 2>/dev/null || true
        print_success "Authentication disabled in configuration"
    else
        # Enable basic authentication
        sed -i.bak 's/^AUTH_TYPE=.*/AUTH_TYPE=basic/' "$ENV_FILE" 2>/dev/null || true
        print_success "Basic authentication enabled in configuration"
    fi
    
    print_success ".env file created with your preferences"
    echo ""
    print_info "IMPORTANT: The .env file has been configured with your selections."
    print_info "You can customize it later for:"
    echo "  • Advanced authentication (OAuth, SAML, etc.)"
    echo "  • AI model configuration"
    echo "  • Domain settings (for production)"
    echo ""
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
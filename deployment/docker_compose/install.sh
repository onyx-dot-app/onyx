#!/bin/bash

set -euo pipefail

# Expected resource requirements (overridden below if --lite)
EXPECTED_DOCKER_RAM_GB=10
EXPECTED_DISK_GB=32

# Parse command line arguments
SHUTDOWN_MODE=false
DELETE_DATA_MODE=false
INCLUDE_CRAFT=false  # Disabled by default, use --include-craft to enable
LITE_MODE=false       # Disabled by default, use --lite to enable
NO_PROMPT=false
DRY_RUN=false
VERBOSE=false

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
        --include-craft)
            INCLUDE_CRAFT=true
            shift
            ;;
        --lite)
            LITE_MODE=true
            shift
            ;;
        --no-prompt)
            NO_PROMPT=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "Onyx Installation Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --include-craft  Enable Onyx Craft (AI-powered web app building)"
            echo "  --lite           Deploy Onyx Lite (no Vespa, Redis, or model servers)"
            echo "  --shutdown       Stop (pause) Onyx containers"
            echo "  --delete-data    Remove all Onyx data (containers, volumes, and files)"
            echo "  --no-prompt      Run non-interactively with defaults (for CI/automation)"
            echo "  --dry-run        Show what would be done without making changes"
            echo "  --verbose        Show detailed output for debugging"
            echo "  --help, -h       Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Install Onyx"
            echo "  $0 --lite             # Install Onyx Lite (minimal deployment)"
            echo "  $0 --include-craft    # Install Onyx with Craft enabled"
            echo "  $0 --shutdown         # Pause Onyx services"
            echo "  $0 --delete-data      # Completely remove Onyx and all data"
            echo "  $0 --no-prompt        # Non-interactive install with defaults"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

if [[ "$VERBOSE" = true ]]; then
    set -x
fi

if [[ "$LITE_MODE" = true ]] && [[ "$INCLUDE_CRAFT" = true ]]; then
    echo "ERROR: --lite and --include-craft cannot be used together."
    echo "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
    exit 1
fi

# When --lite is passed as a flag, lower resource thresholds early (before the
# resource check). When lite is chosen interactively, the thresholds are adjusted
# inside the new-deployment flow, after the resource check has already passed
# with the standard thresholds — which is the safer direction.
if [[ "$LITE_MODE" = true ]]; then
    EXPECTED_DOCKER_RAM_GB=4
    EXPECTED_DISK_GB=16
fi

INSTALL_ROOT="${INSTALL_PREFIX:-onyx_data}"

LITE_COMPOSE_FILE="docker-compose.onyx-lite.yml"

# Build the -f flags for docker compose.
# Pass "true" as $1 to auto-detect a previously-downloaded lite overlay
# (used by shutdown/delete-data so users don't need to remember --lite).
# Without the argument, the lite overlay is only included when --lite was
# explicitly passed — preventing install/start from silently staying in
# lite mode just because the file exists on disk from a prior run.
compose_file_args() {
    local auto_detect="${1:-false}"
    local args="-f docker-compose.yml"
    if [[ "$LITE_MODE" = true ]] || { [[ "$auto_detect" = true ]] && [[ -f "${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}" ]]; }; then
        args="$args -f ${LITE_COMPOSE_FILE}"
    fi
    echo "$args"
}

# --- Downloader detection (curl with wget fallback) ---
DOWNLOADER=""
detect_downloader() {
    if command -v curl &> /dev/null; then
        DOWNLOADER="curl"
        return 0
    fi
    if command -v wget &> /dev/null; then
        DOWNLOADER="wget"
        return 0
    fi
    echo "ERROR: Neither curl nor wget found. Please install one and retry."
    exit 1
}
detect_downloader

download_file() {
    local url="$1"
    local output="$2"
    if [[ "$DOWNLOADER" == "curl" ]]; then
        curl -fsSL --retry 3 --retry-delay 2 --retry-connrefused -o "$output" "$url"
    else
        wget -q --tries=3 --timeout=20 -O "$output" "$url"
    fi
}

# --- Interactive prompt helpers ---
is_interactive() {
    [[ "$NO_PROMPT" = false ]] && [[ -t 0 ]]
}

prompt_or_default() {
    local prompt_text="$1"
    local default_value="$2"
    if is_interactive; then
        read -p "$prompt_text" -r REPLY
        if [[ -z "$REPLY" ]]; then
            REPLY="$default_value"
        fi
    else
        REPLY="$default_value"
    fi
}

prompt_yn_or_default() {
    local prompt_text="$1"
    local default_value="$2"
    if is_interactive; then
        read -p "$prompt_text" -n 1 -r
        echo ""
    else
        REPLY="$default_value"
    fi
}

prompt_enter_or_skip() {
    local prompt_text="$1"
    if is_interactive; then
        echo -e "$prompt_text"
        read -r
    fi
}

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

# Handle shutdown mode
if [ "$SHUTDOWN_MODE" = true ]; then
    echo ""
    echo -e "${BLUE}${BOLD}=== Shutting down Onyx ===${NC}"
    echo ""
    
    if [ -d "${INSTALL_ROOT}/deployment" ]; then
        print_info "Stopping Onyx containers..."

        # Check if docker-compose.yml exists
        if [ -f "${INSTALL_ROOT}/deployment/docker-compose.yml" ]; then
            # Determine compose command
            if docker compose version &> /dev/null; then
                COMPOSE_CMD="docker compose"
            elif command -v docker-compose &> /dev/null; then
                COMPOSE_CMD="docker-compose"
            else
                print_error "Docker Compose not found. Cannot stop containers."
                exit 1
            fi

            # Stop containers (without removing them)
            (cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD $(compose_file_args true) stop)
            if [ $? -eq 0 ]; then
                print_success "Onyx containers stopped (paused)"
            else
                print_error "Failed to stop containers"
                exit 1
            fi
        else
            print_warning "docker-compose.yml not found in ${INSTALL_ROOT}/deployment"
        fi
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
    if is_interactive; then
        read -p "Are you sure you want to continue? Type 'DELETE' to confirm: " -r
        echo ""
        if [ "$REPLY" != "DELETE" ]; then
            print_info "Operation cancelled."
            exit 0
        fi
    else
        print_error "Cannot confirm destructive operation in non-interactive mode."
        print_info "Run interactively or remove the ${INSTALL_ROOT} directory manually."
        exit 1
    fi

    print_info "Removing Onyx containers and volumes..."

    if [ -d "${INSTALL_ROOT}/deployment" ]; then
        # Check if docker-compose.yml exists
        if [ -f "${INSTALL_ROOT}/deployment/docker-compose.yml" ]; then
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
            (cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD $(compose_file_args true) down -v)
            if [ $? -eq 0 ]; then
                print_success "Onyx containers and volumes removed"
            else
                print_error "Failed to remove containers and volumes"
            fi
        fi
    fi

    print_info "Removing data directories..."
    if [ -d "${INSTALL_ROOT}" ]; then
        rm -rf "${INSTALL_ROOT}"
        print_success "Data directories removed"
    else
        print_warning "No ${INSTALL_ROOT} directory found"
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

# User acknowledgment section
echo -e "${YELLOW}${BOLD}This script will:${NC}"
echo "1. Download deployment files for Onyx into a new '${INSTALL_ROOT}' directory"
echo "2. Check your system resources (Docker, memory, disk space)"
echo "3. Guide you through deployment options (version, authentication)"
echo ""

if is_interactive; then
    echo -e "${YELLOW}${BOLD}Please acknowledge and press Enter to continue...${NC}"
    read -r
    echo ""
else
    echo -e "${YELLOW}${BOLD}Running in non-interactive mode - proceeding automatically...${NC}"
    echo ""
fi

# Detect OS (including WSL)
IS_WSL=false
if [[ -n "${WSL_DISTRO_NAME:-}" ]] || grep -qi microsoft /proc/version 2>/dev/null; then
    IS_WSL=true
fi

# Dry-run: show plan and exit
if [[ "$DRY_RUN" = true ]]; then
    print_info "Dry run mode — showing what would happen:"
    echo "  • Install root: ${INSTALL_ROOT}"
    echo "  • Lite mode: ${LITE_MODE}"
    echo "  • Include Craft: ${INCLUDE_CRAFT}"
    echo "  • OS type: ${OSTYPE:-unknown} (WSL: ${IS_WSL})"
    echo "  • Downloader: ${DOWNLOADER}"
    echo ""
    print_success "Dry run complete (no changes made)"
    exit 0
fi

# GitHub repo base URL - using main branch
GITHUB_RAW_URL="https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose"

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
    if [ -z "$COMPOSE_VERSION" ]; then
        # Handle non-standard versions like "dev" - assume recent enough
        COMPOSE_VERSION="dev"
        print_success "Docker Compose (dev build) is installed (plugin)"
    else
        print_success "Docker Compose $COMPOSE_VERSION is installed (plugin)"
    fi
elif command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(docker-compose --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    COMPOSE_CMD="docker-compose"
    if [ -z "$COMPOSE_VERSION" ]; then
        COMPOSE_VERSION="dev"
        print_success "Docker Compose (dev build) is installed (standalone)"
    else
        print_success "Docker Compose $COMPOSE_VERSION is installed (standalone)"
    fi
else
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    echo "Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

# Returns 0 if $1 <= $2, 1 if $1 > $2
# Handles missing or non-numeric parts gracefully (treats them as 0)
version_compare() {
    local version1="${1:-0.0.0}"
    local version2="${2:-0.0.0}"

    local v1_major v1_minor v1_patch v2_major v2_minor v2_patch
    v1_major=$(echo "$version1" | cut -d. -f1)
    v1_minor=$(echo "$version1" | cut -d. -f2)
    v1_patch=$(echo "$version1" | cut -d. -f3)
    v2_major=$(echo "$version2" | cut -d. -f1)
    v2_minor=$(echo "$version2" | cut -d. -f2)
    v2_patch=$(echo "$version2" | cut -d. -f3)

    # Default non-numeric or empty parts to 0
    [[ "$v1_major" =~ ^[0-9]+$ ]] || v1_major=0
    [[ "$v1_minor" =~ ^[0-9]+$ ]] || v1_minor=0
    [[ "$v1_patch" =~ ^[0-9]+$ ]] || v1_patch=0
    [[ "$v2_major" =~ ^[0-9]+$ ]] || v2_major=0
    [[ "$v2_minor" =~ ^[0-9]+$ ]] || v2_minor=0
    [[ "$v2_patch" =~ ^[0-9]+$ ]] || v2_patch=0

    if [ "$v1_major" -lt "$v2_major" ]; then return 0
    elif [ "$v1_major" -gt "$v2_major" ]; then return 1; fi

    if [ "$v1_minor" -lt "$v2_minor" ]; then return 0
    elif [ "$v1_minor" -gt "$v2_minor" ]; then return 1; fi

    [ "$v1_patch" -le "$v2_patch" ]
}

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
EXPECTED_RAM_MB=$((EXPECTED_DOCKER_RAM_GB * 1024))

if [ "$MEMORY_MB" -gt 0 ] && [ "$MEMORY_MB" -lt "$EXPECTED_RAM_MB" ]; then
    print_warning "Docker has less than ${EXPECTED_DOCKER_RAM_GB}GB RAM allocated (found: ~${MEMORY_GB}GB)"
    RESOURCE_WARNING=true
fi

if [ "$DISK_AVAILABLE" -lt "$EXPECTED_DISK_GB" ]; then
    print_warning "Less than ${EXPECTED_DISK_GB}GB disk space available (found: ${DISK_AVAILABLE}GB)"
    RESOURCE_WARNING=true
fi

if [ "$RESOURCE_WARNING" = true ]; then
    echo ""
    print_warning "Onyx recommends at least ${EXPECTED_DOCKER_RAM_GB}GB RAM and ${EXPECTED_DISK_GB}GB disk space for optimal performance."
    echo ""
    prompt_yn_or_default "Do you want to continue anyway? (y/N): " "y"
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Installation cancelled. Please allocate more resources and try again."
        exit 1
    fi
    print_info "Proceeding with installation despite resource limitations..."
fi

# Create directory structure
print_step "Creating directory structure"
if [ -d "${INSTALL_ROOT}" ]; then
    print_info "Directory structure already exists"
    print_success "Using existing ${INSTALL_ROOT} directory"
else
    mkdir -p "${INSTALL_ROOT}/deployment"
    mkdir -p "${INSTALL_ROOT}/data/nginx/local"
    print_success "Directory structure created"
fi

# Download all required files
print_step "Downloading Onyx configuration files"
print_info "This step downloads all necessary configuration files from GitHub..."
echo ""
print_info "Downloading the following files:"
echo "  • docker-compose.yml - Main Docker Compose configuration"
if [[ "$LITE_MODE" = true ]]; then
    echo "  • ${LITE_COMPOSE_FILE} - Lite mode overlay"
fi
echo "  • env.template - Environment variables template"
echo "  • nginx/app.conf.template - Nginx web server configuration"
echo "  • nginx/run-nginx.sh - Nginx startup script"
echo "  • README.md - Documentation and setup instructions"
echo ""

# Download Docker Compose file
COMPOSE_FILE="${INSTALL_ROOT}/deployment/docker-compose.yml"
print_info "Downloading docker-compose.yml..."
if download_file "${GITHUB_RAW_URL}/docker-compose.yml" "$COMPOSE_FILE" 2>/dev/null; then
    print_success "Docker Compose file downloaded successfully"

    # Check if Docker Compose version is older than 2.24.0 and show warning
    # Skip check for dev builds (assume they're recent enough)
    if [ "$COMPOSE_VERSION" != "dev" ] && version_compare "$COMPOSE_VERSION" "2.24.0"; then
        print_warning "Docker Compose version $COMPOSE_VERSION is older than 2.24.0"
        echo ""
        print_warning "The docker-compose.yml file uses the newer env_file format that requires Docker Compose 2.24.0 or later."
        echo ""
        print_info "To use this configuration with your current Docker Compose version, you have two options:"
        echo ""
        echo "1. Upgrade Docker Compose to version 2.24.0 or later (recommended)"
        echo "   Visit: https://docs.docker.com/compose/install/"
        echo ""
        echo "2. Manually replace all env_file sections in docker-compose.yml"
        echo "   Change from:"
        echo "     env_file:"
        echo "       - path: .env"
        echo "         required: false"
        echo "   To:"
        echo "     env_file: .env"
        echo ""
        print_warning "The installation will continue, but may fail if Docker Compose cannot parse the file."
        echo ""
        prompt_yn_or_default "Do you want to continue anyway? (y/N): " "y"
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Installation cancelled. Please upgrade Docker Compose or manually edit the docker-compose.yml file."
            exit 1
        fi
        print_info "Proceeding with installation despite Docker Compose version compatibility issues..."
    fi
else
    print_error "Failed to download Docker Compose file"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Download lite overlay if --lite was requested, otherwise remove any stale
# overlay from a previous lite install so shutdown/delete-data auto-detection
# doesn't mistakenly include it later.
if [[ "$LITE_MODE" = true ]]; then
    LITE_FILE="${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}"
    print_info "Downloading ${LITE_COMPOSE_FILE} (lite overlay)..."
    if download_file "${GITHUB_RAW_URL}/${LITE_COMPOSE_FILE}" "$LITE_FILE" 2>/dev/null; then
        print_success "Lite overlay downloaded successfully"
    else
        print_error "Failed to download lite overlay"
        print_info "Please ensure you have internet connection and try again"
        exit 1
    fi
elif [[ -f "${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}" ]]; then
    rm -f "${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}"
    print_info "Removed previous lite overlay (switching to standard mode)"
fi

# Download env.template file
ENV_TEMPLATE="${INSTALL_ROOT}/deployment/env.template"
print_info "Downloading env.template..."
if download_file "${GITHUB_RAW_URL}/env.template" "$ENV_TEMPLATE" 2>/dev/null; then
    print_success "Environment template downloaded successfully"
else
    print_error "Failed to download env.template"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Download nginx config files
NGINX_BASE_URL="https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/data/nginx"

# Download app.conf.template
NGINX_CONFIG="${INSTALL_ROOT}/data/nginx/app.conf.template"
print_info "Downloading nginx configuration template..."
if download_file "$NGINX_BASE_URL/app.conf.template" "$NGINX_CONFIG" 2>/dev/null; then
    print_success "Nginx configuration template downloaded"
else
    print_error "Failed to download nginx configuration template"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Download run-nginx.sh script
NGINX_RUN_SCRIPT="${INSTALL_ROOT}/data/nginx/run-nginx.sh"
print_info "Downloading nginx startup script..."
if download_file "$NGINX_BASE_URL/run-nginx.sh" "$NGINX_RUN_SCRIPT" 2>/dev/null; then
    chmod +x "$NGINX_RUN_SCRIPT"
    print_success "Nginx startup script downloaded and made executable"
else
    print_error "Failed to download nginx startup script"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Download README file
README_FILE="${INSTALL_ROOT}/README.md"
print_info "Downloading README.md..."
if download_file "${GITHUB_RAW_URL}/README.md" "$README_FILE" 2>/dev/null; then
    print_success "README.md downloaded successfully"
else
    print_error "Failed to download README.md"
    print_info "Please ensure you have internet connection and try again"
    exit 1
fi

# Create empty local directory marker (if needed)
touch "${INSTALL_ROOT}/data/nginx/local/.gitkeep"
print_success "All configuration files downloaded successfully"

# Set up deployment configuration
print_step "Setting up deployment configs"
ENV_FILE="${INSTALL_ROOT}/deployment/.env"
# Check if services are already running
if [ -d "${INSTALL_ROOT}/deployment" ] && [ -f "${INSTALL_ROOT}/deployment/docker-compose.yml" ]; then
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
        RUNNING_CONTAINERS=$(cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD $(compose_file_args true) ps -q 2>/dev/null | wc -l)
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
fi

if [ -f "$ENV_FILE" ]; then
    print_info "Existing .env file found. What would you like to do?"
    echo ""
    echo "• Press Enter to restart with current configuration"
    echo "• Type 'update' to update to a newer version"
    echo ""
    prompt_or_default "Choose an option [default: restart]: " ""
    echo ""

    if [ "$REPLY" = "update" ]; then
        print_info "Update selected. Which tag would you like to deploy?"
        echo ""
        echo "• Press Enter for latest (recommended)"
        echo "• Type a specific tag (e.g., v0.1.0)"
        echo ""
        if [ "$INCLUDE_CRAFT" = true ]; then
            prompt_or_default "Enter tag [default: craft-latest]: " "craft-latest"
            VERSION="$REPLY"
        else
            prompt_or_default "Enter tag [default: latest]: " "latest"
            VERSION="$REPLY"
        fi
        echo ""

        if [ "$INCLUDE_CRAFT" = true ] && [ "$VERSION" = "craft-latest" ]; then
            print_info "Selected: craft-latest (Craft enabled)"
        elif [ "$VERSION" = "latest" ]; then
            print_info "Selected: Latest version"
        else
            print_info "Selected: $VERSION"
        fi

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

        # If using craft image, also enable ENABLE_CRAFT
        if [[ "$VERSION" == craft-* ]]; then
            sed -i.bak 's/^#* *ENABLE_CRAFT=.*/ENABLE_CRAFT=true/' "$ENV_FILE" 2>/dev/null || true
            print_success "ENABLE_CRAFT set to true"
        fi
        print_success "Configuration updated for upgrade"
    else
        print_info "Keeping existing configuration..."
        print_success "Will restart with current settings"
    fi
else
    print_info "No existing .env file found. Setting up new deployment..."
    echo ""

    # Ask for deployment mode (standard vs lite) unless already set via --lite flag
    if [[ "$LITE_MODE" = false ]]; then
        print_info "Which deployment mode would you like?"
        echo ""
        echo "  1) Standard  - Full deployment with search, connectors, and RAG"
        echo "  2) Lite      - Minimal deployment (no Vespa, Redis, or model servers)"
        echo "                  LLM chat, tools, file uploads, and Projects still work"
        echo ""
        prompt_or_default "Choose a mode (1 or 2) [default: 1]: " "1"
        echo ""

        case "$REPLY" in
            2)
                LITE_MODE=true
                print_info "Selected: Lite mode"
                LITE_FILE="${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}"
                print_info "Downloading ${LITE_COMPOSE_FILE} (lite overlay)..."
                if download_file "${GITHUB_RAW_URL}/${LITE_COMPOSE_FILE}" "$LITE_FILE"; then
                    print_success "Lite overlay downloaded successfully"
                else
                    print_error "Failed to download lite overlay"
                    exit 1
                fi
                ;;
            *)
                print_info "Selected: Standard mode"
                ;;
        esac
    else
        print_info "Deployment mode: Lite (set via --lite flag)"
    fi

    # Validate lite + craft combination (could now be set interactively)
    if [[ "$LITE_MODE" = true ]] && [[ "$INCLUDE_CRAFT" = true ]]; then
        print_error "--include-craft cannot be used with Lite mode."
        print_info "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
        exit 1
    fi

    # Adjust resource expectations for lite mode
    if [[ "$LITE_MODE" = true ]]; then
        EXPECTED_DOCKER_RAM_GB=4
        EXPECTED_DISK_GB=16
    fi

    # Ask for version
    print_info "Which tag would you like to deploy?"
    echo ""
    if [ "$INCLUDE_CRAFT" = true ]; then
        echo "• Press Enter for craft-latest (recommended for Craft)"
        echo "• Type a specific tag (e.g., craft-v1.0.0)"
        echo ""
        prompt_or_default "Enter tag [default: craft-latest]: " "craft-latest"
        VERSION="$REPLY"
    else
        echo "• Press Enter for latest (recommended)"
        echo "• Type a specific tag (e.g., v0.1.0)"
        echo ""
        prompt_or_default "Enter tag [default: latest]: " "latest"
        VERSION="$REPLY"
    fi
    echo ""

    if [ "$INCLUDE_CRAFT" = true ] && [ "$VERSION" = "craft-latest" ]; then
        print_info "Selected: craft-latest (Craft enabled)"
    elif [ "$VERSION" = "latest" ]; then
        print_info "Selected: Latest tag"
    else
        print_info "Selected: $VERSION"
    fi

    # Ask for authentication schema
    # echo ""
    # print_info "Which authentication schema would you like to set up?"
    # echo ""
    # echo "1) Basic - Username/password authentication"
    # echo "2) No Auth - Open access (development/testing)"
    # echo ""
    # read -p "Choose an option (1) [default 1]: " -r AUTH_CHOICE
    # echo ""

    # case "${AUTH_CHOICE:-1}" in
    #     1)
    #         AUTH_SCHEMA="basic"
    #         print_info "Selected: Basic authentication"
    #         ;;
    #     # 2)
    #     #     AUTH_SCHEMA="disabled"
    #     #     print_info "Selected: No authentication"
    #     #     ;;
    #     *)
    #         AUTH_SCHEMA="basic"
    #         print_info "Invalid choice, using basic authentication"
    #         ;;
    # esac

    # TODO (jessica): Uncomment this once no auth users still have an account
    # Use basic auth by default
    AUTH_SCHEMA="basic"

    # Reject craft image tags when running in lite mode (must check before writing .env)
    if [[ "$LITE_MODE" = true ]] && [[ "${VERSION:-}" == craft-* ]]; then
        print_error "Cannot use a craft image tag (${VERSION}) with --lite."
        print_info "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
        exit 1
    fi

    # Create .env file from template
    print_info "Creating .env file with your selections..."
    cp "$ENV_TEMPLATE" "$ENV_FILE"

    # Update IMAGE_TAG with selected version
    print_info "Setting IMAGE_TAG to $VERSION..."
    sed -i.bak "s/^IMAGE_TAG=.*/IMAGE_TAG=$VERSION/" "$ENV_FILE"
    print_success "IMAGE_TAG set to $VERSION"

    # Configure basic authentication (default)
    sed -i.bak 's/^AUTH_TYPE=.*/AUTH_TYPE=basic/' "$ENV_FILE" 2>/dev/null || true
    print_success "Basic authentication enabled in configuration"

    # Check if openssl is available
    if ! command -v openssl &> /dev/null; then
        print_error "openssl is required to generate secure secrets but was not found."
        exit 1
    fi

    # Generate a secure USER_AUTH_SECRET
    USER_AUTH_SECRET=$(openssl rand -hex 32)
    sed -i.bak "s/^USER_AUTH_SECRET=.*/USER_AUTH_SECRET=\"$USER_AUTH_SECRET\"/" "$ENV_FILE" 2>/dev/null || true

    # Configure Craft based on flag or if using a craft-* image tag
    # By default, env.template has Craft commented out (disabled)
    if [ "$INCLUDE_CRAFT" = true ] || [[ "$VERSION" == craft-* ]]; then
        # Set ENABLE_CRAFT=true for runtime configuration (handles commented and uncommented lines)
        sed -i.bak 's/^#* *ENABLE_CRAFT=.*/ENABLE_CRAFT=true/' "$ENV_FILE" 2>/dev/null || true
        print_success "Onyx Craft enabled (ENABLE_CRAFT=true)"
    else
        print_info "Onyx Craft disabled (use --include-craft to enable)"
    fi

    print_success ".env file created with your preferences"
    echo ""
    print_info "IMPORTANT: The .env file has been configured with your selections."
    print_info "You can customize it later for:"
    echo "  • Advanced authentication (OAuth, SAML, etc.)"
    echo "  • AI model configuration"
    echo "  • Domain settings (for production)"
    echo "  • Onyx Craft (set ENABLE_CRAFT=true)"
    echo ""
fi

# Function to check if a port is available
is_port_available() {
    local port=$1

    # Try netcat first if available
    if command -v nc &> /dev/null; then
        # Try to connect to the port, if it fails, the port is available
        ! nc -z localhost "$port" 2>/dev/null
    # Fallback using curl/telnet approach
    elif command -v curl &> /dev/null; then
        # Try to connect with curl, if it fails, the port might be available
        ! curl -s --max-time 1 --connect-timeout 1 "http://localhost:$port" >/dev/null 2>&1
    # Final fallback using lsof if available
    elif command -v lsof &> /dev/null; then
        # Check if any process is listening on the port
        ! lsof -i ":$port" >/dev/null 2>&1
    else
        # No port checking tools available, assume port is available
        print_warning "No port checking tools available (nc, curl, lsof). Assuming port $port is available."
        return 0
    fi
}

# Function to find the first available port starting from a given port
find_available_port() {
    local start_port=${1:-3000}
    local port=$start_port

    while [ $port -le 65535 ]; do
        if is_port_available "$port"; then
            echo "$port"
            return 0
        fi
        port=$((port + 1))
    done

    # If no port found, return the original port as fallback
    echo "$start_port"
    return 1
}

# Check for port checking tools availability
PORT_CHECK_AVAILABLE=false
if command -v nc &> /dev/null || command -v curl &> /dev/null || command -v lsof &> /dev/null; then
    PORT_CHECK_AVAILABLE=true
fi

if [ "$PORT_CHECK_AVAILABLE" = false ]; then
    print_warning "No port checking tools found (nc, curl, lsof). Port detection may not work properly."
    print_info "Consider installing one of these tools for reliable automatic port detection."
fi

# Find available port for nginx
print_step "Checking for available ports"
AVAILABLE_PORT=$(find_available_port 3000)

if [ "$AVAILABLE_PORT" != "3000" ]; then
    print_info "Port 3000 is in use, found available port: $AVAILABLE_PORT"
else
    print_info "Port 3000 is available"
fi

# Export HOST_PORT for docker-compose
export HOST_PORT=$AVAILABLE_PORT
print_success "Using port $AVAILABLE_PORT for nginx"

# Determine if we're using the latest tag or a craft tag (both should force pull)
# Read IMAGE_TAG from .env file and remove any quotes or whitespace
CURRENT_IMAGE_TAG=$(grep "^IMAGE_TAG=" "$ENV_FILE" | head -1 | cut -d'=' -f2 | tr -d ' "'"'"'')
if [ "$CURRENT_IMAGE_TAG" = "latest" ] || [[ "$CURRENT_IMAGE_TAG" == craft-* ]]; then
    USE_LATEST=true
    if [[ "$CURRENT_IMAGE_TAG" == craft-* ]]; then
        print_info "Using craft tag '$CURRENT_IMAGE_TAG' - will force pull and recreate containers"
    else
        print_info "Using 'latest' tag - will force pull and recreate containers"
    fi
else
    USE_LATEST=false
fi

# Pull Docker images with reduced output
print_step "Pulling Docker images"
print_info "This may take several minutes depending on your internet connection..."
echo ""
print_info "Downloading Docker images (this may take a while)..."
(cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD $(compose_file_args) pull --quiet)
if [ $? -eq 0 ]; then
    print_success "Docker images downloaded successfully"
else
    print_error "Failed to download Docker images"
    exit 1
fi

# Start services
print_step "Starting Onyx services"
print_info "Launching containers..."
echo ""
if [ "$USE_LATEST" = true ]; then
    print_info "Force pulling latest images and recreating containers..."
    (cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD $(compose_file_args) up -d --pull always --force-recreate)
else
    (cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD $(compose_file_args) up -d)
fi
if [ $? -ne 0 ]; then
    print_error "Failed to start Onyx services"
    exit 1
fi

# Monitor container startup
print_step "Verifying container health"
print_info "Waiting for containers to initialize (10 seconds)..."

# Progress bar for waiting
for i in {1..10}; do
    printf "\r[%-10s] %d%%" $(printf '#%.0s' $(seq 1 $((i*10/10)))) $((i*100/10))
    sleep 1
done
echo ""
echo ""

# Check for restart loops
print_info "Checking container health status..."
RESTART_ISSUES=false
CONTAINERS=$(cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD $(compose_file_args) ps -q 2>/dev/null)

for CONTAINER in $CONTAINERS; do
    PROJECT_NAME="$(basename "$INSTALL_ROOT")_deployment_"
    CONTAINER_NAME=$(docker inspect --format '{{.Name}}' "$CONTAINER" | sed "s/^\/\|^${PROJECT_NAME}//g")
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
    echo "  (cd \"${INSTALL_ROOT}/deployment\" && $COMPOSE_CMD $(compose_file_args) logs)"

    echo ""
    print_info "If the issue persists, please contact: founders@onyx.app"
    echo "Include the output of the logs command in your message."
    exit 1
fi

# Health check function
check_onyx_health() {
    local max_attempts=600  # 10 minutes * 60 attempts per minute (every 1 second)
    local attempt=1
    local port=${HOST_PORT:-3000}

    print_info "Checking Onyx service health..."
    echo "Containers are healthy, waiting for database migrations and service initialization to finish."
    echo ""

    while [ $attempt -le $max_attempts ]; do
        local http_code=""
        if [[ "$DOWNLOADER" == "curl" ]]; then
            http_code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port" 2>/dev/null || echo "000")
        else
            http_code=$(wget -q --spider -S "http://localhost:$port" 2>&1 | grep "HTTP/" | tail -1 | awk '{print $2}' || echo "000")
        fi
        if echo "$http_code" | grep -qE "^(200|301|302|303|307|308)$"; then
            return 0
        fi

        # Show animated progress with time elapsed
        local elapsed=$((attempt))
        local minutes=$((elapsed / 60))
        local seconds=$((elapsed % 60))

        # Create animated dots with fixed spacing (cycle through 1-3 dots)
        local dots=""
        case $((attempt % 3)) in
            0) dots=".  " ;;
            1) dots=".. " ;;
            2) dots="..." ;;
        esac

        # Clear line and show progress with fixed spacing
        printf "\r\033[KChecking Onyx service%s (%dm %ds elapsed)" "$dots" "$minutes" "$seconds"

        sleep 1
        attempt=$((attempt + 1))
    done

    echo ""  # New line after the progress line
    return 1
}

# Success message
print_step "Installation Complete!"
print_success "All containers are running successfully!"
echo ""

# Run health check
if check_onyx_health; then
    echo ""
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}${BOLD}   🎉 Onyx service is ready! 🎉${NC}"
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
else
    print_warning "Health check timed out after 10 minutes"
    print_info "Containers are running, but the web service may still be initializing (or something went wrong)"
    echo ""
    echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}${BOLD}   ⚠️  Onyx containers are running ⚠️${NC}"
    echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
fi
echo ""
print_info "Access Onyx at:"
echo -e "   ${BOLD}http://localhost:${HOST_PORT}${NC}"
echo ""
print_info "If authentication is enabled, you can create your admin account here:"
echo "   • Visit http://localhost:${HOST_PORT}/auth/signup to create your admin account"
echo "   • The first user created will automatically have admin privileges"
echo ""
if [[ "$LITE_MODE" = true ]]; then
    echo ""
    print_info "Running in Lite mode — the following services are NOT started:"
    echo "  • Vespa (vector database)"
    echo "  • Redis (cache)"
    echo "  • Model servers (embedding/inference)"
    echo "  • Background workers (Celery)"
    echo ""
    print_info "Connectors and RAG search are disabled. LLM chat, tools, user file"
    print_info "uploads, Projects, Agent knowledge, and code interpreter still work."
fi
echo ""
print_info "Refer to the README in the ${INSTALL_ROOT} directory for more information."
echo ""
print_info "For help or issues, contact: founders@onyx.app"
echo ""
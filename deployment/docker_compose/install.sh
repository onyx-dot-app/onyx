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
USE_LOCAL_FILES=false # Disabled by default, use --local to skip downloading config files
NO_PROMPT=false
DRY_RUN=false
VERBOSE=false
NO_WAIT=false  # When false (default), pass --wait to `docker compose up`
WAIT_TIMEOUT_SECONDS=600

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
        --local)
            USE_LOCAL_FILES=true
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
        --no-wait)
            NO_WAIT=true
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
            echo "  --local          Use existing config files instead of downloading from GitHub"
            echo "  --shutdown       Stop (pause) Onyx containers"
            echo "  --delete-data    Remove all Onyx data (containers, volumes, and files)"
            echo "  --no-prompt      Run non-interactively with defaults (for CI/automation)"
            echo "  --dry-run        Show what would be done without making changes"
            echo "  --verbose        Show detailed output for debugging"
            echo "  --no-wait        Skip 'docker compose up --wait'; return as soon as"
            echo "                   containers are started (they may still be initializing)"
            echo "  --help, -h       Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Install Onyx"
            echo "  $0 --lite             # Install Onyx Lite (minimal deployment)"
            echo "  $0 --include-craft    # Install Onyx with Craft enabled"
            echo "  $0 --shutdown         # Pause Onyx services"
            echo "  $0 --delete-data      # Completely remove Onyx and all data"
            echo "  $0 --local            # Re-run using existing config files on disk"
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
# after the resource check has already passed with the standard thresholds —
# which is the safer direction.
if [[ "$LITE_MODE" = true ]]; then
    EXPECTED_DOCKER_RAM_GB=4
    EXPECTED_DISK_GB=16
fi

INSTALL_ROOT="${INSTALL_PREFIX:-onyx_data}"

LITE_COMPOSE_FILE="docker-compose.onyx-lite.yml"
CRAFT_COMPOSE_FILE="docker-compose.craft.yml"

# Populate COMPOSE_FILE_ARGS with the -f flags for docker compose.
# Pass "true" as $1 to auto-detect previously-downloaded overlays (used by
# shutdown/delete-data so users don't need to remember --lite/--include-craft).
COMPOSE_FILE_ARGS=()
build_compose_file_args() {
    local auto_detect="${1:-false}"
    COMPOSE_FILE_ARGS=(-f docker-compose.yml)
    if [[ "$LITE_MODE" = true ]] || { [[ "$auto_detect" = true ]] && [[ -f "${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}" ]]; }; then
        COMPOSE_FILE_ARGS+=(-f "${LITE_COMPOSE_FILE}")
    fi
    # Craft Docker sandbox backend is opt-in (--include-craft) so the host
    # Docker socket isn't bind-mounted on default deployments. Layer the
    # craft overlay on top when explicitly enabled, or auto-detect a
    # previously-downloaded overlay on shutdown/delete-data.
    if [[ "$INCLUDE_CRAFT" = true ]] || { [[ "$auto_detect" = true ]] && [[ -f "${INSTALL_ROOT}/deployment/${CRAFT_COMPOSE_FILE}" ]]; }; then
        COMPOSE_FILE_ARGS+=(-f "${CRAFT_COMPOSE_FILE}")
    fi
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

# Fetches the most recent published release tag from the Onyx GitHub repo.
# Used to default the installer to a pinned, tested release (instead of the
# rolling "edge" tag) and to pull compose/nginx files that match it.
LATEST_RELEASE_TAG=""
fetch_latest_release_tag() {
    local api_url="https://api.github.com/repos/onyx-dot-app/onyx/releases/latest"
    local response=""
    if [[ "$DOWNLOADER" == "curl" ]]; then
        response=$(curl -fsSL --retry 2 --retry-delay 1 \
            --connect-timeout 5 --max-time 10 \
            -H "Accept: application/vnd.github+json" \
            "$api_url" 2>/dev/null) || return 1
    else
        response=$(wget -q --tries=2 --timeout=10 \
            --header="Accept: application/vnd.github+json" \
            -O- "$api_url" 2>/dev/null) || return 1
    fi
    local tag
    tag=$(echo "$response" \
        | grep -oE '"tag_name"[[:space:]]*:[[:space:]]*"[^"]+"' \
        | head -1 \
        | sed -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
    if [[ -z "$tag" ]]; then
        return 1
    fi
    LATEST_RELEASE_TAG="$tag"
    return 0
}

# --- Docker Compose detection ---
# Sets COMPOSE_CMD to "docker compose" (plugin) or "docker-compose" (standalone).
# Returns 0 if either is available, 1 otherwise. Safe to re-run after installing
# compose mid-script.
COMPOSE_CMD=""
detect_compose_cmd() {
    if docker compose version &> /dev/null; then
        COMPOSE_CMD="docker compose"
        return 0
    fi
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
        return 0
    fi
    COMPOSE_CMD=""
    return 1
}
detect_compose_cmd || true

# Ensures a required file is present. With --local, verifies the file exists on
# disk. Otherwise, downloads it from the given URL. Returns 0 on success, 1 on
# failure (caller should handle the exit).
ensure_file() {
    local path="$1"
    local url="$2"
    local desc="$3"

    if [[ "$USE_LOCAL_FILES" = true ]]; then
        if [[ -f "$path" ]]; then
            print_success "Using existing ${desc}"
            return 0
        fi
        print_error "Required file missing: ${desc} (${path})"
        return 1
    fi

    print_info "Downloading ${desc}..."
    if download_file "$url" "$path" 2>/dev/null; then
        print_success "${desc} downloaded"
        return 0
    fi
    print_error "Failed to download ${desc}"
    print_info "Please ensure you have internet connection and try again"
    return 1
}

# --- Interactive prompt helpers ---
is_interactive() {
    [[ "$NO_PROMPT" = false ]] && [[ -r /dev/tty ]] && [[ -w /dev/tty ]]
}

read_prompt_line() {
    local prompt_text="$1"
    if ! is_interactive; then
        REPLY=""
        return
    fi
    [[ -n "$prompt_text" ]] && printf "%s" "$prompt_text" > /dev/tty
    IFS= read -r REPLY < /dev/tty || REPLY=""
}

read_prompt_char() {
    local prompt_text="$1"
    if ! is_interactive; then
        REPLY=""
        return
    fi
    [[ -n "$prompt_text" ]] && printf "%s" "$prompt_text" > /dev/tty
    IFS= read -r -n 1 REPLY < /dev/tty || REPLY=""
    printf "\n" > /dev/tty
}

prompt_or_default() {
    local prompt_text="$1"
    local default_value="$2"
    read_prompt_line "$prompt_text"
    [[ -z "$REPLY" ]] && REPLY="$default_value"
    return 0
}

prompt_yn_or_default() {
    local prompt_text="$1"
    local default_value="$2"
    read_prompt_char "$prompt_text"
    [[ -z "$REPLY" ]] && REPLY="$default_value"
    return 0
}

confirm_action() {
    local description="$1"
    prompt_yn_or_default "Install ${description}? (Y/n) [default: Y] " "Y"
    if [[ "$REPLY" =~ ^[Nn] ]]; then
        print_warning "Skipping: ${description}"
        return 1
    fi
    return 0
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
TOTAL_STEPS=9

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
            if [[ -z "$COMPOSE_CMD" ]]; then
                print_error "Docker Compose not found. Cannot stop containers."
                exit 1
            fi

            # Stop containers (without removing them)
            build_compose_file_args true
            if (cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD "${COMPOSE_FILE_ARGS[@]}" stop); then
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
        prompt_or_default "Are you sure you want to continue? Type 'DELETE' to confirm: " ""
        echo "" > /dev/tty
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
            if [[ -z "$COMPOSE_CMD" ]]; then
                print_error "Docker Compose not found. Cannot remove containers."
                exit 1
            fi

            # Stop and remove containers with volumes
            build_compose_file_args true
            if (cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD "${COMPOSE_FILE_ARGS[@]}" down -v); then
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

# --- Auto-install Docker (Linux only) ---
# Runs before the banner so a group-based re-exec doesn't repeat it.
install_docker_linux() {
    local distro_id=""
    if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        distro_id="$(. /etc/os-release && echo "${ID:-}")"
    fi

    case "$distro_id" in
        amzn)
            print_info "Detected Amazon Linux — installing Docker via package manager..."
            if command -v dnf &> /dev/null; then
                sudo dnf install -y docker
            else
                sudo yum install -y docker
            fi
            ;;
        *)
            print_info "Installing Docker via get.docker.com..."
            download_file "https://get.docker.com" /tmp/get-docker.sh
            sudo sh /tmp/get-docker.sh
            rm -f /tmp/get-docker.sh
            ;;
    esac

    sudo systemctl start docker 2>/dev/null || sudo service docker start 2>/dev/null || true
    sudo systemctl enable docker 2>/dev/null || true
}

# Detect OS (including WSL)
IS_WSL=false
if [[ -n "${WSL_DISTRO_NAME:-}" ]] || grep -qi microsoft /proc/version 2>/dev/null; then
    IS_WSL=true
fi

# Resolve the git ref to pull deployment files from, and the default image tag
# to suggest at the version prompt. Both default to the most recent GitHub
# release so users land on a pinned, tested version. If the API is unreachable,
# fall back to main / edge (the pre-existing defaults).
RELEASE_REF="main"
DEFAULT_IMAGE_TAG="edge"
RELEASE_LOOKUP_FAILED=false
if [[ "$USE_LOCAL_FILES" = false ]]; then
    if fetch_latest_release_tag; then
        RELEASE_REF="$LATEST_RELEASE_TAG"
        DEFAULT_IMAGE_TAG="$LATEST_RELEASE_TAG"
    else
        RELEASE_LOOKUP_FAILED=true
    fi
fi

# Dry-run: show plan and exit
if [[ "$DRY_RUN" = true ]]; then
    print_info "Dry run mode — showing what would happen:"
    echo "  • Install root: ${INSTALL_ROOT}"
    echo "  • Lite mode: ${LITE_MODE}"
    echo "  • Include Craft: ${INCLUDE_CRAFT}"
    echo "  • OS type: ${OSTYPE:-unknown} (WSL: ${IS_WSL})"
    echo "  • Downloader: ${DOWNLOADER}"
    echo "  • Default image tag: ${DEFAULT_IMAGE_TAG} (config ref: ${RELEASE_REF})"
    echo ""
    print_success "Dry run complete (no changes made)"
    exit 0
fi

if ! command -v docker &> /dev/null; then
    if [[ "$OSTYPE" == "linux-gnu"* ]] || [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
        print_info "Docker is required but not installed."
        if ! confirm_action "Docker Engine"; then
            print_error "Docker is required to run Onyx."
            exit 1
        fi
        install_docker_linux
        if ! command -v docker &> /dev/null; then
            print_error "Docker installation failed."
            echo "  Visit: https://docs.docker.com/get-docker/"
            exit 1
        fi
        print_success "Docker installed successfully"
        # Compose plugin may ship with Docker — re-detect.
        detect_compose_cmd || true
    fi
fi

# --- Auto-install Docker Compose plugin (Linux only) ---
if command -v docker &> /dev/null \
    && [[ -z "$COMPOSE_CMD" ]] \
    && { [[ "$OSTYPE" == "linux-gnu"* ]] || [[ -n "${WSL_DISTRO_NAME:-}" ]]; }; then

    print_info "Docker Compose is required but not installed."
    if ! confirm_action "Docker Compose plugin"; then
        print_error "Docker Compose is required to run Onyx."
        exit 1
    fi
    COMPOSE_ARCH="$(uname -m)"
    COMPOSE_URL="https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${COMPOSE_ARCH}"
    COMPOSE_DIR="/usr/local/lib/docker/cli-plugins"
    COMPOSE_TMP="$(mktemp)"
    sudo mkdir -p "$COMPOSE_DIR"
    if download_file "$COMPOSE_URL" "$COMPOSE_TMP"; then
        sudo mv "$COMPOSE_TMP" "$COMPOSE_DIR/docker-compose"
        sudo chmod +x "$COMPOSE_DIR/docker-compose"
        if detect_compose_cmd && [[ "$COMPOSE_CMD" == "docker compose" ]]; then
            print_success "Docker Compose plugin installed"
        else
            print_error "Docker Compose plugin installed but not detected."
            echo "  Visit: https://docs.docker.com/compose/install/"
            exit 1
        fi
    else
        rm -f "$COMPOSE_TMP"
        print_error "Failed to download Docker Compose plugin."
        echo "  Visit: https://docs.docker.com/compose/install/"
        exit 1
    fi
fi

# On Linux, ensure the current user can talk to the Docker daemon without
# sudo.  If necessary, add them to the "docker" group and re-exec the
# script under that group so the rest of the install proceeds normally.
if command -v docker &> /dev/null \
    && { [[ "$OSTYPE" == "linux-gnu"* ]] || [[ -n "${WSL_DISTRO_NAME:-}" ]]; } \
    && [[ "$(id -u)" -ne 0 ]] \
    && ! docker info &> /dev/null; then
    if [[ "${_ONYX_REEXEC:-}" = "1" ]]; then
        print_error "Cannot connect to Docker after group re-exec."
        print_info "Log out and back in, then run the script again."
        exit 1
    fi
    if ! getent group docker &> /dev/null; then
        sudo groupadd docker
    fi
    print_info "Adding $USER to the docker group..."
    sudo usermod -aG docker "$USER"
    print_info "Re-launching with docker group active..."
    exec sg docker -c "_ONYX_REEXEC=1 bash $(printf '%q ' "$0" "$@")"
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

if [[ "$RELEASE_LOOKUP_FAILED" = true ]]; then
    print_warning "Could not determine latest Onyx release — falling back to main / edge"
fi

# User acknowledgment section
echo -e "${YELLOW}${BOLD}This script will:${NC}"
echo "1. Download deployment files for Onyx into a new '${INSTALL_ROOT}' directory"
echo "2. Check your system resources (Docker, memory, disk space)"
echo "3. Guide you through deployment options (version, authentication)"
echo ""

if is_interactive; then
    echo -e "${YELLOW}${BOLD}Please acknowledge and press Enter to continue...${NC}"
    read_prompt_line ""
    echo ""
else
    echo -e "${YELLOW}${BOLD}Running in non-interactive mode - proceeding automatically...${NC}"
    echo ""
fi

# GitHub repo base URL — pinned to the resolved release ref (latest release tag
# if reachable, otherwise main).
GITHUB_RAW_URL="https://raw.githubusercontent.com/onyx-dot-app/onyx/${RELEASE_REF}/deployment/docker_compose"

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
if [[ -z "$COMPOSE_CMD" ]]; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    echo "Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

if [[ "$COMPOSE_CMD" == "docker compose" ]]; then
    COMPOSE_VERSION=$($COMPOSE_CMD version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    COMPOSE_TYPE="plugin"
else
    COMPOSE_VERSION=$($COMPOSE_CMD --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    COMPOSE_TYPE="standalone"
fi
if [ -z "$COMPOSE_VERSION" ]; then
    # Handle non-standard versions like "dev" - assume recent enough
    COMPOSE_VERSION="dev"
    print_success "Docker Compose (dev build) is installed (${COMPOSE_TYPE})"
else
    print_success "Docker Compose $COMPOSE_VERSION is installed (${COMPOSE_TYPE})"
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
    if [[ "$OSTYPE" == "darwin"* ]]; then
        print_info "Docker daemon is not running. Starting Docker Desktop..."
        open -a Docker
        # Wait up to 120 seconds for Docker to be ready
        DOCKER_WAIT=0
        DOCKER_MAX_WAIT=120
        while ! docker info &> /dev/null; do
            if [ $DOCKER_WAIT -ge $DOCKER_MAX_WAIT ]; then
                print_error "Docker Desktop did not start within ${DOCKER_MAX_WAIT} seconds."
                print_info "Please start Docker Desktop manually and re-run this script."
                exit 1
            fi
            printf "\r\033[KWaiting for Docker Desktop to start... (%ds)" "$DOCKER_WAIT"
            sleep 2
            DOCKER_WAIT=$((DOCKER_WAIT + 2))
        done
        echo ""
        print_success "Docker Desktop is now running"
    else
        print_error "Docker daemon is not running. Please start Docker."
        exit 1
    fi
else
    print_success "Docker daemon is running"
fi

# Check Docker resources
print_step "Verifying Docker resources"

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
    MEMORY_GB=$(awk "BEGIN {printf \"%.1f\", $MEMORY_MB / 1024}")
    if [ "$(awk "BEGIN {print ($MEMORY_MB >= 1024)}")" = "1" ]; then
        MEMORY_DISPLAY="~${MEMORY_GB}GB"
    else
        MEMORY_DISPLAY="${MEMORY_MB}MB"
    fi
    if [[ "$OSTYPE" == "darwin"* ]]; then
        print_info "Docker memory allocation: ${MEMORY_DISPLAY}"
    else
        print_info "System memory: ${MEMORY_DISPLAY} (Docker uses host memory directly)"
    fi
else
    print_warning "Could not determine memory allocation"
    MEMORY_DISPLAY="unknown"
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
    print_warning "Less than ${EXPECTED_DOCKER_RAM_GB}GB RAM available (found: ${MEMORY_DISPLAY})"
    RESOURCE_WARNING=true
fi

if [ "$DISK_AVAILABLE" -lt "$EXPECTED_DISK_GB" ]; then
    print_warning "Less than ${EXPECTED_DISK_GB}GB disk space available (found: ${DISK_AVAILABLE}GB)"
    RESOURCE_WARNING=true
fi

if [ "$RESOURCE_WARNING" = true ]; then
    echo ""
    print_warning "Onyx recommends at least ${EXPECTED_DOCKER_RAM_GB}GB RAM and ${EXPECTED_DISK_GB}GB disk space for optimal performance in standard mode."
    print_warning "Lite mode requires less resources (1-4GB RAM, 8-16GB disk depending on usage), but does not include a vector database."
    echo ""
    prompt_yn_or_default "Do you want to continue anyway? (Y/n): " "y"
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
fi
mkdir -p "${INSTALL_ROOT}/deployment"
mkdir -p "${INSTALL_ROOT}/data/nginx/local"
print_success "Directory structure created"

# Ensure all required configuration files are present
NGINX_BASE_URL="https://raw.githubusercontent.com/onyx-dot-app/onyx/${RELEASE_REF}/deployment/data/nginx"

if [[ "$USE_LOCAL_FILES" = true ]]; then
    print_step "Verifying existing configuration files"
else
    print_step "Downloading Onyx configuration files"
    print_info "This step downloads all necessary configuration files from GitHub..."
fi

ensure_file "${INSTALL_ROOT}/deployment/docker-compose.yml" \
    "${GITHUB_RAW_URL}/docker-compose.yml" "docker-compose.yml" || exit 1

# Check Docker Compose version compatibility after obtaining docker-compose.yml
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
    prompt_yn_or_default "Do you want to continue anyway? (Y/n): " "y"
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Installation cancelled. Please upgrade Docker Compose or manually edit the docker-compose.yml file."
        exit 1
    fi
    print_info "Proceeding with installation despite Docker Compose version compatibility issues..."
fi

# Ask for deployment mode (standard vs lite) unless already set via --lite flag
if [[ "$LITE_MODE" = false ]]; then
    print_info "Which deployment mode would you like?"
    echo ""
    echo "  1) Lite      - Minimal deployment (no Vespa, Redis, or model servers)"
    echo "                  LLM chat, tools, file uploads, and Projects still work"
    echo "  2) Standard  - Full deployment with search, connectors, and RAG"
    echo ""
    prompt_or_default "Choose a mode (1 or 2) [default: 1]: " "1"
    echo ""

    case "$REPLY" in
        2)
            print_info "Selected: Standard mode"
            ;;
        *)
            LITE_MODE=true
            print_info "Selected: Lite mode"
            ;;
    esac
else
    print_info "Deployment mode: Lite (set via --lite flag)"
fi

if [[ "$LITE_MODE" = true ]] && [[ "$INCLUDE_CRAFT" = true ]]; then
    print_error "--include-craft cannot be used with Lite mode."
    print_info "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
    exit 1
fi

if [[ "$LITE_MODE" = true ]]; then
    EXPECTED_DOCKER_RAM_GB=4
    EXPECTED_DISK_GB=16
fi

# Handle lite overlay file based on selected mode
if [[ "$LITE_MODE" = true ]]; then
    ensure_file "${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}" \
        "${GITHUB_RAW_URL}/${LITE_COMPOSE_FILE}" "${LITE_COMPOSE_FILE}" || exit 1
elif [[ -f "${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}" ]]; then
    rm -f "${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}"
    print_info "Removed previous lite overlay (switching to standard mode)"
fi

# Handle craft overlay file based on selected mode. Keeps the Docker socket
# bind-mount out of the default file so non-Craft deployments never inherit
# it; only `--include-craft` (or an existing overlay from a prior install)
# adds it back.
if [[ "$INCLUDE_CRAFT" = true ]]; then
    ensure_file "${INSTALL_ROOT}/deployment/${CRAFT_COMPOSE_FILE}" \
        "${GITHUB_RAW_URL}/${CRAFT_COMPOSE_FILE}" "${CRAFT_COMPOSE_FILE}" || exit 1
elif [[ -f "${INSTALL_ROOT}/deployment/${CRAFT_COMPOSE_FILE}" ]]; then
    rm -f "${INSTALL_ROOT}/deployment/${CRAFT_COMPOSE_FILE}"
    print_info "Removed previous craft overlay (Craft disabled this run)"
fi

ensure_file "${INSTALL_ROOT}/deployment/env.template" \
    "${GITHUB_RAW_URL}/env.template" "env.template" || exit 1

ensure_file "${INSTALL_ROOT}/data/nginx/app.conf.template" \
    "$NGINX_BASE_URL/app.conf.template" "nginx/app.conf.template" || exit 1

ensure_file "${INSTALL_ROOT}/data/nginx/run-nginx.sh" \
    "$NGINX_BASE_URL/run-nginx.sh" "nginx/run-nginx.sh" || exit 1
chmod +x "${INSTALL_ROOT}/data/nginx/run-nginx.sh"

ensure_file "${INSTALL_ROOT}/README.md" \
    "${GITHUB_RAW_URL}/README.md" "README.md" || exit 1

touch "${INSTALL_ROOT}/data/nginx/local/.gitkeep"
print_success "All configuration files ready"

# Set up deployment configuration
print_step "Setting up deployment configs"
ENV_FILE="${INSTALL_ROOT}/deployment/.env"
ENV_TEMPLATE="${INSTALL_ROOT}/deployment/env.template"
# Check if services are already running
if [ -d "${INSTALL_ROOT}/deployment" ] && [ -f "${INSTALL_ROOT}/deployment/docker-compose.yml" ]; then
    build_compose_file_args true
    RUNNING_CONTAINERS=$(cd "${INSTALL_ROOT}/deployment" && $COMPOSE_CMD "${COMPOSE_FILE_ARGS[@]}" ps -q 2>/dev/null | wc -l)
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

if [ -f "$ENV_FILE" ]; then
    print_info "Existing .env file found. What would you like to do?"
    echo ""
    echo "• Press Enter to restart with current configuration"
    echo "• Type 'update' to update to a newer version"
    echo ""
    prompt_or_default "Choose an option [default: restart]: " ""
    echo ""

    if [ "$REPLY" = "update" ]; then
        if [ "$INCLUDE_CRAFT" = true ]; then
            # --include-craft requires the craft-tagged backend image (Node.js
            # + opencode CLI are only built into that image), so the tag is
            # forced rather than prompted for.
            VERSION="craft-latest"
            print_info "Update selected. Using craft-latest (required by --include-craft)."
        else
            print_info "Update selected. Which tag would you like to deploy?"
            echo ""
            echo "• Press Enter for ${DEFAULT_IMAGE_TAG} (recommended)"
            echo "• Type a specific tag (e.g., v0.1.0)"
            echo ""
            prompt_or_default "Enter tag [default: ${DEFAULT_IMAGE_TAG}]: " "${DEFAULT_IMAGE_TAG}"
            VERSION="$REPLY"
            echo ""

            if [ "$VERSION" = "edge" ]; then
                print_info "Selected: edge (latest nightly)"
            else
                print_info "Selected: $VERSION"
            fi
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
        print_success "Configuration updated for upgrade"
    else
        print_info "Keeping existing configuration..."
        print_success "Will restart with current settings"
    fi

    # Ensure COMPOSE_PROFILES is cleared when running in lite mode on an
    # existing .env (the template ships with s3-filestore enabled).
    if [[ "$LITE_MODE" = true ]] && grep -q "^COMPOSE_PROFILES=.*s3-filestore" "$ENV_FILE" 2>/dev/null; then
        sed -i.bak 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=/' "$ENV_FILE" 2>/dev/null || true
        print_success "Cleared COMPOSE_PROFILES for lite mode"
    fi
else
    print_info "No existing .env file found. Setting up new deployment..."
    echo ""

    # Ask for version (skipped when --include-craft forces the craft-tagged
    # backend image, which is the only image that ships Node.js + opencode CLI).
    if [ "$INCLUDE_CRAFT" = true ]; then
        VERSION="craft-latest"
        print_info "Using craft-latest (required by --include-craft)."
    else
        print_info "Which tag would you like to deploy?"
        echo ""
        echo "• Press Enter for ${DEFAULT_IMAGE_TAG} (recommended)"
        echo "• Type a specific tag (e.g., v0.1.0)"
        echo ""
        prompt_or_default "Enter tag [default: ${DEFAULT_IMAGE_TAG}]: " "${DEFAULT_IMAGE_TAG}"
        VERSION="$REPLY"
        echo ""

        if [ "$VERSION" = "edge" ]; then
            print_info "Selected: edge (latest nightly)"
        else
            print_info "Selected: $VERSION"
        fi
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
    # shellcheck disable=SC2034  # Referenced by the commented-out auth prompt above.
    AUTH_SCHEMA="basic"

    # Create .env file from template
    print_info "Creating .env file with your selections..."
    cp "$ENV_TEMPLATE" "$ENV_FILE"

    # Update IMAGE_TAG with selected version
    print_info "Setting IMAGE_TAG to $VERSION..."
    sed -i.bak "s/^IMAGE_TAG=.*/IMAGE_TAG=$VERSION/" "$ENV_FILE"
    print_success "IMAGE_TAG set to $VERSION"

    # In lite mode, clear COMPOSE_PROFILES so profiled services (MinIO, etc.)
    # stay disabled — the template ships with s3-filestore enabled by default.
    if [[ "$LITE_MODE" = true ]]; then
        sed -i.bak 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=/' "$ENV_FILE" 2>/dev/null || true
        print_success "Cleared COMPOSE_PROFILES for lite mode"
    fi

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

    # Configure Craft based on --include-craft.
    # By default, env.template has Craft commented out (disabled).
    if [ "$INCLUDE_CRAFT" = true ]; then
        # Set ENABLE_CRAFT=true for runtime configuration (handles commented and uncommented lines)
        sed -i.bak 's/^#* *ENABLE_CRAFT=.*/ENABLE_CRAFT=true/' "$ENV_FILE" 2>/dev/null || true
        # Ensure SANDBOX_BACKEND=docker is written explicitly (docker-compose
        # defaults to it already, but a literal entry in .env makes the
        # selection visible/auditable to operators).
        if grep -q "^#* *SANDBOX_BACKEND=" "$ENV_FILE"; then
            sed -i.bak 's/^#* *SANDBOX_BACKEND=.*/SANDBOX_BACKEND=docker/' "$ENV_FILE"
        else
            echo "SANDBOX_BACKEND=docker" >> "$ENV_FILE"
        fi
        print_success "Onyx Craft enabled (ENABLE_CRAFT=true, SANDBOX_BACKEND=docker)"

        # Pre-create the dedicated sandbox bridge. docker-compose references
        # it as external=true so it must exist before `compose up`.
        SANDBOX_NET="${SANDBOX_DOCKER_NETWORK:-onyx_craft_sandbox}"
        if ! docker network inspect "$SANDBOX_NET" >/dev/null 2>&1; then
            if docker network create "$SANDBOX_NET" >/dev/null 2>&1; then
                print_success "Created sandbox bridge network: $SANDBOX_NET"
            else
                print_warning "Could not create sandbox network $SANDBOX_NET — create it manually:"
                echo "    docker network create $SANDBOX_NET"
            fi
        fi

        # Trust boundary warning. api_server + background mount the host
        # Docker socket so they can drive sandbox containers. Anything that
        # can talk to that socket is effectively root on the host.
        echo ""
        print_warning "Craft + docker backend: api_server and background mount"
        print_warning "/var/run/docker.sock. Compromise of either container ="
        print_warning "root on the host. Only enable on hosts you fully control."
        print_warning "On EC2, require IMDSv2 (HttpTokens=required) so sandboxes"
        print_warning "cannot pull IAM credentials from the instance metadata service."
        echo ""
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
        if nc -z localhost "$port" 2>/dev/null; then
            return 1
        fi
        return 0
    # Fallback using curl/telnet approach
    elif command -v curl &> /dev/null; then
        # Try to connect with curl, if it fails, the port might be available
        if curl -s --max-time 1 --connect-timeout 1 "http://localhost:$port" >/dev/null 2>&1; then
            return 1
        fi
        return 0
    # Final fallback using lsof if available
    elif command -v lsof &> /dev/null; then
        # Check if any process is listening on the port
        if lsof -i ":$port" >/dev/null 2>&1; then
            return 1
        fi
        return 0
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

    while [ "$port" -le 65535 ]; do
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

# Determine if we're using a floating tag (edge, latest) that should force pull.
# Read IMAGE_TAG from .env file and remove any quotes or whitespace.
CURRENT_IMAGE_TAG=$(grep "^IMAGE_TAG=" "$ENV_FILE" | head -1 | cut -d'=' -f2 | tr -d ' "'"'"'')

if [ "$CURRENT_IMAGE_TAG" = "edge" ] || [ "$CURRENT_IMAGE_TAG" = "latest" ] || [[ "$CURRENT_IMAGE_TAG" == craft-* ]]; then
    USE_LATEST=true
    # Floating tags track main, so configs should come from main.
    CONFIG_REF="main"
    if [[ "$CURRENT_IMAGE_TAG" == craft-* ]]; then
        print_info "Using craft tag '$CURRENT_IMAGE_TAG' - will force pull and recreate containers"
    else
        print_info "Using '$CURRENT_IMAGE_TAG' tag - will force pull and recreate containers"
    fi
else
    USE_LATEST=false
    # Pinned release tags use their own ref so configs match the images.
    CONFIG_REF="$CURRENT_IMAGE_TAG"
fi

# The initial download pulled configs from RELEASE_REF (latest release, or main
# on fallback). If the chosen image tag wants configs from a different ref,
# re-fetch them so the compose file matches the images being pulled.
if [[ "$CONFIG_REF" != "$RELEASE_REF" ]] && [[ "$USE_LOCAL_FILES" = false ]]; then
    CONFIG_BASE="https://raw.githubusercontent.com/onyx-dot-app/onyx/${CONFIG_REF}/deployment"
    print_info "Fetching config files matching ${CONFIG_REF}..."
    if download_file "${CONFIG_BASE}/docker_compose/docker-compose.yml" "${INSTALL_ROOT}/deployment/docker-compose.yml" 2>/dev/null; then
        download_file "${CONFIG_BASE}/data/nginx/app.conf.template" "${INSTALL_ROOT}/data/nginx/app.conf.template" 2>/dev/null || true
        download_file "${CONFIG_BASE}/data/nginx/run-nginx.sh" "${INSTALL_ROOT}/data/nginx/run-nginx.sh" 2>/dev/null || true
        chmod +x "${INSTALL_ROOT}/data/nginx/run-nginx.sh"
        if [[ "$LITE_MODE" = true ]]; then
            download_file "${CONFIG_BASE}/docker_compose/${LITE_COMPOSE_FILE}" \
                "${INSTALL_ROOT}/deployment/${LITE_COMPOSE_FILE}" 2>/dev/null || true
        fi
        if [[ "$INCLUDE_CRAFT" = true ]]; then
            download_file "${CONFIG_BASE}/docker_compose/${CRAFT_COMPOSE_FILE}" \
                "${INSTALL_ROOT}/deployment/${CRAFT_COMPOSE_FILE}" 2>/dev/null || true
        fi
        print_success "Config files updated to match ${CONFIG_REF}"
    else
        print_warning "Ref ${CONFIG_REF} not found on GitHub — keeping configs from ${RELEASE_REF}"
    fi
fi

# Pull Docker images with reduced output
print_step "Pulling Docker images"
print_info "This may take several minutes depending on your internet connection..."
echo ""
print_info "Downloading Docker images (this may take a while)..."
# Pass IMAGE_TAG inline so the value the user picked at the prompt wins over
# any `export IMAGE_TAG=...` inherited from the caller's shell. Compose's
# substitution prefers shell env over .env, so without this an exported
# IMAGE_TAG in the user's shellrc would silently swap the images being pulled.
build_compose_file_args
if (cd "${INSTALL_ROOT}/deployment" && IMAGE_TAG="$CURRENT_IMAGE_TAG" $COMPOSE_CMD "${COMPOSE_FILE_ARGS[@]}" pull --quiet); then
    print_success "Docker images downloaded successfully"
else
    print_error "Failed to download Docker images"
    exit 1
fi

# Build the up flags. With --wait (default), Compose waits until every
# container with a healthcheck reports healthy before returning, and names any
# service that stays unhealthy past the timeout.
UP_WAIT_ARGS=()
if [[ "$NO_WAIT" = false ]]; then
    UP_WAIT_ARGS=(--wait --wait-timeout "${WAIT_TIMEOUT_SECONDS}")
fi

# Start services
print_step "Starting Onyx services"
print_info "Launching containers..."
if [[ "$NO_WAIT" = false ]]; then
    print_info "Waiting up to ${WAIT_TIMEOUT_SECONDS}s for all services to become healthy..."
fi
echo ""
UP_EXIT=0
if [ "$USE_LATEST" = true ]; then
    print_info "Force pulling latest images and recreating containers..."
    (cd "${INSTALL_ROOT}/deployment" && IMAGE_TAG="$CURRENT_IMAGE_TAG" $COMPOSE_CMD "${COMPOSE_FILE_ARGS[@]}" up -d --pull always --force-recreate "${UP_WAIT_ARGS[@]}") || UP_EXIT=$?
else
    (cd "${INSTALL_ROOT}/deployment" && IMAGE_TAG="$CURRENT_IMAGE_TAG" $COMPOSE_CMD "${COMPOSE_FILE_ARGS[@]}" up -d "${UP_WAIT_ARGS[@]}") || UP_EXIT=$?
fi
if [ $UP_EXIT -ne 0 ]; then
    print_error "Failed to start Onyx services"
    echo ""
    print_info "Current container status:"
    (cd "${INSTALL_ROOT}/deployment" && IMAGE_TAG="$CURRENT_IMAGE_TAG" $COMPOSE_CMD "${COMPOSE_FILE_ARGS[@]}" ps)
    echo ""
    print_info "Check the logs of any unhealthy service:"
    echo "  (cd \"${INSTALL_ROOT}/deployment\" && $COMPOSE_CMD ${COMPOSE_FILE_ARGS[*]} logs <service>)"
    echo ""
    print_info "If the issue persists, please contact: founders@onyx.app"
    exit 1
fi

# Success message
print_step "Installation Complete!"
echo ""
if [[ "$NO_WAIT" = false ]]; then
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}${BOLD}   🎉 Onyx service is ready! 🎉${NC}"
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
else
    echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}${BOLD}   ⚠️  Onyx containers started  ⚠️${NC}"
    echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    print_info "Services may still be initializing. Check status with:"
    echo "  (cd \"${INSTALL_ROOT}/deployment\" && $COMPOSE_CMD ${COMPOSE_FILE_ARGS[*]} ps)"
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

# --- GitHub star prompt (inspired by oh-my-codex) ---
# Only prompt in interactive mode and only if gh CLI is available.
# Uses the GitHub API directly (PUT /user/starred) like oh-my-codex.
if is_interactive && command -v gh &>/dev/null; then
    prompt_yn_or_default "Enjoying Onyx? Star the repo on GitHub? [Y/n] " "Y"
    if [[ ! "$REPLY" =~ ^[Nn] ]]; then
        if GH_PAGER='' gh api -X PUT /user/starred/onyx-dot-app/onyx < /dev/null >/dev/null 2>&1; then
            print_success "Thanks for the star!"
        else
            print_info "Star us at: https://github.com/onyx-dot-app/onyx"
        fi
    fi
fi

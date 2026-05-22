#!/bin/sh
# Setup Onyx Craft templates
# This script is called on container startup to ensure Craft templates are ready
# Set ENABLE_CRAFT=false to skip setup

# Check if Craft is disabled
if [ "$ENABLE_CRAFT" = "false" ] || [ "$ENABLE_CRAFT" = "False" ]; then
    echo "Onyx Craft is disabled (ENABLE_CRAFT=false), skipping template setup"
    exit 0
fi

set -e

# Verify opencode CLI is available (installed in Dockerfile)
if ! command -v opencode >/dev/null 2>&1; then
    echo "WARNING: opencode CLI is not available — creating stub template directories." >&2
    echo "Craft API endpoints will work but sandbox provisioning requires the full image." >&2
    CRAFT_BASE="/app/onyx/server/features/build/sandbox/kubernetes/docker"
    OUTPUTS_TEMPLATE_PATH="${OUTPUTS_TEMPLATE_PATH:-${CRAFT_BASE}/templates/outputs}"
    VENV_TEMPLATE_PATH="${VENV_TEMPLATE_PATH:-${CRAFT_BASE}/templates/venv}"
    mkdir -p "$OUTPUTS_TEMPLATE_PATH" "$VENV_TEMPLATE_PATH"
    exit 0
fi

CRAFT_BASE="/app/onyx/server/features/build/sandbox/kubernetes/docker"
# Use environment variables if set, otherwise use defaults
OUTPUTS_TEMPLATE_PATH="${OUTPUTS_TEMPLATE_PATH:-${CRAFT_BASE}/templates/outputs}"
VENV_TEMPLATE_PATH="${VENV_TEMPLATE_PATH:-${CRAFT_BASE}/templates/venv}"
WEB_TEMPLATE_PATH="${WEB_TEMPLATE_PATH:-${OUTPUTS_TEMPLATE_PATH}/web}"
REQUIREMENTS_PATH="${CRAFT_BASE}/initial-requirements.txt"

echo "Setting up Onyx Craft templates..."

# 1. Create Python venv template if it doesn't exist
if [ ! -d "$VENV_TEMPLATE_PATH" ] && [ -f "$REQUIREMENTS_PATH" ]; then
    echo "  Creating Python venv template (this may take 30-60 seconds)..."
    python -m venv "$VENV_TEMPLATE_PATH"
    "$VENV_TEMPLATE_PATH/bin/pip" install --upgrade pip -q
    "$VENV_TEMPLATE_PATH/bin/pip" install -q -r "$REQUIREMENTS_PATH"
    echo "  Python venv template created"
fi

# 2. Install web template deps (prefer npm in production; fall back to bun
#    for environments like the CI devcontainer that ship bun instead of Node).
if [ -d "$WEB_TEMPLATE_PATH" ]; then
    if command -v npm >/dev/null 2>&1; then
        WEB_INSTALL_CMD="npm install"
    elif command -v bun >/dev/null 2>&1; then
        WEB_INSTALL_CMD="bun install"
    else
        WEB_INSTALL_CMD=""
        echo "WARNING: neither npm nor bun available — skipping web template setup." >&2
    fi
    if [ -n "$WEB_INSTALL_CMD" ]; then
        # Always remove and reinstall to ensure correct architecture binaries
        if [ -d "${WEB_TEMPLATE_PATH}/node_modules" ]; then
            echo "  Removing existing node_modules..."
            rm -rf "${WEB_TEMPLATE_PATH}/node_modules"
        fi
        echo "  Installing web template packages with '${WEB_INSTALL_CMD}' (this may take 1-2 minutes)..."
        cd "$WEB_TEMPLATE_PATH" && $WEB_INSTALL_CMD 2>&1 || { echo "ERROR: ${WEB_INSTALL_CMD} failed" >&2; exit 1; }
        echo "  Web template dependencies installed"
    fi
fi

echo "Craft template setup complete"

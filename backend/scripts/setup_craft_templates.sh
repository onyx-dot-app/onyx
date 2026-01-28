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
    echo "ERROR: opencode CLI is not available but ENABLE_CRAFT is enabled." >&2
    echo "opencode is required for Craft agent functionality. Ensure you are using Dockerfile" >&2
    echo "which includes the opencode CLI, or set ENABLE_CRAFT=false to disable Craft." >&2
    exit 1
fi

CRAFT_BASE="/app/onyx/server/features/build/sandbox/kubernetes/docker"
DEMO_DATA_ZIP="${CRAFT_BASE}/demo_data.zip"
DEMO_DATA_DIR="${CRAFT_BASE}/demo_data"
# Use environment variables if set, otherwise use defaults
OUTPUTS_TEMPLATE_PATH="${OUTPUTS_TEMPLATE_PATH:-${CRAFT_BASE}/templates/outputs}"
VENV_TEMPLATE_PATH="${VENV_TEMPLATE_PATH:-${CRAFT_BASE}/templates/venv}"
WEB_TEMPLATE_PATH="${WEB_TEMPLATE_PATH:-${OUTPUTS_TEMPLATE_PATH}/web}"
REQUIREMENTS_PATH="${CRAFT_BASE}/initial-requirements.txt"

echo "Setting up Onyx Craft templates..."

# 1. Unzip demo_data.zip if demo_data directory doesn't exist
if [ ! -d "$DEMO_DATA_DIR" ] && [ -f "$DEMO_DATA_ZIP" ]; then
    echo "  Extracting demo data..."
    cd "$CRAFT_BASE" && unzip -q demo_data.zip || { echo "ERROR: Failed to extract demo data" >&2; exit 1; }
    echo "  Demo data extracted"
fi

# 2. Create Python venv template if it doesn't exist
if [ ! -d "$VENV_TEMPLATE_PATH" ] && [ -f "$REQUIREMENTS_PATH" ]; then
    echo "  Creating Python venv template (this may take 30-60 seconds)..."
    python -m venv "$VENV_TEMPLATE_PATH"
    "$VENV_TEMPLATE_PATH/bin/pip" install --upgrade pip -q
    "$VENV_TEMPLATE_PATH/bin/pip" install -q -r "$REQUIREMENTS_PATH"
    echo "  Python venv template created"
fi

# 3. Run npm install in web template
if [ -d "$WEB_TEMPLATE_PATH" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "ERROR: npm is not available but ENABLE_CRAFT is enabled." >&2
        echo "npm is required for Craft web features. Ensure you are using Dockerfile" >&2
        echo "which includes Node.js, or set ENABLE_CRAFT=false to disable Craft." >&2
        exit 1
    fi
    # Always remove and reinstall to ensure correct architecture binaries
    if [ -d "${WEB_TEMPLATE_PATH}/node_modules" ]; then
        echo "  Removing existing node_modules..."
        rm -rf "${WEB_TEMPLATE_PATH}/node_modules"
    fi
    echo "  Installing npm packages (this may take 1-2 minutes)..."
    cd "$WEB_TEMPLATE_PATH" && npm install 2>&1 || { echo "ERROR: npm install failed" >&2; exit 1; }
    echo "  Web template dependencies installed"
fi

echo "Craft template setup complete"

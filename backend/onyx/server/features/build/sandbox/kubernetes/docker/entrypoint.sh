#!/bin/bash
# Sandbox Container Entrypoint
#
# Starts both services required for the sandbox:
# 1. Next.js dev server (port 3000) - for live preview
# 2. OpenCode ACP server (port 8081) - for agent communication
#
# Environment variables:
# - OPENCODE_CONFIG: JSON config for opencode (provider, model, apiKey, etc.)

set -e

echo "Starting sandbox services..."

# Generate AGENTS.md from template + scanned files
# This runs AFTER the init container has synced files from S3
echo "Generating AGENTS.md..."
python3 /usr/local/bin/generate_agents_md.py

# Change to the outputs/web directory for Next.js
cd /workspace/outputs/web

# Remove node_modules and .next to fix permissions
# (init container may copy files with wrong permissions)
if [ -d "node_modules" ]; then
    echo "Removing node_modules (fixing permissions)..."
    rm -rf node_modules
fi
if [ -d ".next" ]; then
    echo "Removing .next cache..."
    rm -rf .next
fi
echo "Installing npm dependencies..."
npm install

# Start Next.js dev server in background using npx to ensure PATH resolution
echo "Starting Next.js dev server on port 3000..."
npx next dev &
NEXTJS_PID=$!

# Give Next.js a moment to start
sleep 2

# Keep container running
# The manager runs `opencode acp` via kubectl exec when needed
echo "Container ready. Waiting for commands..."
cd /workspace
exec tail -f /dev/null

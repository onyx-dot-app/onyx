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

# Give Next.js a moment to start
sleep 2

# Keep container running
# The manager runs `opencode acp` via kubectl exec when needed
echo "Container ready. Waiting for commands..."
cd /workspace
exec tail -f /dev/null

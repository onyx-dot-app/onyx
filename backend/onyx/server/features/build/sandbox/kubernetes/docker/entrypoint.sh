#!/bin/bash
set -e

echo "=== Sandbox Container Starting ==="
echo "Session ID: ${SESSION_ID:-not set}"

# Setup workspace if outputs directory is empty (first run, no snapshot)
if [ ! -f "/workspace/outputs/web/package.json" ]; then
    echo "Outputs directory empty, copying from template..."
    if [ -d "/workspace/outputs-template" ]; then
        cp -r /workspace/outputs-template/* /workspace/outputs/ 2>/dev/null || true
        echo "Template copied successfully"
    else
        echo "WARNING: No template available and outputs directory is empty"
    fi
fi

# Copy AGENTS.md from ConfigMap mount if available
if [ -f "/workspace/instructions/AGENTS.md" ]; then
    cp /workspace/instructions/AGENTS.md /workspace/outputs/AGENTS.md 2>/dev/null || true
    echo "AGENTS.md copied from instructions"
fi

# Write opencode configuration from environment variable
if [ -n "$OPENCODE_CONFIG" ]; then
    echo "Writing opencode configuration..."
    echo "$OPENCODE_CONFIG" > /workspace/outputs/opencode.json
fi

# Ensure node_modules are installed in web directory
cd /workspace/outputs/web
if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm ci --silent 2>&1 || npm install --silent 2>&1
fi

echo "=== Starting Services ==="

# Function to cleanup on exit
cleanup() {
    echo "Received shutdown signal, cleaning up..."
    if [ -n "$NEXTJS_PID" ]; then
        kill $NEXTJS_PID 2>/dev/null || true
    fi
    if [ -n "$AGENT_PID" ]; then
        kill $AGENT_PID 2>/dev/null || true
    fi
    exit 0
}

# Trap signals for graceful shutdown
trap cleanup SIGTERM SIGINT SIGQUIT

# Start Next.js dev server in background
echo "Starting Next.js dev server on port 3000..."
cd /workspace/outputs/web
npm run dev &
NEXTJS_PID=$!
echo "Next.js started with PID $NEXTJS_PID"

# Wait a moment for Next.js to initialize
sleep 3

# Start opencode ACP HTTP server
echo "Starting OpenCode ACP server on port 8081..."
cd /workspace/outputs

# Check if opencode is available
if command -v opencode &> /dev/null; then
    # Start opencode in serve mode (HTTP-based ACP)
    opencode serve --port 8081 --cwd /workspace/outputs &
    AGENT_PID=$!
    echo "OpenCode agent started with PID $AGENT_PID"
else
    echo "WARNING: opencode binary not found, agent features will not work"
    # Create a simple health endpoint as fallback
    while true; do
        echo -e "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"agent_unavailable\"}" | nc -l -p 8081 -q 1 2>/dev/null || sleep 1
    done &
    AGENT_PID=$!
fi

echo "=== Services Running ==="
echo "Next.js: http://localhost:3000"
echo "Agent: http://localhost:8081"

# Wait for any process to exit
wait -n $NEXTJS_PID $AGENT_PID

# If we get here, one of the processes died
EXIT_CODE=$?
echo "A process exited with code $EXIT_CODE"

# Kill the other process
cleanup

exit $EXIT_CODE

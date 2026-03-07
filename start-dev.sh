#!/bin/bash
# Local development startup script

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Load environment
export $(cat .env.development | xargs)

echo "🚀 Starting HOP development environment..."
echo ""
echo "Make sure you have 4 terminal windows ready:"
echo "1. Backend API: source .venv/bin/activate && cd backend && uvicorn onyx.main:app --reload --port 8080"
echo "2. Model Server: source .venv/bin/activate && cd backend && uvicorn model_server.main:app --reload --port 9000"
echo "3. Background Jobs: source .venv/bin/activate && cd backend && python ./scripts/dev_run_background_jobs.py"
echo "4. Frontend: cd web && npm run dev"
echo ""
echo "Or run this script again with --all to start everything in one go (requires tmux)"
echo ""

if [ "$1" = "--check" ]; then
    echo "✓ Checking environment..."

    echo -n "Docker services... "
    if docker ps | grep -q hop-relational_db-1; then
        echo "✓"
    else
        echo "✗ (Run: cd deployment/docker_compose && docker compose up -d)"
        exit 1
    fi

    echo -n "Python venv... "
    if [ -d ".venv" ]; then
        echo "✓"
    else
        echo "✗"
        exit 1
    fi

    echo -n "Backend dependencies... "
    if source .venv/bin/activate && python -c "import fastapi" 2>/dev/null; then
        echo "✓"
    else
        echo "✗"
        exit 1
    fi

    echo -n "Frontend dependencies... "
    if [ -d "web/node_modules" ]; then
        echo "✓"
    else
        echo "✗"
        exit 1
    fi

    echo ""
    echo "✓ All systems ready! Start the 4 servers as shown above."
fi

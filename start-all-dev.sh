#!/bin/bash

################################################################################
# HOP Local Development Startup Script
#
# This script starts all 4 development servers in the correct order with
# proper timing delays to ensure services are fully initialized.
#
# Usage: ./start-all-dev.sh [--simple]
#        --simple : Use background processes instead of tmux
################################################################################

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Load environment
if [ -f ".env.development" ]; then
    export $(cat .env.development | grep -v '^#' | grep -v '^$' | xargs)
else
    echo -e "${RED}✗ .env.development not found${NC}"
    exit 1
fi

# Check prerequisites
check_prerequisites() {
    echo -e "${BLUE}Checking prerequisites...${NC}"

    local all_good=true

    # Check Docker services
    echo -n "  Docker services (PostgreSQL, Redis, Vespa, MinIO)... "
    if docker ps 2>/dev/null | grep -q "hop-relational_db-1"; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        echo "    Run: cd deployment/docker_compose && docker compose up -d"
        all_good=false
    fi

    # Check venv
    echo -n "  Python virtual environment... "
    if [ -d ".venv" ]; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        all_good=false
    fi

    # Check backend dependencies
    echo -n "  Backend dependencies... "
    if source .venv/bin/activate && python -c "import fastapi" 2>/dev/null; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        all_good=false
    fi

    # Check frontend dependencies
    echo -n "  Frontend dependencies... "
    if [ -d "web/node_modules" ]; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        all_good=false
    fi

    if [ "$all_good" = false ]; then
        echo -e "${RED}\n✗ Missing prerequisites. See errors above.${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓ All prerequisites met${NC}\n"
}

# Use simple background process mode (no tmux)
start_simple_mode() {
    echo -e "${YELLOW}Starting services in simple mode (background processes)${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}\n"

    source .venv/bin/activate

    # Create a temporary directory for PIDs
    local pid_dir="/tmp/hop_dev_$$"
    mkdir -p "$pid_dir"

    # Trap to cleanup all processes
    trap "cleanup_simple" EXIT INT TERM

    cleanup_simple() {
        echo -e "\n${YELLOW}Stopping all services...${NC}"

        for pid_file in "$pid_dir"/*.pid; do
            if [ -f "$pid_file" ]; then
                local pid=$(cat "$pid_file")
                local service=$(basename "$pid_file" .pid)
                if kill -0 "$pid" 2>/dev/null; then
                    echo -e "  Stopping $service (PID $pid)..."
                    kill "$pid" 2>/dev/null || true
                fi
            fi
        done

        rm -rf "$pid_dir"
        echo -e "${GREEN}✓ All services stopped${NC}"
    }

    # Start Model Server
    echo -e "${BLUE}[1/4] Starting Model Server on port 9000...${NC}"
    (
        cd backend
        uvicorn model_server.main:app --reload --port 9000
    ) > "$PROJECT_ROOT/logs/model_server.log" 2>&1 &
    echo $! > "$pid_dir/model_server.pid"
    sleep 5

    if kill -0 $(cat "$pid_dir/model_server.pid") 2>/dev/null; then
        echo -e "${GREEN}✓ Model Server started (PID: $(cat "$pid_dir/model_server.pid"))${NC}\n"
    else
        echo -e "${RED}✗ Model Server failed to start${NC}"
        cat "$PROJECT_ROOT/logs/model_server.log"
        exit 1
    fi

    # Start Backend API
    echo -e "${BLUE}[2/4] Starting Backend API on port 8080...${NC}"
    (
        cd backend
        uvicorn onyx.main:app --reload --port 8080
    ) > "$PROJECT_ROOT/logs/backend_api.log" 2>&1 &
    echo $! > "$pid_dir/backend_api.pid"
    sleep 8

    if kill -0 $(cat "$pid_dir/backend_api.pid") 2>/dev/null; then
        echo -e "${GREEN}✓ Backend API started (PID: $(cat "$pid_dir/backend_api.pid"))${NC}\n"
    else
        echo -e "${RED}✗ Backend API failed to start${NC}"
        cat "$PROJECT_ROOT/logs/backend_api.log"
        exit 1
    fi

    # Start Background Jobs
    echo -e "${BLUE}[3/4] Starting Background Jobs Worker...${NC}"
    (
        cd backend
        python ./scripts/dev_run_background_jobs.py
    ) > "$PROJECT_ROOT/logs/background_jobs.log" 2>&1 &
    echo $! > "$pid_dir/background_jobs.pid"
    sleep 5

    if kill -0 $(cat "$pid_dir/background_jobs.pid") 2>/dev/null; then
        echo -e "${GREEN}✓ Background Jobs started (PID: $(cat "$pid_dir/background_jobs.pid"))${NC}\n"
    else
        echo -e "${RED}✗ Background Jobs failed to start${NC}"
        cat "$PROJECT_ROOT/logs/background_jobs.log"
        exit 1
    fi

    # Start Frontend
    echo -e "${BLUE}[4/4] Starting Frontend on port 3000...${NC}"
    (
        cd web
        npm run dev
    ) > "$PROJECT_ROOT/logs/frontend.log" 2>&1 &
    echo $! > "$pid_dir/frontend.pid"
    sleep 5

    if kill -0 $(cat "$pid_dir/frontend.pid") 2>/dev/null; then
        echo -e "${GREEN}✓ Frontend started (PID: $(cat "$pid_dir/frontend.pid"))${NC}\n"
    else
        echo -e "${RED}✗ Frontend failed to start${NC}"
        cat "$PROJECT_ROOT/logs/frontend.log"
        exit 1
    fi

    # All services started
    echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}✓ All services started successfully!${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}\n"

    echo -e "${YELLOW}Service Status:${NC}"
    echo -e "  Model Server:      ${GREEN}http://localhost:9000${NC} (PID: $(cat "$pid_dir/model_server.pid"))"
    echo -e "  Backend API:       ${GREEN}http://localhost:8080${NC} (PID: $(cat "$pid_dir/backend_api.pid"))"
    echo -e "  Background Jobs:   ${GREEN}Running${NC} (PID: $(cat "$pid_dir/background_jobs.pid"))"
    echo -e "  Frontend:          ${GREEN}http://localhost:3000${NC} (PID: $(cat "$pid_dir/frontend.pid"))\n"

    echo -e "${YELLOW}Logs Location:${NC}"
    echo -e "  Model Server:      $PROJECT_ROOT/logs/model_server.log"
    echo -e "  Backend API:       $PROJECT_ROOT/logs/backend_api.log"
    echo -e "  Background Jobs:   $PROJECT_ROOT/logs/background_jobs.log"
    echo -e "  Frontend:          $PROJECT_ROOT/logs/frontend.log\n"

    echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}\n"

    # Wait for all processes
    wait
}

# Use tmux mode (if available)
start_tmux_mode() {
    # Check if tmux is installed
    if ! command -v tmux &> /dev/null; then
        echo -e "${YELLOW}tmux not found. Use --simple flag or install tmux.${NC}"
        start_simple_mode
        return
    fi

    local session_name="hop_dev_$$"

    # Trap to cleanup tmux session
    trap "cleanup_tmux" EXIT INT TERM

    cleanup_tmux() {
        echo -e "\n${YELLOW}Stopping tmux session...${NC}"
        tmux kill-session -t "$session_name" 2>/dev/null || true
        echo -e "${GREEN}✓ Tmux session stopped${NC}"
    }

    echo -e "${YELLOW}Starting services in tmux mode${NC}"
    echo -e "${YELLOW}Session: $session_name${NC}\n"

    # Create tmux session
    tmux new-session -d -s "$session_name" -x 200 -y 50

    # Create windows for each service
    tmux new-window -t "$session_name" -n "model-server"
    tmux new-window -t "$session_name" -n "backend-api"
    tmux new-window -t "$session_name" -n "background-jobs"
    tmux new-window -t "$session_name" -n "frontend"

    # Kill default window
    tmux kill-window -t "$session_name:0"

    # Start Model Server
    echo -e "${BLUE}[1/4] Starting Model Server...${NC}"
    tmux send-keys -t "$session_name:0" "source .venv/bin/activate && export \$(cat .env.development | grep -v '^#' | grep -v '^$' | xargs) && cd $PROJECT_ROOT/backend && uvicorn model_server.main:app --reload --port 9000" Enter
    sleep 5
    echo -e "${GREEN}✓ Model Server starting${NC}"

    # Start Backend API
    echo -e "${BLUE}[2/4] Starting Backend API...${NC}"
    tmux send-keys -t "$session_name:1" "source .venv/bin/activate && export \$(cat .env.development | grep -v '^#' | grep -v '^$' | xargs) && cd $PROJECT_ROOT/backend && uvicorn onyx.main:app --reload --port 8080" Enter
    sleep 8
    echo -e "${GREEN}✓ Backend API starting${NC}"

    # Start Background Jobs
    echo -e "${BLUE}[3/4] Starting Background Jobs...${NC}"
    tmux send-keys -t "$session_name:2" "source .venv/bin/activate && export \$(cat .env.development | grep -v '^#' | grep -v '^$' | xargs) && cd $PROJECT_ROOT/backend && python ./scripts/dev_run_background_jobs.py" Enter
    sleep 5
    echo -e "${GREEN}✓ Background Jobs starting${NC}"

    # Start Frontend
    echo -e "${BLUE}[4/4] Starting Frontend...${NC}"
    tmux send-keys -t "$session_name:3" "cd $PROJECT_ROOT/web && npm run dev" Enter
    sleep 5
    echo -e "${GREEN}✓ Frontend starting${NC}"

    # Print status
    echo -e "\n${GREEN}════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}✓ All services started in tmux session!${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}\n"

    echo -e "${YELLOW}Tmux Commands:${NC}"
    echo -e "  View all windows:  tmux list-windows -t $session_name"
    echo -e "  Switch windows:    tmux select-window -t $session_name:0  (0-3)"
    echo -e "  Attach to session: tmux attach -t $session_name"
    echo -e "  Kill session:      tmux kill-session -t $session_name\n"

    echo -e "${YELLOW}Services:${NC}"
    echo -e "  Model Server:  ${GREEN}http://localhost:9000${NC}"
    echo -e "  Backend API:   ${GREEN}http://localhost:8080${NC}"
    echo -e "  Frontend:      ${GREEN}http://localhost:3000${NC}\n"

    # Attach to the tmux session
    tmux attach -t "$session_name"
}

# Create logs directory
mkdir -p "$PROJECT_ROOT/logs"

# Check arguments
case "${1:-}" in
    --simple)
        check_prerequisites
        start_simple_mode
        ;;
    --tmux)
        check_prerequisites
        start_tmux_mode
        ;;
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --tmux       Start services in tmux windows (default if tmux available)"
        echo "  --simple     Start services as background processes"
        echo "  --help       Show this help message"
        echo ""
        echo "If no option is provided, will try tmux first, fall back to simple mode."
        ;;
    *)
        check_prerequisites
        # Default: try tmux, fall back to simple
        if command -v tmux &> /dev/null; then
            start_tmux_mode
        else
            start_simple_mode
        fi
        ;;
esac

#!/usr/bin/env bash

set -euo pipefail

ONYX_ZED_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ONYX_ZED_ROOT
readonly ONYX_ZED_WEB_ENV_FILE="${ONYX_ZED_ROOT}/.vscode/.env.web"
readonly ONYX_ZED_COMPOSE_FILE="${ONYX_ZED_ROOT}/.zed/process-compose.k8s.yaml"
readonly ONYX_ZED_CONTROL_PORT=18080
readonly ONYX_ZED_API_PORT=8080
readonly ONYX_ZED_WEB_PORT=3000

ONYX_ZED_STACK_STARTED=false
ONYX_ZED_INTERCEPT_FILE=""
ONYX_ZED_CLEANING_UP=false
ONYX_ZED_PROCESS_TREE_PIDS=()

require_command() {
  local command_name="$1"
  local installation_hint="$2"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "error: ${command_name} was not found; ${installation_hint}" >&2
    exit 1
  fi
}

require_file() {
  local file_path="$1"
  local creation_hint="$2"

  if [[ ! -f "$file_path" ]]; then
    echo "error: ${file_path} was not found; ${creation_hint}" >&2
    exit 1
  fi
}

listener_pids() {
  local port="$1"

  lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
}

process_command() {
  local pid="$1"

  ps -p "$pid" -o command= 2>/dev/null || true
}

is_managed_process_compose() {
  local pid="$1"
  local command

  command="$(process_command "$pid")"
  [[ "$command" == *"process-compose"* ]] &&
    [[ "$command" == *"--port ${ONYX_ZED_CONTROL_PORT}"* ]] &&
    [[ "$command" == *"--config ${ONYX_ZED_COMPOSE_FILE}"* ]]
}

collect_process_tree() {
  local root_pid="$1"
  local child_pid

  if ! kill -0 "$root_pid" 2>/dev/null; then
    return
  fi

  ONYX_ZED_PROCESS_TREE_PIDS+=("$root_pid")
  while IFS= read -r child_pid; do
    [[ -n "$child_pid" ]] && collect_process_tree "$child_pid"
  done < <(pgrep -P "$root_pid" 2>/dev/null || true)
}

terminate_process_trees() {
  local root_pid
  local pid
  local remaining_pids=()

  ONYX_ZED_PROCESS_TREE_PIDS=()
  for root_pid in "$@"; do
    collect_process_tree "$root_pid"
  done

  if [[ "${#ONYX_ZED_PROCESS_TREE_PIDS[@]}" -eq 0 ]]; then
    return
  fi

  kill -TERM "${ONYX_ZED_PROCESS_TREE_PIDS[@]}" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    remaining_pids=()
    for pid in "${ONYX_ZED_PROCESS_TREE_PIDS[@]}"; do
      kill -0 "$pid" 2>/dev/null && remaining_pids+=("$pid")
    done
    [[ "${#remaining_pids[@]}" -eq 0 ]] && return
    sleep 1
  done

  kill -KILL "${remaining_pids[@]}" 2>/dev/null || true
}

# Bound cleanup commands without macOS `timeout`. Ignore failures; return 124 on timeout.
run_bounded() {
  local deadline_seconds="$1"
  shift

  local bounded_pid
  "$@" >/dev/null 2>&1 &
  bounded_pid="$!"

  local _
  for _ in $(seq 1 "$deadline_seconds"); do
    if ! kill -0 "$bounded_pid" 2>/dev/null; then
      wait "$bounded_pid" 2>/dev/null || true
      return 0
    fi
    sleep 1
  done

  terminate_process_trees "$bounded_pid"
  wait "$bounded_pid" 2>/dev/null || true
  return 124
}

request_process_compose_down() {
  run_bounded 5 process-compose --port "$ONYX_ZED_CONTROL_PORT" down || true
}

assert_port_available() {
  local port="$1"
  local purpose="$2"
  local pid
  local command
  local occupied=false

  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    occupied=true
    command="$(process_command "$pid")"
    echo "error: port ${port} (${purpose}) is owned by PID ${pid}: ${command}" >&2
  done < <(listener_pids "$port")

  if [[ "$occupied" == true ]]; then
    echo "error: refusing to stop a process that was not started by this worktree" >&2
    return 1
  fi
}

stop_managed_stack() {
  local pid
  local control_listener_pids=()

  while IFS= read -r pid; do
    [[ -n "$pid" ]] && control_listener_pids+=("$pid")
  done < <(listener_pids "$ONYX_ZED_CONTROL_PORT")

  # Bash 3.2 requires a count check before expanding empty arrays under set -u.
  if [[ "${#control_listener_pids[@]}" -gt 0 ]]; then
    for pid in "${control_listener_pids[@]}"; do
      if ! is_managed_process_compose "$pid"; then
        echo "error: port ${ONYX_ZED_CONTROL_PORT} is owned by an unrelated process:" >&2
        echo "       PID ${pid}: $(process_command "$pid")" >&2
        return 1
      fi
    done

    echo "==> stopping the existing Onyx Process Compose stack"
    request_process_compose_down
    terminate_process_trees "${control_listener_pids[@]}"
  fi

  assert_port_available "$ONYX_ZED_CONTROL_PORT" "Process Compose control server"
  assert_port_available "$ONYX_ZED_API_PORT" "Onyx API"
}

cleanup() {
  if [[ "$ONYX_ZED_CLEANING_UP" == true ]]; then
    return
  fi
  ONYX_ZED_CLEANING_UP=true

  trap - EXIT INT TERM
  if [[ "$ONYX_ZED_STACK_STARTED" == true ]]; then
    stop_managed_stack || true
  fi
  if [[ -n "$ONYX_ZED_INTERCEPT_FILE" ]]; then
    if [[ -s "$ONYX_ZED_INTERCEPT_FILE" ]]; then
      run_bounded 10 telepresence leave "$(cat "$ONYX_ZED_INTERCEPT_FILE")" || true
    fi
    rm -f "$ONYX_ZED_INTERCEPT_FILE"
  fi
}

require_command process-compose "install it with 'brew install f1bonacc1/tap/process-compose'"
require_command telepresence "install Telepresence before using the local kind cluster"
require_command lsof "install lsof before starting local services"

if [[ "${1:-}" == "--stop" ]]; then
  if [[ "$#" -gt 1 ]]; then
    echo "error: --stop does not accept additional arguments" >&2
    exit 1
  fi
  stop_managed_stack
  run_bounded 10 telepresence leave onyx-api-server || true
  echo "==> Onyx local services stopped"
  exit 0
fi

if [[ "$#" -gt 0 ]]; then
  echo "error: unsupported argument: $1" >&2
  exit 1
fi

require_command bun "install Bun before starting the web server"
require_command make "install Make before starting local services"
require_command kubectl "install kubectl before using the local kind cluster"
require_file "$ONYX_ZED_WEB_ENV_FILE" "run make craft-up to create the web environment file"
require_file "${ONYX_ZED_ROOT}/.venv/bin/python" "run 'uv sync --frozen' from the repository root"

if ! kubectl config get-contexts kind-onyx-dev -o name >/dev/null 2>&1; then
  echo "error: kubectl context kind-onyx-dev was not found; run make craft-up first" >&2
  exit 1
fi

mkdir -p "${ONYX_ZED_ROOT}/.zed/logs"

stop_managed_stack
assert_port_available "$ONYX_ZED_WEB_PORT" "Onyx web server"

ONYX_ZED_INTERCEPT_FILE="$(mktemp)"
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "==> preparing the API intercept (with stale-agent recovery)"
make -C "$ONYX_ZED_ROOT" craft-intercept CLUSTER_NAME=onyx-dev NAMESPACE=onyx \
  INTERCEPT_ARGS="--ownership-file '$ONYX_ZED_INTERCEPT_FILE'"

process_compose_args=(
  --port "$ONYX_ZED_CONTROL_PORT"
  --ordered-shutdown
  --disable-dotenv
  --config "$ONYX_ZED_COMPOSE_FILE"
)

if [[ -t 1 ]]; then
  echo "==> starting the service stack in Process Compose"
else
  echo "==> no terminal detected; starting the service stack without the TUI"
  echo "    logs:   ${ONYX_ZED_ROOT}/.zed/logs"
  echo "    attach: process-compose --port ${ONYX_ZED_CONTROL_PORT} attach"
  process_compose_args+=(--tui=false)
fi

export ONYX_ZED_ROOT
ONYX_ZED_STACK_STARTED=true
process-compose "${process_compose_args[@]}" up

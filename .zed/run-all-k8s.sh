#!/usr/bin/env bash

set -euo pipefail

ONYX_ZED_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ONYX_ZED_ROOT
readonly ONYX_ZED_ENV_FILE="${ONYX_ZED_ROOT}/.vscode/.env.k8s"
readonly ONYX_ZED_WEB_ENV_FILE="${ONYX_ZED_ROOT}/.vscode/.env.web"
readonly ONYX_ZED_COMPOSE_FILE="${ONYX_ZED_ROOT}/.zed/process-compose.k8s.yaml"
readonly ONYX_ZED_CONTROL_PORT=18080
readonly ONYX_ZED_API_PORT=8080
readonly ONYX_ZED_WEB_PORT=3000
# Same private roots that deployment/helm/dev/k8s-up.sh trusts in the cluster.
readonly ONYX_ZED_CA_DIR="${ONYX_DEV_CA_DIR:-$HOME/.onyx-dev/ca-certificates}"
readonly ONYX_ZED_CA_BUNDLE="$HOME/.onyx-dev/ca-bundle.crt"

ONYX_ZED_STACK_STARTED=false
ONYX_ZED_INTERCEPT_CREATED=false
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

is_managed_api() {
  local pid="$1"
  local command

  command="$(process_command "$pid")"
  [[ "$command" == *"-m uvicorn onyx.main:app"* ]] &&
    [[ "$command" == *"${ONYX_ZED_ROOT}/backend"* ]] &&
    [[ "$command" == *"--port ${ONYX_ZED_API_PORT}"* ]]
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

# Run a command, discard its output, and kill it if it outlives the deadline.
# macOS has no `timeout`. Returns 124 on the deadline and 0 otherwise: the
# command's own exit status is deliberately dropped, because every caller is a
# best-effort cleanup that must never wedge the whole task.
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

managed_api_pids() {
  local pid
  local command

  while read -r pid command; do
    if is_managed_api "$pid"; then
      echo "$pid"
    fi
  done < <(ps -axo pid=,command=)
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
  local api_pids=()

  while IFS= read -r pid; do
    [[ -n "$pid" ]] && control_listener_pids+=("$pid")
  done < <(listener_pids "$ONYX_ZED_CONTROL_PORT")

  # Bash 3.2 (the macOS system bash) treats "${empty[@]}" as an unbound
  # variable under `set -u`, so guard every array expansion with a count check.
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

  while IFS= read -r pid; do
    [[ -n "$pid" ]] && api_pids+=("$pid")
  done < <(managed_api_pids)

  if [[ "${#api_pids[@]}" -gt 0 ]]; then
    echo "==> stopping stale Onyx API reload processes"
    terminate_process_trees "${api_pids[@]}"
  fi

  assert_port_available "$ONYX_ZED_CONTROL_PORT" "Process Compose control server"
  assert_port_available "$ONYX_ZED_API_PORT" "Onyx API"
}

# Python ignores the macOS keychain: httpx/requests verify against certifi, so
# behind a TLS-intercepting proxy every LLM call dies with
# `CERTIFICATE_VERIFY_FAILED ... self-signed certificate in certificate chain`.
# Merge the private roots into a copy of certifi and point the child processes
# at it. No-op when ONYX_ZED_CA_DIR holds nothing.
export_ca_bundle() {
  if ! compgen -G "$ONYX_ZED_CA_DIR/*.crt" >/dev/null; then
    return 0
  fi

  local built=1
  mkdir -p "$(dirname "$ONYX_ZED_CA_BUNDLE")"
  "${ONYX_ZED_ROOT}/.venv/bin/python" - \
    "$ONYX_ZED_CA_BUNDLE" "$ONYX_ZED_CA_DIR" <<'PY' || built=0
import glob
import os
import sys

import certifi

bundle_path, ca_dir = sys.argv[1], sys.argv[2]
chunks = [open(certifi.where(), "rb").read()]
for path in sorted(glob.glob(os.path.join(ca_dir, "*.crt"))):
    chunks.append(open(path, "rb").read())
with open(bundle_path, "wb") as out:
    out.write(b"\n".join(chunks))
PY

  if [[ "$built" -eq 0 ]]; then
    echo "warning: could not build $ONYX_ZED_CA_BUNDLE; LLM calls may fail TLS" >&2
    return 0
  fi

  export SSL_CERT_FILE="$ONYX_ZED_CA_BUNDLE"
  export REQUESTS_CA_BUNDLE="$ONYX_ZED_CA_BUNDLE"
  export NODE_EXTRA_CA_CERTS="$ONYX_ZED_CA_BUNDLE"
  echo "==> trusting private root CAs via $ONYX_ZED_CA_BUNDLE"
}

update_env_value() {
  local key="$1"
  local value="$2"
  local temporary_file

  temporary_file="$(mktemp "${ONYX_ZED_ENV_FILE}.tmp.XXXXXX")"
  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    index($0, key "=") == 1 { print key "=" value; found = 1; next }
    { print }
    END { if (!found) print key "=" value }
  ' "$ONYX_ZED_ENV_FILE" >"$temporary_file"
  chmod 600 "$temporary_file"
  mv "$temporary_file" "$ONYX_ZED_ENV_FILE"
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
  if [[ "$ONYX_ZED_INTERCEPT_CREATED" == true ]]; then
    run_bounded 10 telepresence leave onyx-api-server || true
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
require_command kubectl "install kubectl before using the local kind cluster"
require_file "$ONYX_ZED_ENV_FILE" "copy .vscode/.env.k8s.template and fill in its required values"
require_file "$ONYX_ZED_WEB_ENV_FILE" "create the web environment file used by the Zed web task"
require_file "${ONYX_ZED_ROOT}/.venv/bin/python" "run 'uv sync --frozen' from the repository root"

if ! kubectl config get-contexts kind-onyx-dev -o name >/dev/null 2>&1; then
  echo "error: kubectl context kind-onyx-dev was not found; run deployment/helm/dev/k8s-up.sh first" >&2
  exit 1
fi

echo "==> reading cluster secrets into .vscode/.env.k8s"
readonly ONYX_ZED_KUBECTL=(kubectl --context kind-onyx-dev --namespace onyx)
opensearch_password="$(
  "${ONYX_ZED_KUBECTL[@]}" get secret onyx-opensearch \
    -o jsonpath='{.data.opensearch_admin_password}' 2>/dev/null | base64 -d || true
)"
if [[ -z "$opensearch_password" ]]; then
  echo "error: could not read the onyx-opensearch admin password; is the cluster running?" >&2
  exit 1
fi

encryption_key="$(
  "${ONYX_ZED_KUBECTL[@]}" get secret onyx-encryption-key \
    -o jsonpath='{.data.encryption_key_secret}' 2>/dev/null | base64 -d || true
)"
if [[ -z "$encryption_key" ]]; then
  echo "error: could not read the onyx-encryption-key value; is the cluster running?" >&2
  exit 1
fi

update_env_value OPENSEARCH_ADMIN_PASSWORD "$opensearch_password"
update_env_value ENCRYPTION_KEY_SECRET "$encryption_key"
unset opensearch_password encryption_key

mkdir -p "${ONYX_ZED_ROOT}/.zed/logs"

stop_managed_stack
assert_port_available "$ONYX_ZED_WEB_PORT" "Onyx web server"

echo "==> connecting Telepresence to kind-onyx-dev"
# Clears a daemon left pointing at another context. OSS 2.31.2 sometimes spins
# here forever even with no daemon running, so never wait on it indefinitely.
if ! run_bounded 15 telepresence quit; then
  echo "    'telepresence quit' did not exit in 15s; killed it and continuing"
fi
telepresence connect --context kind-onyx-dev --namespace onyx

echo "==> intercepting onyx-api-server on port ${ONYX_ZED_API_PORT}"
run_bounded 10 telepresence leave onyx-api-server || true
telepresence intercept onyx-api-server \
  --namespace onyx \
  --port 8080:8080 \
  --mount=false
ONYX_ZED_INTERCEPT_CREATED=true

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

export_ca_bundle

process_compose_args=(
  --port "$ONYX_ZED_CONTROL_PORT"
  --ordered-shutdown
  --disable-dotenv
  --config "$ONYX_ZED_COMPOSE_FILE"
)

# Every process in the compose file writes to .zed/logs, so nothing reaches
# stdout. Without a terminal the TUI also draws nothing, and the stack looks
# like it hung. Run headless in that case and say where the logs are.
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

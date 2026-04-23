#!/usr/bin/env bash
# run-platform.sh
# Helper to run the Onyx platform locally via Docker Compose.
#
# Usage:
#   ./run-platform.sh dev              Rebuild images from local source and bring up the
#                                      platform (all services) in dev mode. This ensures
#                                      any code changes under backend/ and web/ are picked
#                                      up on each run.
#   ./run-platform.sh dev -no-build    Bring up the platform without rebuilding (faster;
#                                      uses cached/prebuilt images).
#   ./run-platform.sh dev -clean       Tear down everything (containers, volumes, images,
#                                      orphans) and then rebuild + bring up a fresh
#                                      platform.
#   ./run-platform.sh down             Stop the platform (keep data).
#   ./run-platform.sh down -clean      Stop the platform and wipe volumes + images.
#   ./run-platform.sh status           Show status of platform services.
#   ./run-platform.sh logs [service]   Tail logs (optionally for one service).
#   ./run-platform.sh -h | --help      Show this help message.

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="${SCRIPT_DIR}/deployment/docker_compose"
COMPOSE_PROJECT_NAME="onyx"

BASE_COMPOSE_FILE="docker-compose.yml"
DEV_COMPOSE_FILE="docker-compose.dev.yml"

ENV_FILE="${COMPOSE_DIR}/.env"
ENV_TEMPLATE="${COMPOSE_DIR}/env.template"

# ---------------------------------------------------------------------------
# Pretty logging
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_INFO=$'\033[0;36m'
  C_OK=$'\033[0;32m'
  C_WARN=$'\033[0;33m'
  C_ERR=$'\033[0;31m'
else
  C_RESET=""; C_BOLD=""; C_INFO=""; C_OK=""; C_WARN=""; C_ERR=""
fi

log()   { printf "%s[run-platform]%s %s\n" "${C_INFO}" "${C_RESET}" "$*"; }
ok()    { printf "%s[run-platform]%s %s\n" "${C_OK}"   "${C_RESET}" "$*"; }
warn()  { printf "%s[run-platform]%s %s\n" "${C_WARN}" "${C_RESET}" "$*"; }
err()   { printf "%s[run-platform]%s %s\n" "${C_ERR}"  "${C_RESET}" "$*" >&2; }

usage() {
  sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker is not installed or not on PATH. Install Docker Desktop / Engine first."
    exit 1
  fi

  if ! docker info >/dev/null 2>&1; then
    err "Docker daemon is not running. Start Docker Desktop (or the docker service) and retry."
    exit 1
  fi

  if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker-compose)
  else
    err "Neither 'docker compose' (v2) nor 'docker-compose' (v1) is available."
    exit 1
  fi
}

ensure_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f "${ENV_TEMPLATE}" ]]; then
      warn ".env not found in ${COMPOSE_DIR}. Copying env.template -> .env"
      cp "${ENV_TEMPLATE}" "${ENV_FILE}"
    else
      warn "No .env or env.template found in ${COMPOSE_DIR}. Proceeding with defaults."
    fi
  fi
}

# ---------------------------------------------------------------------------
# Compose helpers
# ---------------------------------------------------------------------------
compose_dev() {
  (
    cd "${COMPOSE_DIR}"
    "${DOCKER_COMPOSE[@]}" \
      -p "${COMPOSE_PROJECT_NAME}" \
      -f "${BASE_COMPOSE_FILE}" \
      -f "${DEV_COMPOSE_FILE}" \
      "$@"
  )
}

compose_base() {
  (
    cd "${COMPOSE_DIR}"
    "${DOCKER_COMPOSE[@]}" \
      -p "${COMPOSE_PROJECT_NAME}" \
      -f "${BASE_COMPOSE_FILE}" \
      "$@"
  )
}

# Destructive: remove containers, networks, named volumes, images built by this
# compose project, and orphan containers. Data will be lost.
wipe_everything() {
  warn "Wiping containers, volumes, images and orphans for project '${COMPOSE_PROJECT_NAME}'..."
  compose_dev down --volumes --remove-orphans --rmi all || true

  # Extra safety: prune any dangling named volumes that belong to the project
  # but were not tracked by the current compose file set (e.g. renamed services).
  local leftover
  leftover=$(docker volume ls -q --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" 2>/dev/null || true)
  if [[ -n "${leftover}" ]]; then
    warn "Removing leftover project volumes:"
    printf '  - %s\n' ${leftover}
    docker volume rm ${leftover} >/dev/null 2>&1 || true
  fi

  ok "Clean wipe complete."
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
cmd_dev() {
  local clean="false"
  local build="true"
  for arg in "$@"; do
    case "${arg}" in
      -clean|--clean|-c)
        clean="true"
        ;;
      -no-build|--no-build)
        build="false"
        ;;
      -build|--build)
        build="true"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        err "Unknown option for 'dev': ${arg}"
        usage
        exit 1
        ;;
    esac
  done

  require_docker
  ensure_env_file

  if [[ "${clean}" == "true" ]]; then
    wipe_everything
  fi

  log "Starting Onyx platform in dev mode..."
  log "Compose files: ${BASE_COMPOSE_FILE} + ${DEV_COMPOSE_FILE}"
  log "Working dir:   ${COMPOSE_DIR}"

  # Default behavior is to rebuild images from the local source tree so that
  # changes under backend/ and web/ are reflected on each run. Pass
  # --no-build (or -no-build) to skip the rebuild and reuse cached images.
  local up_args=(-d --wait)
  if [[ "${build}" == "true" ]]; then
    log "Rebuilding images from local source (use -no-build to skip)..."
    up_args+=(--build)
  else
    warn "Skipping image rebuild (-no-build). Cached/prebuilt images will be used."
  fi

  compose_dev up "${up_args[@]}"

  ok "Onyx platform is up."
  log "Quick links:"
  log "  Web UI     : http://localhost:3000"
  log "  API server : http://localhost:8080"
  log "  Postgres   : localhost:5432"
  log "  Redis      : localhost:6379"
  log "  MinIO UI   : http://localhost:9005"
  log "Tail logs with: ./run-platform.sh logs"
}

cmd_down() {
  local clean="false"
  for arg in "$@"; do
    case "${arg}" in
      -clean|--clean|-c) clean="true" ;;
      -h|--help) usage; exit 0 ;;
      *) err "Unknown option for 'down': ${arg}"; usage; exit 1 ;;
    esac
  done

  require_docker
  if [[ "${clean}" == "true" ]]; then
    wipe_everything
  else
    log "Stopping Onyx platform (data preserved)..."
    compose_dev down --remove-orphans
    ok "Platform stopped."
  fi
}

cmd_status() {
  require_docker
  compose_dev ps
}

cmd_logs() {
  require_docker
  if [[ $# -gt 0 ]]; then
    compose_dev logs -f --tail=200 "$@"
  else
    compose_dev logs -f --tail=200
  fi
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 1
  fi

  local command="$1"; shift
  case "${command}" in
    dev)            cmd_dev "$@" ;;
    down|stop)      cmd_down "$@" ;;
    status|ps)      cmd_status ;;
    logs)           cmd_logs "$@" ;;
    -h|--help|help) usage ;;
    *)
      err "Unknown command: ${command}"
      usage
      exit 1
      ;;
  esac
}

main "$@"

#!/usr/bin/env bash
#
# dev.sh — Onyx local-cluster orchestrator.
#
# One script, one entry point. See docs/dev/local-cluster.md for the
# architecture (single k3d cluster, shared onyx-infra namespace, one
# onyx-<slug> namespace per worktree).
#
# Usage:
#   deployment/helm/dev/dev.sh up            # bring up everything for THIS worktree
#                                            # (creates cluster + infra if absent,
#                                            #  provisions DB/bucket/redis, execs `tilt up`)
#   deployment/helm/dev/dev.sh stop          # pause the cluster — data preserved
#   deployment/helm/dev/dev.sh start         # resume a paused cluster
#   deployment/helm/dev/dev.sh status        # show cluster + worktree state
#
#   # Destructive subcommands. These are intentionally NOT exposed as VSCode
#   # tasks so they can't be invoked with one click.
#   deployment/helm/dev/dev.sh nuke worktree           # destroy THIS worktree's DB/bucket/ns
#   deployment/helm/dev/dev.sh nuke worktree --slug X  # destroy a specific worktree
#   deployment/helm/dev/dev.sh nuke all                # destroy the cluster + ALL worktree state
#
# Flags accepted by `up`:
#   --slug <name>             override the slug (default: derive from git branch)
#   --skip-infra              skip cluster + infra creation (assume already up)
#   --no-tilt                 do all provisioning but don't exec tilt up
#   --no-browser              don't open the Tilt UI in the browser after launch
#   --opensearch-password <p> set OpenSearch admin password on first install
#
# Flags accepted by `nuke worktree`:
#   --slug <name>   override the slug (default: derive from git branch)
#   --keep-data     uninstall pods but preserve postgres DB + minio bucket
#
# This script is meant to be invoked directly during dogfooding. Once `ods`
# wraps the same flow, callers should prefer `ods` over invoking the script
# by path.

set -euo pipefail

# ====================================================================
# Globals
# ====================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CHART_DIR="${REPO_ROOT}/deployment/helm/charts/onyx"
INFRA_VALUES="${CHART_DIR}/values-dev-infra.yaml"

CLUSTER_NAME="onyx-local"
REGISTRY_NAME="onyx-registry"
# macOS Ventura+ reserves :5000 for AirPlay Receiver; use :5001 instead.
REGISTRY_PORT="5001"
KUBECONFIG_FILE="${HOME}/.kube/onyx-local.yaml"
INFRA_NS="onyx-infra"
INFRA_RELEASE="onyx-infra"
STATE_DIR="${HOME}/.config/onyx-dev"

# ====================================================================
# Shared helpers
# ====================================================================

log()  { echo "[dev.sh] $*"; }
warn() { echo "[dev.sh] warn: $*" >&2; }
die()  { echo "[dev.sh] error: $*" >&2; exit 1; }

require_tool() {
  local bin="$1"
  command -v "${bin}" >/dev/null 2>&1 \
    || die "'${bin}' is required but not on PATH (run: brew bundle)"
}

slugify() {
  local raw="$1"
  echo "${raw}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's|[^a-z0-9-]+|-|g; s|^-+||; s|-+$||' \
    | cut -c1-40
}

# Open a URL in the user's default browser. macOS `open` and Linux
# `xdg-open` both already focus an existing tab if one matches, so calling
# this on every `dev.sh up` doesn't spawn duplicate Tilt tabs.
open_url() {
  local url="$1"
  if command -v open >/dev/null 2>&1; then
    open "${url}" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${url}" >/dev/null 2>&1 || true
  fi
}

derive_slug() {
  local branch
  branch="$(git -C "$(pwd)" branch --show-current 2>/dev/null || true)"
  [[ -n "${branch}" ]] || die "not on a git branch (detached HEAD?). Pass --slug explicitly."
  slugify "${branch}"
}

ensure_local_context() {
  [[ -f "${KUBECONFIG_FILE}" ]] || die "${KUBECONFIG_FILE} missing — run 'dev.sh up' first."
  export KUBECONFIG="${KUBECONFIG_FILE}"
  local expected="k3d-${CLUSTER_NAME}"
  local current
  current="$(kubectl config current-context 2>/dev/null || true)"
  [[ "${current}" == "${expected}" ]] \
    || die "kubectl context is '${current}', expected '${expected}'"
}

clear_pending_helm_release() {
  # If a previous `tilt up` was Ctrl-C'd while `helm install --wait` was
  # running, the release is left in `pending-install` and the next install
  # aborts with "another operation in progress".
  local ns="$1" release="$2"
  local status
  status=$(helm -n "${ns}" status "${release}" -o json 2>/dev/null \
    | jq -r '.info.status // empty' 2>/dev/null || true)
  case "${status}" in
    pending-install|pending-upgrade|pending-rollback)
      log "clearing stuck helm release ${release} (-n ${ns}) status=${status}"
      helm -n "${ns}" uninstall "${release}" --ignore-not-found || true
      ;;
  esac
}

cluster_exists() {
  k3d cluster list "${CLUSTER_NAME}" >/dev/null 2>&1
}

infra_ready() {
  kubectl -n "${INFRA_NS}" get cluster.postgresql.cnpg.io "${INFRA_RELEASE}-pg" \
    >/dev/null 2>&1
}

# ====================================================================
# Cluster + infra bring-up (idempotent)
# ====================================================================

ensure_cluster() {
  if k3d registry list "${REGISTRY_NAME}" >/dev/null 2>&1; then
    log "k3d registry '${REGISTRY_NAME}' already exists"
  else
    log "creating k3d registry '${REGISTRY_NAME}' on :${REGISTRY_PORT}"
    k3d registry create "${REGISTRY_NAME}" --port "${REGISTRY_PORT}"
  fi

  if cluster_exists; then
    log "k3d cluster '${CLUSTER_NAME}' already exists"
  else
    log "creating k3d cluster '${CLUSTER_NAME}'"
    k3d cluster create "${CLUSTER_NAME}" \
      --api-port 6550 \
      --registry-use "${REGISTRY_NAME}:${REGISTRY_PORT}" \
      --k3s-arg "--disable=traefik@server:0" \
      --k3s-arg "--disable=servicelb@server:0"
  fi

  mkdir -p "$(dirname "${KUBECONFIG_FILE}")"
  k3d kubeconfig get "${CLUSTER_NAME}" > "${KUBECONFIG_FILE}"
  log "wrote kubeconfig to ${KUBECONFIG_FILE}"

  export KUBECONFIG="${KUBECONFIG_FILE}"

  local expected="k3d-${CLUSTER_NAME}"
  local current
  current="$(kubectl config current-context)"
  [[ "${current}" == "${expected}" ]] \
    || die "current context is '${current}', expected '${expected}'"
}

ensure_operators() {
  helm repo add cnpg https://cloudnative-pg.github.io/charts >/dev/null 2>&1 || true
  helm repo update cnpg >/dev/null

  if ! helm -n cnpg-system status cnpg >/dev/null 2>&1; then
    log "installing CNPG operator (one-time)"
    helm install cnpg cnpg/cloudnative-pg \
      --namespace cnpg-system --create-namespace \
      --version 0.26.0 --wait --timeout 5m
  else
    log "CNPG operator already installed"
  fi

  helm repo add ot-helm https://ot-container-kit.github.io/helm-charts >/dev/null 2>&1 || true
  helm repo update ot-helm >/dev/null

  if ! helm -n redis-operator-system status redis-operator >/dev/null 2>&1; then
    log "installing redis-operator (one-time)"
    helm install redis-operator ot-helm/redis-operator \
      --namespace redis-operator-system --create-namespace \
      --version 0.24.0 --wait --timeout 5m
  else
    log "redis-operator already installed"
  fi
}

ensure_infra_release() {
  local opensearch_password="$1"

  kubectl get namespace "${INFRA_NS}" >/dev/null 2>&1 \
    || kubectl create namespace "${INFRA_NS}"

  clear_pending_helm_release "${INFRA_NS}" "${INFRA_RELEASE}"
  clear_pending_helm_release cnpg-system cnpg
  clear_pending_helm_release redis-operator-system redis-operator

  # Generate an OpenSearch admin password on first install; reuse the
  # existing Secret on upgrades.
  local pw_flag=()
  if ! kubectl -n "${INFRA_NS}" get secret onyx-opensearch >/dev/null 2>&1; then
    if [[ -z "${opensearch_password}" ]]; then
      opensearch_password="Aa1!$(openssl rand -hex 12)"
      log "generated opensearch admin password: ${opensearch_password}"
    fi
    pw_flag=(--set "auth.opensearch.values.opensearch_admin_password=${opensearch_password}")
  fi

  # Isolated helm repo config so a stale dev-global repo with a colliding
  # name doesn't shadow ours.
  local helm_dev_home
  helm_dev_home="$(mktemp -d -t onyx-dev-helm-XXXXXX)"
  export HELM_REPOSITORY_CONFIG="${helm_dev_home}/repositories.yaml"
  export HELM_REPOSITORY_CACHE="${helm_dev_home}/cache"
  mkdir -p "${HELM_REPOSITORY_CACHE}"
  # shellcheck disable=SC2064
  trap "rm -rf '${helm_dev_home}'" RETURN

  # Repo names must match the dep names in Chart.yaml.
  helm repo add cloudnative-pg   https://cloudnative-pg.github.io/charts          >/dev/null
  helm repo add opensearch       https://opensearch-project.github.io/helm-charts >/dev/null
  helm repo add ingress-nginx    https://kubernetes.github.io/ingress-nginx       >/dev/null
  helm repo add redis-ot         https://ot-container-kit.github.io/helm-charts   >/dev/null
  helm repo add minio            https://charts.min.io/                           >/dev/null
  helm repo add code-interpreter https://onyx-dot-app.github.io/python-sandbox/   >/dev/null
  helm repo update >/dev/null
  helm dependency update "${CHART_DIR}" >/dev/null

  log "installing infra release '${INFRA_RELEASE}' in namespace '${INFRA_NS}'"

  local attempts=3
  for attempt in $(seq 1 "${attempts}"); do
    if helm upgrade --install "${INFRA_RELEASE}" "${CHART_DIR}" \
        -n "${INFRA_NS}" \
        -f "${INFRA_VALUES}" \
        ${pw_flag[@]+"${pw_flag[@]}"} \
        --wait --timeout 10m; then
      return 0
    fi
    if [[ "${attempt}" -lt "${attempts}" ]]; then
      warn "helm install failed (attempt ${attempt}/${attempts}) — waiting 20s, retrying"
      sleep 20
    else
      die "helm install failed after ${attempts} attempts"
    fi
  done
}

# ====================================================================
# Worktree provisioning
# ====================================================================

allocate_offsets() {
  # State files in $STATE_DIR record (tilt_port, redis_db_base) per slug.
  # Scan siblings to pick the first free offset.
  local slug="$1"
  local used_tilt=" " used_redis=" "
  shopt -s nullglob
  local f
  for f in "${STATE_DIR}"/*.json; do
    [[ "$(basename "${f}" .json)" == "${slug}" ]] && continue
    local tp rb
    tp="$(jq -r '.tilt_port' "${f}" 2>/dev/null || echo "")"
    rb="$(jq -r '.redis_db_base' "${f}" 2>/dev/null || echo "")"
    [[ -n "${tp}" && "${tp}" != "null" ]] && used_tilt+="${tp} "
    [[ -n "${rb}" && "${rb}" != "null" ]] && used_redis+="${rb} "
  done
  shopt -u nullglob

  local tp rb i
  for ((i=0; i<100; i++)); do
    tp=$((10350 + i))
    if [[ "${used_tilt}" != *" ${tp} "* ]]; then break; fi
  done
  [[ -n "${tp}" ]] || die "couldn't allocate a free tilt port"

  for ((i=0; i<80; i++)); do
    rb=$((i * 3))
    if [[ "${used_redis}" != *" ${rb} "* ]]; then break; fi
  done
  [[ -n "${rb}" ]] || die "couldn't allocate a free redis db base"

  echo "${tp} ${rb}"
}

provision_pg_database() {
  local db="$1"
  local pg_pod
  pg_pod="$(kubectl -n "${INFRA_NS}" get pod \
              -l 'cnpg.io/cluster=onyx-infra-pg,cnpg.io/instanceRole=primary' \
              -o jsonpath='{.items[0].metadata.name}')"
  [[ -n "${pg_pod}" ]] || die "no CNPG primary pod found in ${INFRA_NS}"

  if kubectl -n "${INFRA_NS}" exec "${pg_pod}" -c postgres -- \
       psql -tA -d postgres -c "SELECT 1 FROM pg_database WHERE datname='${db}'" \
       | grep -q '^1$'; then
    log "database ${db} already exists"
  else
    log "creating database ${db}"
    kubectl -n "${INFRA_NS}" exec "${pg_pod}" -c postgres -- \
      psql -d postgres -c "CREATE DATABASE \"${db}\" OWNER postgres;"
  fi
}

drop_pg_database() {
  local db="$1"
  local pg_pod
  pg_pod="$(kubectl -n "${INFRA_NS}" get pod \
              -l 'cnpg.io/cluster=onyx-infra-pg,cnpg.io/instanceRole=primary' \
              -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  [[ -n "${pg_pod}" ]] || { warn "no CNPG primary pod found — skipping DROP"; return; }
  log "dropping database ${db}"
  kubectl -n "${INFRA_NS}" exec "${pg_pod}" -c postgres -- \
    psql -d postgres -c "DROP DATABASE IF EXISTS \"${db}\" WITH (FORCE);" || true
}

minio_pod() {
  local p
  p="$(kubectl -n "${INFRA_NS}" get pod -l 'app=minio' \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -z "${p}" ]]; then
    p="$(kubectl -n "${INFRA_NS}" get pod -l 'app.kubernetes.io/name=minio' \
          -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  fi
  echo "${p}"
}

provision_minio_bucket() {
  local bucket="$1"
  local pod
  pod="$(minio_pod)"
  [[ -n "${pod}" ]] || die "no minio pod found in ${INFRA_NS}"
  log "creating minio bucket ${bucket}"
  kubectl -n "${INFRA_NS}" exec "${pod}" -- /bin/sh -c "
    mc alias set local http://localhost:9000 minioadmin minioadmin >/dev/null &&
    mc mb -p local/${bucket} 2>/dev/null || true
  "
}

drop_minio_bucket() {
  local bucket="$1"
  local pod
  pod="$(minio_pod)"
  [[ -n "${pod}" ]] || { warn "no minio pod found — skipping bucket delete"; return; }
  log "removing minio bucket ${bucket}"
  kubectl -n "${INFRA_NS}" exec "${pod}" -- /bin/sh -c "
    mc alias set local http://localhost:9000 minioadmin minioadmin >/dev/null &&
    mc rb --force local/${bucket} 2>/dev/null || true
  "
}

write_worktree_values() {
  local slug="$1" db="$2" bucket="$3" redis_base="$4"
  local app_ns="onyx-${slug}"
  local app_release="onyx-${slug}"
  local sandbox_ns="onyx-${slug}-sandboxes"
  local ingress_host="${slug}.onyx.localhost"
  local out="${STATE_DIR}/${slug}.values.yaml"

  cat > "${out}" <<EOF
# Auto-generated by dev.sh for slug '${slug}'.
# Re-running 'dev.sh up' overwrites this file.

configMap:
  POSTGRES_DB: "${db}"
  S3_FILE_STORE_BUCKET_NAME: "${bucket}"
  REDIS_DB_NUMBER: "${redis_base}"
  REDIS_DB_NUMBER_CELERY_RESULT_BACKEND: "$((redis_base + 1))"
  REDIS_DB_NUMBER_CELERY: "$((redis_base + 2))"
  SANDBOX_NAMESPACE: "${sandbox_ns}"
  SANDBOX_API_SERVER_URL: "http://${app_release}-api-service.${app_ns}.svc.cluster.local:8080"

ingress:
  api:
    host: "${ingress_host}"
  webserver:
    host: "${ingress_host}"
EOF
  log "wrote ${out}"
}

# ====================================================================
# Subcommand: up
# ====================================================================

cmd_up() {
  local slug="" skip_infra=0 run_tilt=1 open_browser=1 opensearch_password=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --slug)                  slug="$2"; shift 2 ;;
      --skip-infra)            skip_infra=1; shift ;;
      --no-tilt)               run_tilt=0; shift ;;
      --no-browser)            open_browser=0; shift ;;
      --opensearch-password)   opensearch_password="$2"; shift 2 ;;
      *) die "unknown flag: $1" ;;
    esac
  done

  require_tool k3d
  require_tool tilt
  require_tool kubectl
  require_tool helm
  require_tool jq

  # ---- Cluster + infra ----
  if [[ "${skip_infra}" -eq 0 ]]; then
    ensure_cluster
    ensure_operators
    ensure_infra_release "${opensearch_password}"
  else
    ensure_local_context
    infra_ready || die "infra release not ready in ${INFRA_NS} — drop --skip-infra"
  fi

  # ---- Per-worktree ----
  [[ -n "${slug}" ]] || slug="$(derive_slug)"
  [[ "${slug}" =~ ^[a-z0-9-]+$ ]] && [[ "${#slug}" -le 40 ]] \
    || die "slug '${slug}' must match [a-z0-9-]+ and be ≤40 chars"

  local app_ns="onyx-${slug}"
  local sandbox_ns="onyx-${slug}-sandboxes"
  local app_release="onyx-${slug}"
  local db_name="postgres_${slug//-/_}"
  local bucket_name="onyx-${slug}"
  local ingress_host="${slug}.onyx.localhost"
  local state_file="${STATE_DIR}/${slug}.json"
  local values_file="${STATE_DIR}/${slug}.values.yaml"

  log "worktree slug: ${slug}"

  mkdir -p "${STATE_DIR}"

  local tilt_port redis_base
  if [[ -f "${state_file}" ]]; then
    tilt_port="$(jq -r '.tilt_port' "${state_file}")"
    redis_base="$(jq -r '.redis_db_base' "${state_file}")"
    log "reusing allocation: tilt_port=${tilt_port}, redis_db_base=${redis_base}"
  else
    read -r tilt_port redis_base < <(allocate_offsets "${slug}")
    log "allocated: tilt_port=${tilt_port}, redis_db_base=${redis_base}"
    jq -n \
      --arg slug "${slug}" \
      --argjson tilt_port "${tilt_port}" \
      --argjson redis_base "${redis_base}" \
      --arg db "${db_name}" \
      --arg bucket "${bucket_name}" \
      --arg host "${ingress_host}" \
      '{slug:$slug, tilt_port:$tilt_port, redis_db_base:$redis_base, db:$db, bucket:$bucket, ingress_host:$host}' \
      > "${state_file}"
  fi

  kubectl get namespace "${app_ns}"     >/dev/null 2>&1 || kubectl create namespace "${app_ns}"
  kubectl get namespace "${sandbox_ns}" >/dev/null 2>&1 || kubectl create namespace "${sandbox_ns}"
  kubectl label    namespace "${sandbox_ns}" app.kubernetes.io/managed-by=Helm --overwrite >/dev/null
  kubectl annotate namespace "${sandbox_ns}" meta.helm.sh/release-name="${app_release}" --overwrite >/dev/null
  kubectl annotate namespace "${sandbox_ns}" meta.helm.sh/release-namespace="${app_ns}" --overwrite >/dev/null

  provision_pg_database "${db_name}"
  provision_minio_bucket "${bucket_name}"
  write_worktree_values "${slug}" "${db_name}" "${bucket_name}" "${redis_base}"

  if [[ "${run_tilt}" -eq 0 ]]; then
    log "skipping 'tilt up' (--no-tilt). Run with:"
    log "  cd ${REPO_ROOT} && WORKTREE_SLUG=${slug} TILT_PORT=${tilt_port} tilt up"
    return 0
  fi

  cd "${REPO_ROOT}"
  export WORKTREE_SLUG="${slug}"
  export WORKTREE_APP_NS="${app_ns}"
  export WORKTREE_APP_RELEASE="${app_release}"
  export WORKTREE_INGRESS_HOST="${ingress_host}"
  export WORKTREE_VALUES_FILE="${values_file}"
  export TILT_PORT="${tilt_port}"

  log ""
  log "launching 'tilt up' — Tilt UI at http://localhost:${tilt_port}"
  log "app will be reachable at http://${ingress_host}:13000 once pods are ready"
  log ""

  # Schedule a browser open AFTER tilt has had time to bind :tilt_port. The
  # subshell forks before exec, so it survives the script being replaced
  # by `tilt up`. macOS/Linux openers focus an existing tab rather than
  # opening a duplicate, so re-running `dev.sh up` doesn't spam tabs.
  if [[ "${open_browser}" -eq 1 ]]; then
    ( sleep 3 && open_url "http://localhost:${tilt_port}" ) &
    disown
  fi

  exec tilt up --port "${tilt_port}"
}

# ====================================================================
# Subcommand: stop  (pause the cluster — data preserved)
# ====================================================================
#
# `k3d cluster stop` stops the k3s server + agent containers. All pod state
# vanishes (pods are scheduled fresh on resume), but PVCs and the local
# registry contents persist. Resume with `dev.sh start`.

cmd_stop() {
  require_tool k3d
  if ! cluster_exists; then
    log "cluster '${CLUSTER_NAME}' not found — nothing to stop"
    return 0
  fi
  log "stopping k3d cluster '${CLUSTER_NAME}' (data preserved)"
  k3d cluster stop "${CLUSTER_NAME}"
  log "stopped. Resume with: dev.sh start"
}

# ====================================================================
# Subcommand: start  (resume a paused cluster)
# ====================================================================
#
# Counterpart to `stop`. Brings the k3d node containers back up; the
# kubelet reconciles workloads from their stored manifests. The infra and
# any existing worktree pods come back without re-provisioning state.

cmd_start() {
  require_tool k3d
  if ! cluster_exists; then
    die "cluster '${CLUSTER_NAME}' not found — run 'dev.sh up' to create it"
  fi
  log "starting k3d cluster '${CLUSTER_NAME}'"
  k3d cluster start "${CLUSTER_NAME}"
  log "started. Verify with: dev.sh status"
}

# ====================================================================
# Subcommand: nuke  (destructive — NOT exposed as a VSCode task)
# ====================================================================
#
# Two scopes:
#   `nuke worktree`  — drop this worktree's helm release / DB / bucket / namespaces
#   `nuke all`       — also delete the k3d cluster + local registry + ~/.config/onyx-dev
#
# Both prompt for confirmation since they are unrecoverable.

confirm() {
  local prompt="$1"
  read -r -p "${prompt} [y/N] " response
  case "${response}" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *) echo "aborted."; return 1 ;;
  esac
}

cmd_nuke() {
  local scope="${1:-}"
  shift || true
  case "${scope}" in
    worktree) nuke_worktree "$@" ;;
    all)      nuke_all "$@" ;;
    "")       die "usage: dev.sh nuke {worktree|all}" ;;
    *)        die "unknown nuke scope: ${scope} (try: worktree, all)" ;;
  esac
}

nuke_worktree() {
  local slug="" keep_data=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --slug)       slug="$2"; shift 2 ;;
      --keep-data)  keep_data=1; shift ;;
      *) die "unknown flag: $1" ;;
    esac
  done

  [[ -n "${slug}" ]] || slug="$(derive_slug 2>/dev/null || true)"
  [[ -n "${slug}" ]] || die "couldn't derive slug; pass --slug"

  confirm "About to DESTROY worktree '${slug}' (helm release, postgres DB, minio bucket, namespaces). Continue?" || return 1

  require_tool kubectl
  require_tool helm
  ensure_local_context

  local app_ns="onyx-${slug}"
  local sandbox_ns="onyx-${slug}-sandboxes"
  local app_release="onyx-${slug}"
  local db_name="postgres_${slug//-/_}"
  local bucket_name="onyx-${slug}"
  local state_file="${STATE_DIR}/${slug}.json"
  local values_file="${STATE_DIR}/${slug}.values.yaml"

  log "nuking worktree: ${slug}"

  if helm -n "${app_ns}" status "${app_release}" >/dev/null 2>&1; then
    log "uninstalling helm release ${app_release}"
    helm -n "${app_ns}" uninstall "${app_release}" --wait --timeout 3m || true
  fi

  if [[ "${keep_data}" -eq 0 ]]; then
    drop_pg_database "${db_name}"
    drop_minio_bucket "${bucket_name}"
  fi

  kubectl delete namespace "${app_ns}"     --ignore-not-found --wait=false
  kubectl delete namespace "${sandbox_ns}" --ignore-not-found --wait=false

  rm -f "${state_file}" "${values_file}"
  log "worktree '${slug}' destroyed."
}

nuke_all() {
  confirm "About to DESTROY the entire k3d cluster '${CLUSTER_NAME}', the local registry, and ALL worktree state under ${STATE_DIR}. Continue?" || return 1

  require_tool k3d
  if cluster_exists; then
    log "deleting k3d cluster '${CLUSTER_NAME}'"
    k3d cluster delete "${CLUSTER_NAME}"
  fi
  if k3d registry list "${REGISTRY_NAME}" >/dev/null 2>&1; then
    log "deleting k3d registry '${REGISTRY_NAME}'"
    k3d registry delete "${REGISTRY_NAME}"
  fi
  rm -f "${KUBECONFIG_FILE}"
  [[ -d "${STATE_DIR}" ]] && rm -rf "${STATE_DIR}"
  log "cluster destroyed."
}

# ====================================================================
# Subcommand: status
# ====================================================================

cluster_running() {
  # `k3d cluster list -o json` includes serversRunning / agentsRunning counts.
  k3d cluster list "${CLUSTER_NAME}" -o json 2>/dev/null \
    | jq -e '.[0].serversRunning > 0' >/dev/null 2>&1
}

cmd_status() {
  if ! command -v k3d >/dev/null 2>&1; then
    echo "k3d not installed — run: brew bundle"
    return
  fi

  if ! cluster_exists; then
    echo "cluster:  not created (run: dev.sh up)"
    return
  fi
  if cluster_running; then
    echo "cluster:  k3d-${CLUSTER_NAME} RUNNING (registry: ${REGISTRY_NAME}:${REGISTRY_PORT})"
  else
    echo "cluster:  k3d-${CLUSTER_NAME} STOPPED (resume with: dev.sh start)"
    echo ""
    echo "worktrees: (cluster stopped; run 'dev.sh start' to inspect)"
    return
  fi

  if [[ -f "${KUBECONFIG_FILE}" ]]; then
    export KUBECONFIG="${KUBECONFIG_FILE}"
    if infra_ready; then
      echo "infra:    ready (namespace ${INFRA_NS})"
    else
      echo "infra:    not ready"
    fi
  else
    echo "infra:    kubeconfig missing"
  fi

  echo ""
  echo "worktrees:"
  shopt -s nullglob
  local found=0 f slug tp rb host
  for f in "${STATE_DIR}"/*.json; do
    found=1
    slug="$(jq -r '.slug' "${f}")"
    tp="$(jq -r '.tilt_port' "${f}")"
    rb="$(jq -r '.redis_db_base' "${f}")"
    host="$(jq -r '.ingress_host' "${f}")"
    printf "  %-30s tilt=:%-5s redis=%s..%s  http://%s:13000\n" \
      "${slug}" "${tp}" "${rb}" "$((rb + 2))" "${host}"
  done
  shopt -u nullglob
  [[ "${found}" -eq 1 ]] || echo "  (none — run: dev.sh up from a worktree)"
}

# ====================================================================
# Dispatch
# ====================================================================

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//'
}

if [[ $# -eq 0 ]]; then
  usage
  exit 0
fi

case "$1" in
  up)      shift; cmd_up "$@" ;;
  stop)    shift; cmd_stop "$@" ;;
  start)   shift; cmd_start "$@" ;;
  status)  shift; cmd_status "$@" ;;
  nuke)    shift; cmd_nuke "$@" ;;
  -h|--help|help) usage ;;
  *)       die "unknown subcommand: $1 (try: up, down, status)" ;;
esac

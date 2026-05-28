#!/usr/bin/env bash
# CLI equivalent of the "Run All Onyx Services (k8s)" compound launch config.
# Runs the telepresence intercept preLaunchTask, then fans out all 10 services.
# Ctrl-C kills them all. Logs go to backend/log/<service>.log.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/backend/log"
ENV_FILE="$ROOT/.vscode/.env.k8s"
PY="$ROOT/.venv/bin/python"
mkdir -p "$LOG_DIR"

KUBE='kubectl --context kind-onyx-dev'
kubectl config get-contexts -o name | grep -qx kind-onyx-dev \
  || { echo 'error: kubectl context kind-onyx-dev not found' >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "error: $ENV_FILE not found" >&2; exit 1; }

OS_PW=$($KUBE -n onyx get secret onyx-opensearch \
  -o jsonpath='{.data.opensearch_admin_password}' 2>/dev/null | base64 -d || true)
[ -n "$OS_PW" ] || { echo 'error: could not read opensearch admin password' >&2; exit 1; }

TMP=$(mktemp)
awk -v pw="$OS_PW" 'BEGIN{f=0} /^OPENSEARCH_ADMIN_PASSWORD=/{print "OPENSEARCH_ADMIN_PASSWORD=" pw; f=1; next} {print} END{if(!f) print "OPENSEARCH_ADMIN_PASSWORD=" pw}' "$ENV_FILE" > "$TMP" && mv "$TMP" "$ENV_FILE"

telepresence connect --context kind-onyx-dev -n onyx
telepresence leave onyx-api-server 2>/dev/null || true
telepresence intercept onyx-api-server --namespace onyx --port 8080:8080 --mount=false

export PYTHONUNBUFFERED=1 PYTHONPATH=. SANDBOX_BACKEND=kubernetes

PIDS=()
trap 'echo; echo "shutting down..."; kill "${PIDS[@]}" 2>/dev/null || true; wait; exit 0' INT TERM

# Loads .env.k8s via python-dotenv (handles values like `<REPLACE THIS>` that bash source would choke on).
DOTENV_RUN=("$PY" -m dotenv -f "$ENV_FILE" run --no-override --)

run() {
  local name=$1; shift
  echo "→ $name (log: $LOG_DIR/${name}.log)"
  ( "$@" ) >"$LOG_DIR/${name}.log" 2>&1 &
  PIDS+=($!)
}

# Web server uses .vscode/.env.web (loaded by bun); doesn't need .env.k8s.
cd "$ROOT/web"
run web_server bun run dev

cd "$ROOT/backend"
run api_server "${DOTENV_RUN[@]}" "$PY" -m uvicorn onyx.main:app --reload --port 8080

run celery_primary               "${DOTENV_RUN[@]}" "$PY" scripts/dev_celery_reload.py -A onyx.background.celery.versioned_apps.primary               worker --pool=threads --concurrency=4  --prefetch-multiplier=1 --loglevel=INFO --hostname=primary@%n               -Q celery
run celery_light                 "${DOTENV_RUN[@]}" "$PY" scripts/dev_celery_reload.py -A onyx.background.celery.versioned_apps.light                 worker --pool=threads --concurrency=64 --prefetch-multiplier=8 --loglevel=INFO --hostname=light@%n                 -Q vespa_metadata_sync,connector_deletion,doc_permissions_upsert,checkpoint_cleanup,index_attempt_cleanup,opensearch_migration
run celery_heavy                 "${DOTENV_RUN[@]}" "$PY" scripts/dev_celery_reload.py -A onyx.background.celery.versioned_apps.heavy                 worker --pool=threads --concurrency=4  --prefetch-multiplier=1 --loglevel=INFO --hostname=heavy@%n                 -Q connector_pruning,connector_doc_permissions_sync,connector_external_group_sync,csv_generation,sandbox
run celery_docfetching           "${DOTENV_RUN[@]}" "$PY" scripts/dev_celery_reload.py -A onyx.background.celery.versioned_apps.docfetching           worker --pool=threads                       --prefetch-multiplier=1 --loglevel=INFO --hostname=docfetching@%n           -Q connector_doc_fetching
ENABLE_MULTIPASS_INDEXING=false \
run celery_docprocessing         "${DOTENV_RUN[@]}" "$PY" scripts/dev_celery_reload.py -A onyx.background.celery.versioned_apps.docprocessing         worker --pool=threads                       --prefetch-multiplier=1 --loglevel=INFO --hostname=docprocessing@%n         -Q docprocessing
run celery_user_file_processing  "${DOTENV_RUN[@]}" "$PY" scripts/dev_celery_reload.py -A onyx.background.celery.versioned_apps.user_file_processing  worker --pool=threads --concurrency=2  --prefetch-multiplier=1 --loglevel=INFO --hostname=user_file_processing@%n  -Q user_file_processing,user_file_project_sync,user_file_delete
run celery_scheduled_tasks       "${DOTENV_RUN[@]}" "$PY" scripts/dev_celery_reload.py -A onyx.background.celery.versioned_apps.scheduled_tasks       worker --pool=threads --concurrency=4  --prefetch-multiplier=1 --loglevel=INFO --hostname=scheduled_tasks@%n       -Q scheduled_tasks
run celery_beat                  "${DOTENV_RUN[@]}" "$PY" scripts/dev_celery_reload.py -A onyx.background.celery.versioned_apps.beat                  beat   --loglevel=INFO

echo
echo "all services started. tail logs with:"
echo "  tail -f $LOG_DIR/*.log"
echo "ctrl-c to stop everything."
wait

#!/usr/bin/env bash
# company_search skill runner.
#
# Calls the Onyx sandbox search endpoint as the current build session and
# prints the LLM-facing markdown to stdout. Stateless: no files are written.
#
# Required env (injected by the backend at session setup):
#   ONYX_BUILD_SESSION_TOKEN  - bearer token for /api/build/sandbox/*
#   ONYX_BACKEND_URL          - base URL of the Onyx backend (no trailing slash)
#   ONYX_TENANT_ID            - tenant id; sent as X-Onyx-Tenant-ID
#
# Exit codes:
#   0  - success (markdown printed to stdout)
#   1  - usage / argument error
#   2  - missing required env
#   3  - HTTP error from the backend
#   4  - JSON parse error

set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage: company_search "<query>" [--limit N] [--source s1,s2] [--days N]
EOF
  exit 1
}

if [ "$#" -lt 1 ]; then
  usage
fi

query="$1"
shift

if [ -z "${query// }" ]; then
  usage
fi

limit=""
source_filters=""
days=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --limit)
      limit="${2:-}"
      shift 2
      ;;
    --source)
      source_filters="${2:-}"
      shift 2
      ;;
    --days)
      days="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "company_search: unknown argument: $1" >&2
      usage
      ;;
  esac
done

if [ -z "${ONYX_BUILD_SESSION_TOKEN:-}" ]; then
  echo "company_search: ONYX_BUILD_SESSION_TOKEN is not set" >&2
  exit 2
fi
if [ -z "${ONYX_BACKEND_URL:-}" ]; then
  echo "company_search: ONYX_BACKEND_URL is not set" >&2
  exit 2
fi

# Build request body. Use jq so the query is JSON-safe regardless of contents.
body=$(jq -n \
  --arg q "$query" \
  --arg limit "$limit" \
  --arg sources "$source_filters" \
  --arg days "$days" \
  '
    {query: $q}
    + (if $limit == "" then {} else {limit: ($limit | tonumber)} end)
    + (if $sources == "" then {} else {source_filters: ($sources | split(","))} end)
    + (if $days == "" then {} else {time_cutoff_days: ($days | tonumber)} end)
  ')

tenant_header=()
if [ -n "${ONYX_TENANT_ID:-}" ]; then
  tenant_header=(-H "X-Onyx-Tenant-ID: ${ONYX_TENANT_ID}")
fi

# Capture body and HTTP status separately so we can surface a clean error.
tmp_body=$(mktemp)
trap 'rm -f "$tmp_body"' EXIT

http_status=$(curl -sS -o "$tmp_body" -w "%{http_code}" \
  -X POST \
  -H "Authorization: Bearer ${ONYX_BUILD_SESSION_TOKEN}" \
  -H "Content-Type: application/json" \
  "${tenant_header[@]}" \
  --data-binary "$body" \
  "${ONYX_BACKEND_URL%/}/api/build/sandbox/search") || {
    echo "company_search: backend request failed" >&2
    exit 3
  }

if [ "$http_status" -lt 200 ] || [ "$http_status" -ge 300 ]; then
  detail=$(jq -r '.detail // .error_code // empty' < "$tmp_body" 2>/dev/null || true)
  echo "company_search: HTTP ${http_status} — ${detail:-no detail}" >&2
  exit 3
fi

if ! jq -e -r '.llm_facing_text' < "$tmp_body" >/dev/null 2>&1; then
  echo "company_search: malformed response from backend" >&2
  exit 4
fi

jq -r '.llm_facing_text' < "$tmp_body"

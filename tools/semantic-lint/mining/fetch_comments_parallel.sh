#!/usr/bin/env bash
# Dump every PR review comment and issue comment in the repo to JSONL, pages in parallel.
# Usage: fetch_comments_parallel.sh [--workdir DIR]
# Rerunnable: each run rewrites the page files it fetches and the merged outputs.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(python3 -I "${HERE}/common.py" repo)"
WORKDIR="$(python3 -I "${HERE}/common.py" workdir)"
if [[ "${1:-}" == "--workdir" ]]; then
  WORKDIR="${2:?--workdir needs a path}"
fi
mkdir -p "${WORKDIR}/corpus/pages"
OUT="$(cd "${WORKDIR}/corpus" && pwd)"
PAR="${PAR:-12}"

last_page() {
  gh api -i "repos/${REPO}/$1?per_page=100" | grep -i '^link:' | sed -E 's/.*page=([0-9]+)>; rel="last".*/\1/'
}

fetch_kind() {
  local kind="$1" prefix="$2"
  local last; last="$(last_page "$kind")"
  echo "[$(date -u +%FT%TZ)] ${kind}: ${last} pages, PAR=${PAR}"
  seq 1 "${last}" | xargs -P "${PAR}" -n 1 "${HERE}/fetch_page.sh" "${OUT}" "${REPO}" "${kind}" "${prefix}"
  cat "${OUT}/pages/${prefix}"_*.jsonl > "${OUT}/${prefix}.jsonl"
  echo "[$(date -u +%FT%TZ)] ${kind} done: $(wc -l < "${OUT}/${prefix}.jsonl") rows"
}

fetch_kind "pulls/comments" pull_comments
fetch_kind "issues/comments" issue_comments

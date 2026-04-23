#!/usr/bin/env bash
# Sync this InsightAI fork with upstream onyx-dot-app/onyx.
#
# Usage:
#   scripts/sync_upstream.sh              # fetch + merge (default)
#   scripts/sync_upstream.sh rebase       # fetch + rebase onto upstream/main
#   scripts/sync_upstream.sh fetch-only   # fetch only
#
# The only files that should conflict during a sync are the InsightAI brand
# patches, which are listed in project_documentation.md under "Branding
# patches". Resolve those conflicts by keeping the InsightAI side and move on.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

MODE="${1:-merge}"
UPSTREAM_REMOTE="upstream"
UPSTREAM_URL="https://github.com/onyx-dot-app/onyx.git"
UPSTREAM_BRANCH="main"

if ! git remote | grep -q "^${UPSTREAM_REMOTE}$"; then
  echo "[sync] adding remote '${UPSTREAM_REMOTE}' -> ${UPSTREAM_URL}"
  git remote add "${UPSTREAM_REMOTE}" "${UPSTREAM_URL}"
fi

echo "[sync] fetching ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}..."
git fetch "${UPSTREAM_REMOTE}" "${UPSTREAM_BRANCH}"

case "${MODE}" in
  fetch-only)
    echo "[sync] fetch-only mode; nothing to merge."
    ;;
  rebase)
    echo "[sync] rebasing HEAD onto ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}..."
    git rebase "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}"
    ;;
  merge|*)
    echo "[sync] merging ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH} into HEAD..."
    git merge --no-edit "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}" || {
      status=$?
      cat <<'EOF'

[sync] merge conflict detected.

Expected conflict surface (InsightAI brand patches):
  - backend/onyx/configs/constants.py        (ONYX_DEFAULT_APPLICATION_NAME)
  - web/src/providers/DynamicMetadata.tsx    ("Onyx" fallback)
  - web/src/app/layout.tsx                   (metadata.title, description)
  - web/src/app/auth/login/LoginText.tsx     ("Onyx" fallback)
  - web/src/lib/constants.ts                 (APP_SLOGAN)
  - README.md                                (title + fork notice)
  - web/public/logo.svg
  - web/public/onyx.ico
  - backend/static/images/logo.png
  - backend/static/images/logotype.png

Resolve by keeping the InsightAI side ("ours") for those files, then:
  git add <resolved files>
  git commit

If the conflict is OUTSIDE this list, it is a real upstream code change
that needs actual review.
EOF
      exit "$status"
    }
    ;;
esac

echo "[sync] done."

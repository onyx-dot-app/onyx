#!/usr/bin/env bash
# Merge-queue guard for a required check whose real verdict comes from the
# pull_request event only (`required`, `playwright-required`).
#
# The pull_request run records the base it tested against as a commit status
# on the PR head (context = CONTEXT, description = "<base sha> <base ref>").
# This script accepts the verdict when that base is in the target branch's
# history or in the PR's own history. In both cases the merged tree differs
# from the tested tree only by what the target gained since the test, which is
# the staleness the repository already accepts (no strict up-to-date policy).
# It rejects a base that never landed: an abandoned parent branch, or a release
# branch after a retarget to main.
#
# Runs with a read-only token. Needs contents:read, pull-requests:read, and
# statuses:read.
set -euo pipefail

: "${CONTEXT:?}" "${REPO:?}" "${MERGE_GROUP_HEAD_REF:?}" "${MERGE_GROUP_BASE_REF:?}" "${GH_TOKEN:?}"

# refs/heads/gh-readonly-queue/<target>/pr-<N>-<base sha>. The target can
# contain slashes (release/vX.Y), so anchor on the trailing "pr-<N>-<sha>".
if [[ "${MERGE_GROUP_HEAD_REF}" =~ /pr-([0-9]+)-[0-9a-f]{40}$ ]]; then
  PR_NUMBER="${BASH_REMATCH[1]}"
elif [[ "${MERGE_GROUP_HEAD_COMMIT_MESSAGE:-}" =~ \(#([0-9]+)\) ]]; then
  PR_NUMBER="${BASH_REMATCH[1]}"
else
  echo "::error::Cannot find a PR number in merge group ref '${MERGE_GROUP_HEAD_REF}'."
  exit 1
fi
TARGET="${MERGE_GROUP_BASE_REF#refs/heads/}"

pr_json="$(gh pr view "${PR_NUMBER}" --repo "${REPO}" --json headRefOid,isCrossRepository,author)"
HEAD_SHA="$(jq -r '.headRefOid' <<<"${pr_json}")"
IS_CROSS_REPO="$(jq -r '.isCrossRepository' <<<"${pr_json}")"
AUTHOR="$(jq -r '.author.login' <<<"${pr_json}")"
echo "PR #${PR_NUMBER} by ${AUTHOR}: head ${HEAD_SHA} -> ${TARGET}"

# Fork and Dependabot runs get a read-only token, so they cannot record.
if [[ "${IS_CROSS_REPO}" == "true" || "${AUTHOR}" == "app/dependabot" ]]; then
  echo "::warning::PR #${PR_NUMBER} runs with a read-only token and cannot record ${CONTEXT}. Skipping this check."
  exit 0
fi

record="$(gh api "repos/${REPO}/commits/${HEAD_SHA}/status" \
  | jq -r --arg ctx "${CONTEXT}" '.statuses[] | select(.context == $ctx) | .description')"
if [[ -z "${record}" ]]; then
  echo "::error::No ${CONTEXT} record on ${HEAD_SHA} (PR #${PR_NUMBER}). The pull_request run that produced this verdict predates the record step, or did not finish. Push a commit, or close and reopen the PR, to run it again. Then re-queue. 'Re-run jobs' does not help: it reuses the old base."
  exit 1
fi
TESTED_BASE="${record%% *}"
TESTED_REF="${record#* }"

# True when $1 is in the history of $2. The compare API reports base...head as
# "ahead" or "identical" only when base is an ancestor of head.
is_ancestor() {
  local status
  if ! status="$(gh api "repos/${REPO}/compare/${1}...${2}" --jq '.status' 2>/dev/null)"; then
    status="unknown"
  fi
  echo "compare ${1}...${2}: ${status}"
  [[ "${status}" == "ahead" || "${status}" == "identical" ]]
}

if is_ancestor "${TESTED_BASE}" "${TARGET}" || is_ancestor "${TESTED_BASE}" "${HEAD_SHA}"; then
  echo "${CONTEXT} for PR #${PR_NUMBER} ran against ${TESTED_BASE} (${TESTED_REF}). Accepted."
  exit 0
fi

echo "::error::${CONTEXT} for PR #${PR_NUMBER} ran against ${TESTED_BASE} (${TESTED_REF}), which is in neither ${TARGET} nor the PR's own history. That base never landed, so the verdict does not cover this merge. Rebase onto ${TARGET}, push, and re-queue."
exit 1

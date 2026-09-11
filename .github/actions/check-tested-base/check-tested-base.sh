#!/usr/bin/env bash
# Merge-queue guard for a required check whose real verdict comes from the
# pull_request event only (`required`, `playwright-required`).
#
# The pull_request run records the base it tested against as a commit status
# on the PR head (context = CONTEXT, description = "<base sha> <base ref>").
# This script accepts the verdict when that base has landed in the target
# branch, or when it is the tip of a parent PR that squash-merged into the
# target or is still open against it (a stack in flight). In each case the
# merged tree differs from the tested tree only by what the target gained
# since the test, which is the staleness the repository already accepts (no
# strict up-to-date policy). It rejects a base that never landed: an abandoned
# parent branch, or a release branch after a retarget to main.
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
# `gh pr view` reports GitHub App authors with an "app/" prefix.
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

# True when a chain of open same-repo PRs leads from head branch $1 to TARGET.
reaches_target() {
  local ref="$1" depth="${2:-0}" base
  [[ "${ref}" == "${TARGET}" ]] && return 0
  ((depth >= 10)) && return 1
  while IFS= read -r base; do
    [[ -z "${base}" ]] && continue
    echo "open PR chain: ${ref} -> ${base}"
    if reaches_target "${base}" $((depth + 1)); then
      return 0
    fi
  done < <(gh pr list --repo "${REPO}" --head "${ref}" --state open --limit 20 \
    --json baseRefName,isCrossRepository \
    --jq '.[] | select(.isCrossRepository == false) | .baseRefName')
  return 1
}

if is_ancestor "${TESTED_BASE}" "${TARGET}"; then
  echo "${CONTEXT} for PR #${PR_NUMBER} ran against ${TESTED_BASE} (${TESTED_REF}), which is in ${TARGET}. Accepted."
  exit 0
fi

# A stacked PR tests against its parent's tip. Under squash merge that tip
# never enters the target as-is, so look at the parent PR instead: the tested
# tip must be part of the parent's head, and the parent must have merged into
# the target or still be open against it.
parents="$(gh pr list --repo "${REPO}" --head "${TESTED_REF}" --state all --limit 20 \
  --json number,state,baseRefName,headRefOid,mergeCommit,isCrossRepository \
  --jq '[.[] | select(.isCrossRepository == false and (.state == "MERGED" or .state == "OPEN"))]
        | sort_by(.state)[]
        | [.number, .state, .baseRefName, .headRefOid, (.mergeCommit.oid // "")] | @tsv')"
while IFS=$'\t' read -r number state base head merge; do
  [[ -z "${number}" ]] && continue
  echo "parent PR #${number} (${state}): ${TESTED_REF} -> ${base}"
  if ! is_ancestor "${TESTED_BASE}" "${head}"; then
    continue
  fi
  if [[ "${state}" == "MERGED" && -n "${merge}" ]] && is_ancestor "${merge}" "${TARGET}"; then
    echo "${CONTEXT} for PR #${PR_NUMBER} ran against ${TESTED_BASE} (${TESTED_REF}); parent PR #${number} merged into ${TARGET}. Accepted."
    exit 0
  fi
  if [[ "${state}" == "OPEN" ]] && reaches_target "${base}"; then
    echo "${CONTEXT} for PR #${PR_NUMBER} ran against ${TESTED_BASE} (${TESTED_REF}); parent PR #${number} is open against ${TARGET}. Accepted."
    exit 0
  fi
done <<<"${parents}"

echo "::error::${CONTEXT} for PR #${PR_NUMBER} ran against ${TESTED_BASE} (${TESTED_REF}). That tip is not in ${TARGET}, and no PR from ${TESTED_REF} that contains it merged into or is open against ${TARGET}. The verdict does not cover this merge. Rebase onto ${TARGET}, push, and re-queue."
exit 1

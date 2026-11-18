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
# A PR with an open child PR skips the suite and records no verdict (see
# .github/actions/stack-position). Its verdict then comes from an open
# descendant whose passing run tested a head that contains this PR's head.
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

pr_json="$(gh pr view "${PR_NUMBER}" --repo "${REPO}" --json headRefName,headRefOid,isCrossRepository,author)"
HEAD_REF="$(jq -r '.headRefName' <<<"${pr_json}")"
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

# Verdict record of CONTEXT on commit $1: "<tested base sha> <tested base ref>".
verdict_on() {
  gh api "repos/${REPO}/commits/${1}/status" \
    | jq -r --arg ctx "${CONTEXT}" '.statuses[] | select(.context == $ctx) | .description'
}

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

# Open same-repo PRs, read once. Stacks can be dozens of PRs deep, so the walks
# below use this list instead of one API call for each level.
OPEN_PRS="$(gh pr list --repo "${REPO}" --state open --limit 2000 \
  --json number,headRefName,baseRefName,headRefOid,isCrossRepository \
  --jq '[.[] | select(.isCrossRepository == false)]')"
MAX_CHAIN_DEPTH=500

# True when a chain of open same-repo PRs leads from head branch $1 to TARGET.
reaches_target() {
  local ref="$1" depth=0
  while ((depth < MAX_CHAIN_DEPTH)); do
    [[ "${ref}" == "${TARGET}" ]] && return 0
    ref="$(jq -r --arg ref "${ref}" '[.[] | select(.headRefName == $ref) | .baseRefName] | first // empty' <<<"${OPEN_PRS}")"
    [[ -z "${ref}" ]] && return 1
    echo "open PR chain: -> ${ref}"
    depth=$((depth + 1))
  done
  return 1
}

# True when verdict record $1 ("<base sha> <base ref>") used a base that landed
# in TARGET, directly or through a parent PR.
base_landed() {
  local tested_base="${1%% *}" tested_ref="${1#* }" parents number state base head merge
  if is_ancestor "${tested_base}" "${TARGET}"; then
    echo "The verdict ran against ${tested_base} (${tested_ref}), which is in ${TARGET}."
    return 0
  fi

  # A stacked PR tests against its parent's tip. Under squash merge that tip
  # never enters the target as-is, so look at the parent PR instead: the tested
  # tip must be part of the parent's head, and the parent must have merged into
  # the target or still be open against it.
  parents="$(gh pr list --repo "${REPO}" --head "${tested_ref}" --state all --limit 20 \
    --json number,state,baseRefName,headRefOid,mergeCommit,isCrossRepository \
    --jq '[.[] | select(.isCrossRepository == false and (.state == "MERGED" or .state == "OPEN"))]
          | sort_by(.state)[]
          | [.number, .state, .baseRefName, .headRefOid, (.mergeCommit.oid // "")] | @tsv')"
  while IFS=$'\t' read -r number state base head merge; do
    [[ -z "${number}" ]] && continue
    echo "parent PR #${number} (${state}): ${tested_ref} -> ${base}"
    if ! is_ancestor "${tested_base}" "${head}"; then
      continue
    fi
    if [[ "${state}" == "MERGED" && -n "${merge}" ]] && is_ancestor "${merge}" "${TARGET}"; then
      echo "The verdict ran against ${tested_base} (${tested_ref}); parent PR #${number} merged into ${TARGET}."
      return 0
    fi
    if [[ "${state}" == "OPEN" ]] && reaches_target "${base}"; then
      echo "The verdict ran against ${tested_base} (${tested_ref}); parent PR #${number} is open against ${TARGET}."
      return 0
    fi
  done <<<"${parents}"
  echo "The verdict ran against ${tested_base} (${tested_ref}). That tip is not in ${TARGET}, and no PR from ${tested_ref} that contains it merged into or is open against ${TARGET}."
  return 1
}

own_record="$(verdict_on "${HEAD_SHA}")"
if [[ -n "${own_record}" ]] && base_landed "${own_record}"; then
  echo "${CONTEXT} for PR #${PR_NUMBER} accepted."
  exit 0
fi

# Open descendants of this PR, nearest first.
descendants() {
  local refs=("${HEAD_REF}") ref children
  local seen=0
  while ((${#refs[@]} > 0 && seen < MAX_CHAIN_DEPTH)); do
    ref="${refs[0]}"
    refs=("${refs[@]:1}")
    children="$(jq -r --arg ref "${ref}" '.[] | select(.baseRefName == $ref) | [.number, .headRefName, .headRefOid] | @tsv' <<<"${OPEN_PRS}")"
    while IFS=$'\t' read -r number head_ref head_sha; do
      [[ -z "${number}" ]] && continue
      printf '%s\t%s\n' "${number}" "${head_sha}"
      refs+=("${head_ref}")
      seen=$((seen + 1))
    done <<<"${children}"
  done
}

while IFS=$'\t' read -r number head_sha; do
  [[ -z "${number}" ]] && continue
  record="$(verdict_on "${head_sha}")"
  [[ -z "${record}" ]] && continue
  echo "descendant PR #${number} has a ${CONTEXT} verdict on ${head_sha}"
  if is_ancestor "${HEAD_SHA}" "${head_sha}" && base_landed "${record}"; then
    echo "${CONTEXT} for PR #${PR_NUMBER} accepted: descendant PR #${number} tested ${head_sha}, which contains ${HEAD_SHA}."
    exit 0
  fi
done < <(descendants)

if [[ -z "${own_record}" ]]; then
  echo "::error::No ${CONTEXT} verdict covers ${HEAD_SHA} (PR #${PR_NUMBER}). The PR has no verdict of its own, and no open descendant PR has a passing run that contains this head. Push the whole stack again, so that the stack tip runs, then re-queue. 'Re-run jobs' does not help: it reuses the old base."
else
  echo "::error::No ${CONTEXT} verdict covers this merge for PR #${PR_NUMBER}. Rebase onto ${TARGET}, push, and re-queue."
fi
exit 1

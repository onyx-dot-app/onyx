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
# That run tested the PR only together with the PRs up to the descendant, so
# all of them must be in the merge queue. A PR in a GitHub stack also merges
# only with every open PR of its stack (gh stack merge).
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

# PR numbers in the merge queue of TARGET, space separated, in QUEUED.
QUEUED=""
QUEUE_LOADED=false
load_queue() {
  if [[ "${QUEUE_LOADED}" != "true" ]]; then
    # shellcheck disable=SC2016 # GraphQL variables, not shell expansions.
    QUEUED=" $(gh api graphql \
      -f query='query($owner: String!, $name: String!, $branch: String!) {
        repository(owner: $owner, name: $name) {
          mergeQueue(branch: $branch) { entries(first: 100) { nodes { pullRequest { number } } } }
        }
      }' \
      -f owner="${REPO%%/*}" -f name="${REPO#*/}" -f branch="${TARGET}" \
      --jq '.data.repository.mergeQueue.entries.nodes[].pullRequest.number' | tr '\n' ' ')"
    QUEUE_LOADED=true
    echo "merge queue for ${TARGET}:${QUEUED}"
  fi
}

# The merge queue tests at most this many entries at once. A stack deeper than
# this cannot merge as one unit: its lower PRs wait for an entry that the queue
# does not start until they merge.
BUILD_LIMIT=""
load_build_limit() {
  if [[ -z "${BUILD_LIMIT}" ]]; then
    BUILD_LIMIT="$(gh api "repos/${REPO}/rules/branches/${TARGET}" \
      --jq '[.[] | select(.type == "merge_queue") | .parameters.max_entries_to_build] | first // empty')"
    : "${BUILD_LIMIT:?Cannot read max_entries_to_build of the ${TARGET} merge queue.}"
  fi
}

too_deep() {
  load_build_limit
  if (($1 > BUILD_LIMIT)); then
    echo "::error::PR #${PR_NUMBER} is in a stack of $1 PRs. The merge queue tests at most ${BUILD_LIMIT} entries at once, so this stack cannot merge as one unit. Split it into stacks of at most ${BUILD_LIMIT} PRs."
    return 0
  fi
  return 1
}

# Waits until the merge queue entries of the PRs in $1 pass their checks. $1
# lists "number:head sha" pairs, space separated; a PR whose head changed since
# the check counts as failed. GitHub merges the lower PRs of a stack even when
# an entry above them fails, and the stack tip's entry can pass while a PR
# below it fails. So a lower PR that relies on the tip's verdict waits for
# every PR up to the tip. The waits clear from the top down, one poll for each
# level. 80 polls of 20 seconds stay under the queue's 30-minute check timeout.
# Sets WAIT_FAILURE when it returns 1.
WAIT_FAILURE=""
wait_for_entries() {
  local pairs="$1" entries line pending pair pr sha attempt
  for attempt in $(seq 1 80); do
    # A failed read is not a removal: retry it, so one GitHub error does not
    # eject the whole stack.
    # shellcheck disable=SC2016 # GraphQL variables, not shell expansions.
    if ! entries="$(gh api graphql \
      -f query='query($owner: String!, $name: String!, $branch: String!) {
        repository(owner: $owner, name: $name) {
          mergeQueue(branch: $branch) {
            entries(first: 100) { nodes { state pullRequest { number headRefOid } } }
          }
        }
      }' \
      -f owner="${REPO%%/*}" -f name="${REPO#*/}" -f branch="${TARGET}" \
      --jq '.data.repository.mergeQueue.entries.nodes[] | "\(.pullRequest.number) \(.state) \(.pullRequest.headRefOid)"')"; then
      echo "Could not read the merge queue (${attempt}/80). Trying again."
      sleep 20
      continue
    fi
    pending=""
    for pair in ${pairs}; do
      pr="${pair%%:*}"
      sha="${pair#*:}"
      line="$(awk -v pr="${pr}" '$1 == pr' <<<"${entries}")"
      if [[ -z "${line}" ]]; then
        WAIT_FAILURE="PR #${pr} left the merge queue."
        return 1
      fi
      if [[ "${line##* }" != "${sha}" ]]; then
        WAIT_FAILURE="PR #${pr} changed its head while in the merge queue."
        return 1
      fi
      case "$(cut -d' ' -f2 <<<"${line}")" in
        MERGEABLE | LOCKED) ;;
        UNMERGEABLE)
          WAIT_FAILURE="PR #${pr} failed its merge queue checks."
          return 1
          ;;
        *) pending+=" #${pr}" ;;
      esac
    done
    if [[ -z "${pending}" ]]; then
      echo "Every PR up to the stack tip passed its merge queue checks."
      return 0
    fi
    echo "Waiting in the merge queue for${pending} (${attempt}/80)"
    sleep 20
  done
  WAIT_FAILURE="These PRs did not pass their merge queue checks in time:${pending}."
  return 1
}

# A PR in a GitHub stack merges only with the whole stack (gh stack merge),
# because the stack tip's run is the one that tests the PRs below it.
# shellcheck disable=SC2016 # GraphQL variables, not shell expansions.
stack_json="$(gh api graphql \
  -f query='query($owner: String!, $name: String!, $number: Int!) {
    repository(owner: $owner, name: $name) {
      pullRequest(number: $number) {
        stack { number entries(first: 100) { nodes { pullRequest { number state } } } }
      }
    }
  }' \
  -f owner="${REPO%%/*}" -f name="${REPO#*/}" -F number="${PR_NUMBER}" \
  --jq '.data.repository.pullRequest.stack')"
if [[ -n "${stack_json}" && "${stack_json}" != "null" ]]; then
  STACK_NUMBER="$(jq -r '.number' <<<"${stack_json}")"
  too_deep "$(jq '[.entries.nodes[].pullRequest | select(.state == "OPEN")] | length' <<<"${stack_json}")" && exit 1
  load_queue
  missing=""
  for pr in $(jq -r '.entries.nodes[].pullRequest | select(.state == "OPEN") | .number' <<<"${stack_json}"); do
    [[ "${QUEUED}" == *" ${pr} "* ]] || missing+=" #${pr}"
  done
  if [[ -n "${missing}" ]]; then
    echo "::error::PR #${PR_NUMBER} is in stack #${STACK_NUMBER}, and a stack merges only as one unit. These open PRs of the stack are not in the merge queue:${missing}. Merge the whole stack with: gh stack merge ${STACK_NUMBER}. To land only part of it, take the other PRs out of the stack first."
    exit 1
  fi
  echo "Every open PR of stack #${STACK_NUMBER} is in the merge queue."
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
# A branch can have open PRs against more than one base, so try every route.
reaches_target() {
  local queue=("$1") seen=" " ref next steps=0
  while ((${#queue[@]} > 0 && steps < MAX_CHAIN_DEPTH)); do
    ref="${queue[0]}"
    queue=("${queue[@]:1}")
    [[ "${ref}" == "${TARGET}" ]] && return 0
    [[ "${seen}" == *" ${ref} "* ]] && continue
    seen+="${ref} "
    steps=$((steps + 1))
    while IFS= read -r next; do
      [[ -z "${next}" ]] && continue
      echo "open PR chain: ${ref} -> ${next}"
      queue+=("${next}")
    done < <(jq -r --arg ref "${ref}" '.[] | select(.headRefName == $ref) | .baseRefName' <<<"${OPEN_PRS}")
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

# Open descendants of this PR, nearest first, as "number<TAB>head sha<TAB>chain",
# where chain lists the PR numbers from this PR's child down to the descendant.
descendants() {
  local refs=("${HEAD_REF}") chains=("") ref chain children number head_ref head_sha
  local seen=0
  while ((${#refs[@]} > 0 && seen < MAX_CHAIN_DEPTH)); do
    ref="${refs[0]}"
    chain="${chains[0]}"
    refs=("${refs[@]:1}")
    chains=("${chains[@]:1}")
    children="$(jq -r --arg ref "${ref}" '.[] | select(.baseRefName == $ref) | [.number, .headRefName, .headRefOid] | @tsv' <<<"${OPEN_PRS}")"
    while IFS=$'\t' read -r number head_ref head_sha; do
      [[ -z "${number}" ]] && continue
      printf '%s\t%s\t%s\n' "${number}" "${head_sha}" "${chain}${number} "
      refs+=("${head_ref}")
      chains+=("${chain}${number} ")
      seen=$((seen + 1))
    done <<<"${children}"
  done
}

# A descendant's verdict tested this PR together with every PR up to that
# descendant, so it covers this PR only when all of them are in the queue. This
# also covers a chain of PRs that is not a GitHub stack.
not_queued=""
not_passed=""
while IFS=$'\t' read -r number head_sha chain; do
  [[ -z "${number}" ]] && continue
  record="$(verdict_on "${head_sha}")"
  [[ -z "${record}" ]] && continue
  echo "descendant PR #${number} has a ${CONTEXT} verdict on ${head_sha}"
  if ! is_ancestor "${HEAD_SHA}" "${head_sha}" || ! base_landed "${record}"; then
    continue
  fi
  # shellcheck disable=SC2086 # chain is a space-separated list of PR numbers.
  set -- ${chain}
  too_deep "$(($# + 1))" && exit 1
  load_queue
  missing=""
  for pr in ${chain}; do
    [[ "${QUEUED}" == *" ${pr} "* ]] || missing+=" #${pr}"
  done
  if [[ -n "${missing}" ]]; then
    echo "PR #${number} tested this PR, but${missing} not in the merge queue."
    not_queued+=" #${number}"
    continue
  fi
  pairs=""
  for pr in ${chain}; do
    pairs+="${pr}:$(jq -r --argjson n "${pr}" '.[] | select(.number == $n) | .headRefOid' <<<"${OPEN_PRS}") "
  done
  if ! wait_for_entries "${pairs}"; then
    echo "PR #${number} tested this PR, but ${WAIT_FAILURE}"
    not_passed+=" ${WAIT_FAILURE}"
    continue
  fi
  echo "${CONTEXT} for PR #${PR_NUMBER} accepted: descendant PR #${number} tested ${head_sha}, which contains ${HEAD_SHA}, and passed in the merge queue with it."
  exit 0
done < <(descendants)

if [[ -n "${not_passed}" ]]; then
  echo "::error::PR #${PR_NUMBER} has no ${CONTEXT} verdict of its own, because it is in a stack, so it merges only when every PR up to the stack tip passes in the merge queue.${not_passed} Nothing in the stack merges. Fix the failing PR and merge the stack again: gh stack merge <stack number>."
  exit 1
fi

if [[ -n "${not_queued}" ]]; then
  echo "::error::PR #${PR_NUMBER} has no ${CONTEXT} verdict of its own, because it is in a stack. The run of${not_queued} tested it together with the PRs above it, so it can merge only with them. Merge the stack up to that PR as one unit: gh stack merge <PR number>."
  exit 1
fi

if [[ -z "${own_record}" ]]; then
  echo "::error::No ${CONTEXT} verdict covers ${HEAD_SHA} (PR #${PR_NUMBER}). The PR has no verdict of its own, and no open descendant PR has a passing run that contains this head. Push the whole stack again, so that the stack tip runs, then re-queue. 'Re-run jobs' does not help: it reuses the old base."
else
  echo "::error::No ${CONTEXT} verdict covers this merge for PR #${PR_NUMBER}. Rebase onto ${TARGET}, push, and re-queue."
fi
exit 1

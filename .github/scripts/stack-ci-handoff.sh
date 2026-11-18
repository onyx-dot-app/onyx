#!/usr/bin/env bash
# Moves the slow PR suites to the tip of a stack of PRs.
#
# A PR with an open child skips the integration and Playwright suites (see
# .github/actions/stack-position). When a PR gets its first child, this script
# cancels the PR's unfinished or failed runs and starts them again, so they
# skip. When a PR loses its last child, the PR is the tip again: if it has no
# verdict of its own, this script starts its runs again, so they test it.
set -euo pipefail

: "${GH_TOKEN:?}" "${REPO:?}" "${ACTION:?}" "${PR_NUMBER:?}"

# The event's base can be stale when a stack tool sets it after opening the PR.
BASE_REF="$(gh pr view "${PR_NUMBER}" --repo "${REPO}" --json baseRefName --jq .baseRefName)"

WORKFLOWS=(
  "pr-integration-tests.yml:ci/tested-base/integration"
  "pr-playwright-tests.yml:ci/tested-base/playwright"
)

same_repo_open_prs() {
  gh pr list --repo "${REPO}" "$@" --state open --json number,headRefOid,isCrossRepository \
    --jq '.[] | select(.isCrossRepository == false) | [.number, .headRefOid] | @tsv'
}

wait_until_completed() {
  local run_id="$1" attempt
  for attempt in $(seq 1 60); do
    if [[ "$(gh run view "${run_id}" --repo "${REPO}" --json status --jq .status)" == "completed" ]]; then
      return 0
    fi
    echo "Waiting for run ${run_id} to stop (${attempt}/60)"
    sleep 5
  done
  echo "::error::Run ${run_id} did not stop in 5 minutes."
  return 1
}

restart_run() {
  local run_id="$1" status="$2"
  if [[ "${status}" != "completed" ]]; then
    gh run cancel "${run_id}" --repo "${REPO}" || true
    wait_until_completed "${run_id}"
  fi
  gh run rerun "${run_id}" --repo "${REPO}"
  echo "Started run ${run_id} again."
}

# $1: branch whose PR gained or lost a child. $2: child-added or child-removed.
hand_off() {
  local parent_ref="$1" change="$2" parent head entry workflow context run run_id status conclusion
  parent="$(same_repo_open_prs --head "${parent_ref}" | head -n 1)"
  if [[ -z "${parent}" ]]; then
    echo "No open PR has head branch ${parent_ref}."
    return 0
  fi
  head="${parent#*$'\t'}"
  parent="${parent%%$'\t'*}"

  if [[ "${change}" == "child-removed" && -n "$(same_repo_open_prs --base "${parent_ref}")" ]]; then
    echo "PR #${parent} still has an open child. Its suites stay skipped."
    return 0
  fi

  for entry in "${WORKFLOWS[@]}"; do
    workflow="${entry%%:*}"
    context="${entry#*:}"
    run="$(gh run list --repo "${REPO}" --workflow "${workflow}" --branch "${parent_ref}" \
      --commit "${head}" --event pull_request --limit 1 \
      --json databaseId,status,conclusion --jq '.[0] | [.databaseId, .status, (.conclusion // "")] | @tsv')"
    if [[ -z "${run}" ]]; then
      echo "PR #${parent}: no ${workflow} run on ${head}."
      continue
    fi
    IFS=$'\t' read -r run_id status conclusion <<<"${run}"

    if [[ "${change}" == "child-added" ]]; then
      if [[ "${conclusion}" == "success" ]]; then
        echo "PR #${parent}: ${workflow} run ${run_id} already passed."
        continue
      fi
      echo "PR #${parent} has a child now. ${workflow} run ${run_id} (${status} ${conclusion}) starts again and skips."
    else
      if [[ -n "$(gh api "repos/${REPO}/commits/${head}/status" \
        | jq -r --arg ctx "${context}" '.statuses[] | select(.context == $ctx) | .context')" ]]; then
        echo "PR #${parent}: ${context} already has a verdict on ${head}."
        continue
      fi
      echo "PR #${parent} is the stack tip now. ${workflow} run ${run_id} starts again and tests it."
    fi
    restart_run "${run_id}" "${status}"
  done
}

case "${ACTION}" in
  opened | reopened)
    hand_off "${BASE_REF}" child-added
    ;;
  closed)
    hand_off "${BASE_REF}" child-removed
    ;;
  edited)
    if [[ -n "${OLD_BASE_REF:-}" ]]; then
      hand_off "${OLD_BASE_REF}" child-removed
      hand_off "${BASE_REF}" child-added
    fi
    ;;
  *)
    echo "Nothing to do for ${ACTION}."
    ;;
esac

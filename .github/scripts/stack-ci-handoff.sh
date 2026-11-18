#!/usr/bin/env bash
# Moves the slow PR suites to the tip of a stack of PRs.
#
# A PR with an open, ready child skips the slow suites (see
# .github/actions/stack-position). When a PR gets its first ready child, this
# script cancels the PR's unfinished or failed runs and starts them again, so
# they skip. When a PR loses its last ready child, the PR is the tip again: if
# its latest run skipped the suites, this script starts that run again, so it
# tests the PR. A draft child does not count, because a draft skips the suites.
set -euo pipefail

: "${GH_TOKEN:?}" "${REPO:?}" "${ACTION:?}" "${PR_NUMBER:?}"

# The event can be stale when a stack tool changes the PR after opening it.
pr="$(gh pr view "${PR_NUMBER}" --repo "${REPO}" --json baseRefName,isDraft)"
BASE_REF="$(jq -r .baseRefName <<<"${pr}")"
IS_DRAFT="$(jq -r .isDraft <<<"${pr}")"

# Each workflow runs the stack-position action and the step below in one job.
WORKFLOWS=(
  pr-integration-tests.yml
  pr-playwright-tests.yml
  pr-external-dependency-unit-tests.yml
  pr-craft-k8s-tests.yml
  pr-craft-compose-integration.yml
  pr-python-connector-tests.yml
)
SKIP_STEP="Skip the slow suites"

# Prints "number<TAB>head sha<TAB>draft" for each open same-repo PR.
same_repo_open_prs() {
  gh pr list --repo "${REPO}" "$@" --state open --json number,headRefOid,isCrossRepository,isDraft \
    --jq '.[] | select(.isCrossRepository == false) | [.number, .headRefOid, .isDraft] | @tsv'
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

# GitHub can answer a rerun with a 5xx error just after a cancel, so retry it.
restart_run() {
  local run_id="$1" status="$2" attempt
  if [[ "${status}" != "completed" ]]; then
    gh run cancel "${run_id}" --repo "${REPO}" || true
    wait_until_completed "${run_id}" || return 1
  fi
  for attempt in $(seq 1 5); do
    if gh run rerun "${run_id}" --repo "${REPO}"; then
      echo "Started run ${run_id} again."
      return 0
    fi
    echo "Rerun of run ${run_id} failed (${attempt}/5)."
    sleep 10
  done
  echo "::error::Could not start run ${run_id} again."
  return 1
}

# A failed restart does not stop the other workflows. The job fails at the end.
FAILED=0

# $1: branch whose PR gained or lost a ready child. $2: child-added or child-removed.
hand_off() {
  local parent_ref="$1" change="$2" parent head draft workflow run run_id status conclusion skipped
  parent="$(same_repo_open_prs --head "${parent_ref}" | head -n 1)"
  if [[ -z "${parent}" ]]; then
    echo "No open PR has head branch ${parent_ref}."
    return 0
  fi
  IFS=$'\t' read -r parent head draft <<<"${parent}"

  if [[ "${change}" == "child-removed" ]]; then
    if [[ "${draft}" == "true" ]]; then
      echo "PR #${parent} is a draft. Its suites stay skipped."
      return 0
    fi
    if same_repo_open_prs --base "${parent_ref}" | cut -f3 | grep -qx false; then
      echo "PR #${parent} still has a ready child. Its suites stay skipped."
      return 0
    fi
  fi

  for workflow in "${WORKFLOWS[@]}"; do
    run="$(gh run list --repo "${REPO}" --workflow "${workflow}" --branch "${parent_ref}" \
      --commit "${head}" --event pull_request --limit 1 \
      --json databaseId,status,conclusion --jq '.[0] // empty | [.databaseId, .status, (.conclusion // "")] | @tsv')"
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
      echo "PR #${parent} has a ready child now. ${workflow} run ${run_id} (${status} ${conclusion}) starts again and skips."
    else
      skipped="$(gh run view "${run_id}" --repo "${REPO}" --json jobs \
        | jq -r --arg step "${SKIP_STEP}" \
          '[.jobs[].steps[]? | select(.name == $step and .conclusion == "success")] | length')"
      if [[ "${skipped}" == "0" ]]; then
        echo "PR #${parent}: ${workflow} run ${run_id} did not skip the suites."
        continue
      fi
      echo "PR #${parent} is the stack tip now. ${workflow} run ${run_id} starts again and tests it."
    fi
    restart_run "${run_id}" "${status}" || FAILED=1
  done
}

case "${ACTION}" in
  opened | reopened | ready_for_review)
    if [[ "${IS_DRAFT}" == "true" ]]; then
      echo "PR #${PR_NUMBER} is a draft. It does not test its parent."
    else
      hand_off "${BASE_REF}" child-added
    fi
    ;;
  closed | converted_to_draft)
    hand_off "${BASE_REF}" child-removed
    ;;
  edited)
    if [[ -n "${OLD_BASE_REF:-}" && "${IS_DRAFT}" != "true" ]]; then
      hand_off "${OLD_BASE_REF}" child-removed
      hand_off "${BASE_REF}" child-added
    fi
    ;;
  *)
    echo "Nothing to do for ${ACTION}."
    ;;
esac
exit "${FAILED}"

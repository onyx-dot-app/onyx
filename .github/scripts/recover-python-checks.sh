#!/usr/bin/env bash
# Run from a trusted checkout with gh and jq. Supply the later, cancelled run ID.
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 || ! $1 =~ ^[1-9][0-9]*$ || ! $2 =~ ^[1-9][0-9]*$ || ( $# == 3 && $3 != --apply ) ]]; then
  echo "Usage: $0 PR_NUMBER CANCELLED_RUN_ID [--apply]" >&2
  exit 2
fi

repo=repos/onyx-dot-app/onyx
workflow='pr-python-checks.yml'
pr_number=$1
run_id=$2

skip() {
  echo "Skip: $1"
  exit 0
}

read_pr() {
  gh api "$repo/pulls/$pr_number" --jq '{
    number, state,
    head: (.head | {ref, sha, repo: {id: .repo.id}}),
    base: (.base | {ref, sha, repo: {id: .repo.id}})
  }'
}

pr=$(read_pr)
jq -e --argjson number "$pr_number" '
  .number == $number and .state == "open" and
  (.base.repo.id != null and .base.repo.id == .head.repo.id)
' <<< "$pr" >/dev/null || skip "PR must be open and in the same repository."

branch=$(jq -r '.head.ref | @uri' <<< "$pr")
read_pair() {
  # Read the whole branch, since a rerun shares concurrency with other heads.
  gh api "$repo/actions/workflows/$workflow/runs?branch=$branch&per_page=100" |
    jq -c --argjson pr "$pr" --argjson target "$run_id" '
      def ref: {ref, sha, repo: {id: .repo.id}};
      select(.total_count == (.workflow_runs | length))
      | .workflow_runs
      | select(all(.[]; .status == "completed"))
      | map(select(.head_sha == $pr.head.sha))
      | select(length == 2)
      | select(all(.[];
          .event == "pull_request" and .path == ".github/workflows/pr-python-checks.yml"
          and .head_branch == $pr.head.ref and .run_attempt == 1
          and (.pull_requests | map({number, head: (.head | ref), base: (.base | ref)}))
              == [($pr | del(.state))]))
      | sort_by(.run_number)
      | select(.[0].created_at != null and .[0].created_at == .[1].created_at)
      | select(.[0].run_number < .[1].run_number and .[1].id == $target
          and .[0].conclusion == "success" and .[1].conclusion == "cancelled")
      | .[0].id'
}

sibling=$(read_pair)
[[ -n $sibling ]] || skip "No eligible duplicate pair on the current PR."

# Attempt-specific endpoints keep the evidence tied to the original execution.
jobs="$repo/actions/runs"
cancelled_jobs=$(gh api "$jobs/$run_id/attempts/1/jobs?per_page=100")
jq -e '.total_count == 0 and .jobs == []' <<< "$cancelled_jobs" >/dev/null ||
  skip "The cancelled run created jobs."

passed_jobs=$(gh api "$jobs/$sibling/attempts/1/jobs?per_page=100")
jq -e '.total_count == (.jobs | length) and
  ([.jobs[] | select(.name == "mypy-check") | [.status, .conclusion]] == [["completed", "success"]])' \
  <<< "$passed_jobs" >/dev/null || skip "The sibling lacks a successful mypy-check."

if [[ $# == 2 ]]; then
  echo "Eligible: rerun Python Checks $run_id for PR #$pr_number. Repeat with --apply to submit."
  exit 0
fi

# GitHub has no conditional rerun endpoint. Refresh mutable evidence before POST.
current_sibling=$(read_pair)
current_pr=$(read_pr)
[[ $current_sibling == "$sibling" && $current_pr == "$pr" ]] || skip "PR or workflow state changed."
gh api --method POST "$jobs/$run_id/rerun"
echo "Requested Python Checks rerun $run_id for PR #$pr_number."

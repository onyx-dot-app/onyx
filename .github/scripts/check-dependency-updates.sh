#!/usr/bin/env bash
# Write the Slack alert for pending dependency updates. Fail when an update is past due or a check broke.
# Usage: check-dependency-updates.sh <ods-audit> <update policy file> <alert file>
set -euo pipefail

ods_audit="$1"
policy="$2"
alert="$3"
installer=backend/onyx/server/features/build/sandbox/image/install-browser.sh
repo_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}"
notify=.github/actions/slack-notify

mention() {
  local slack_id
  slack_id="$(jq -r --arg login "$1" 'to_entries[] | select(.value == $login) | .key' "${notify}/user-mappings.json")"
  if [ -n "$slack_id" ]; then echo "<@${slack_id}>"; else echo "$1"; fi
}

# One person owns each post: the first update PR's requested reviewer, or a random CVE reviewer when no PR has one.
fallback_reviewer="$(jq -r '.[]' "${notify}/cve-reviewers.json" | shuf -n 1)"
# This alert stays if a later command stops the script.
echo "$(mention "$fallback_reviewer") *The dependency update check failed.*" > "$alert"

latest="$(jq -r '.chrome.releases | keys | max_by(split(".") | map(tonumber))' "$policy")"
releases="$(python3 .github/scripts/supported-release-branches.py)"

lines=()
failed=0
# A pending update alerts once a day. A past-due update, a broken check, or a failed release observation alerts on every run.
urgent=false
reviewer=""
if [ "${OBSERVE_OUTCOME:-success}" != success ]; then
  lines+=("• Release observation failed. Deadlines use the last recorded release.")
  urgent=true
fi

while IFS= read -r base; do
  [ -n "$base" ] || continue
  echo "Checking ${base}"
  if ! installed="$(gh api "repos/${GITHUB_REPOSITORY}/contents/${installer}?ref=${base}" --jq .content | base64 --decode | sed -n 's/^version=//p')" || [ -z "$installed" ]; then
    lines+=("• *${base}*: could not read the installed Chrome version.")
    failed=1
    urgent=true
    continue
  fi
  # Success covers the first 24 hours after a release. A non-zero exit with JSON is a pending update.
  # With no output the check itself broke.
  if status="$("$ods_audit" updates --monitor --state "$policy" --package chrome --version "$installed")"; then
    continue
  fi
  if [ -z "$status" ]; then
    lines+=("• *${base}*: the update check failed for Chrome ${installed}.")
    failed=1
    urgent=true
    continue
  fi
  marker=""
  if jq -e '.blocking' <<< "$status" > /dev/null; then
    marker=" :rotating_light: *past due*"
    failed=1
    urgent=true
  fi
  pr=""
  if found="$(gh pr list --repo "$GITHUB_REPOSITORY" --base "$base" --head "auto/sandbox-browser/${base}" --state open --json url,reviewRequests --jq '.[0] // empty')" && [ -n "$found" ]; then
    pr="$(jq -r '.url' <<< "$found")"
    [ -n "$reviewer" ] || reviewer="$(jq -r '[.reviewRequests[].login // empty] | first // empty' <<< "$found")"
  fi
  lines+=("• *${base}*: Chrome ${installed}, latest ${latest}, $(jq -r '.message' <<< "$status")${marker}${pr:+ <${pr}|update PR>}")
done <<< "main"$'\n'"${releases}"

if [ "${#lines[@]}" -eq 0 ]; then
  rm -f "$alert"
  echo "No dependency update has been pending for 24 hours."
  exit 0
fi

{
  echo "$(mention "${reviewer:-$fallback_reviewer}") *Dependency updates need attention.* Merge each update PR. If a branch has no PR, check <${repo_url}/actions/workflows/update-sandbox-browser.yml|Update Sandbox Browser>."
  printf '%s\n' "${lines[@]}"
} > "$alert"
cat "$alert"

if [ "$urgent" = true ] || [ "${DAILY_POST:-false}" = true ]; then
  echo "post=true" >> "$GITHUB_OUTPUT"
fi

exit "$failed"

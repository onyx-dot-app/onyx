#!/usr/bin/env bash
# Write the Slack alert for pending dependency updates. Fail when an update is past due or a check broke.
# Usage: check-dependency-updates.sh <ods-audit> <update policy file> <alert file>
set -euo pipefail

ods_audit="$1"
policy="$2"
alert="$3"
installer=backend/onyx/server/features/build/sandbox/image/install-browser.sh
repo_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}"

latest="$(jq -r '.chrome.releases | keys | max_by(split(".") | map(tonumber))' "$policy")"
releases="$(python3 .github/scripts/supported-release-branches.py)"

lines=()
failed=0
# A repeated alert posts once. A broken check must alert on every run, so it is not stable.
stable=true
if [ "${OBSERVE_OUTCOME:-success}" != success ]; then
  lines+=("• Release observation failed. Deadlines use the last recorded release.")
  stable=false
fi

while IFS= read -r base; do
  [ -n "$base" ] || continue
  echo "Checking ${base}"
  if ! installed="$(gh api "repos/${GITHUB_REPOSITORY}/contents/${installer}?ref=${base}" --jq .content | base64 --decode | sed -n 's/^version=//p')" || [ -z "$installed" ]; then
    lines+=("• *${base}*: could not read the installed Chrome version.")
    failed=1
    stable=false
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
    stable=false
    continue
  fi
  marker=""
  if jq -e '.blocking' <<< "$status" > /dev/null; then
    marker=" :rotating_light: *past due*"
    failed=1
  fi
  pr="$(gh pr list --repo "$GITHUB_REPOSITORY" --base "$base" --head "auto/sandbox-browser/${base}" --state open --json url --jq '.[0].url // empty')" || pr=""
  lines+=("• *${base}*: Chrome ${installed}, latest ${latest}, $(jq -r '.message' <<< "$status")${marker}${pr:+ <${pr}|update PR>}")
done <<< "main"$'\n'"${releases}"

if [ "${#lines[@]}" -eq 0 ]; then
  echo "No dependency update has been pending for 24 hours."
  exit 0
fi

{
  echo "*Dependency updates need attention.* Merge each update PR. If a branch has no PR, check <${repo_url}/actions/workflows/update-sandbox-browser.yml|Update Sandbox Browser>."
  printf '%s\n' "${lines[@]}"
} > "$alert"
cat "$alert"

{
  echo "key=$(printf '%s\n' "${lines[@]}" | sha256sum | cut -d ' ' -f 1)"
  echo "stable=${stable}"
} >> "$GITHUB_OUTPUT"

exit "$failed"

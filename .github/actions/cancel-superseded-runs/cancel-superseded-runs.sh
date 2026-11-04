#!/usr/bin/env bash
# Cancels this workflow's older in-flight pull_request runs for HEAD_REF.
# Run ids grow with creation time, so only the newest run cancels the others.
set -euo pipefail

workflow_id="$(gh api "repos/${REPO}/actions/runs/${RUN_ID}" --jq '.workflow_id')"

# In-flight runs are the most recent ones, so the first page is enough.
older_runs="$(
  gh api --method GET "repos/${REPO}/actions/workflows/${workflow_id}/runs" \
    -f event=pull_request -f branch="${HEAD_REF}" -F per_page=100 \
    --jq ".workflow_runs[]
      | select(.status != \"completed\"
          and .id < ${RUN_ID}
          and .head_repository.full_name == \"${HEAD_REPO}\")
      | .id"
)"

if [ -z "${older_runs}" ]; then
  echo "No older in-flight runs for ${HEAD_REF}."
  exit 0
fi

for older_id in ${older_runs}; do
  echo "Cancelling superseded run ${older_id}"
  # A run that finished since the listing returns 409; that is not an error.
  gh api --method POST "repos/${REPO}/actions/runs/${older_id}/cancel" >/dev/null ||
    echo "::warning::Could not cancel run ${older_id}"
done

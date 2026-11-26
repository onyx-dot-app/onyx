#!/usr/bin/env bash
set -euo pipefail

workflow_path=${GITHUB_WORKFLOW_REF#"$GITHUB_REPOSITORY/"}
workflow_path=${workflow_path%@*}
api="repos/$GITHUB_REPOSITORY/actions"
zip=$(mktemp)
trap 'rm -f "$zip"' EXIT

if ! artifacts=$(timeout 8 gh api --method GET "$api/artifacts" \
    -f name="$ARTIFACT_NAME" -F per_page=25); then
  exit 0
fi

# Artifact names are caller-controlled. Check the producing run before reading it.
candidates=$(jq -r --argjson repo "$GITHUB_REPOSITORY_ID" --arg branch "$HEAD_BRANCH" '
  .artifacts[]
  | select(.expired == false and .size_in_bytes <= 1024)
  | select(.workflow_run.repository_id == $repo and .workflow_run.head_repository_id == $repo)
  | select(.workflow_run.head_branch == $branch)
  | [.id, .workflow_run.id] | @tsv
' <<< "$artifacts")

while IFS=$'\t' read -r artifact_id run_id; do
  [[ -n "$artifact_id" ]] || break
  if ! run=$(timeout 8 gh api "$api/runs/$run_id"); then
    break
  fi
  if ! jq -e --arg workflow "$workflow_path" --argjson pr "$PR_NUMBER" '
    .path == $workflow and .event == "pull_request"
    and any(.pull_requests[]; .number == $pr)
  ' <<< "$run" >/dev/null; then
    continue
  fi

  if curl --fail --silent --show-error --location --max-time 8 --max-filesize 1024 \
       -H "Authorization: Bearer $GH_TOKEN" \
       "$GITHUB_API_URL/$api/artifacts/$artifact_id/zip" -o "$zip" &&
     digest=$(unzip -p "$zip" digest | head -c 72) &&
     [[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] &&
     timeout 8 docker buildx imagetools inspect "$IMAGE_REPO@$digest" >/dev/null; then
    echo "Reusing $IMAGE_REPO@$digest from workflow run $run_id"
    echo "digest=$digest" >> "$GITHUB_OUTPUT"
    break
  fi
done <<< "$candidates"

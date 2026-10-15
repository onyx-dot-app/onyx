#!/usr/bin/env bash
# Fetch one page of a repo-wide comment listing to <corpus>/pages/<prefix>_<page>.jsonl.
# Usage: fetch_page.sh <corpus> <repo> <pulls/comments|issues/comments> <prefix> <page>
set -uo pipefail
OUT="$1" REPO="$2" kind="$3" prefix="$4" page="$5"
case "$kind" in
  pulls/comments)
    jq='.[] | {id, pr: (.pull_request_url | split("/") | last | tonumber), author: .user.login, path, line, original_line, start_line, side, diff_hunk, body, created_at, in_reply_to_id, html_url, commit_id}' ;;
  issues/comments)
    jq='.[] | {id, issue: (.issue_url | split("/") | last | tonumber), is_pr: (.html_url | test("/pull/")), author: .user.login, body, created_at, html_url}' ;;
  *) echo "unknown kind $kind" >&2; exit 2 ;;
esac
f="${OUT}/pages/${prefix}_$(printf %05d "$page").jsonl"
for attempt in 1 2 3 4 5; do
  if gh api "repos/${REPO}/${kind}?per_page=100&sort=created&direction=asc&page=${page}" --jq "$jq" > "$f.tmp" 2>"$f.err"; then
    mv "$f.tmp" "$f"; rm -f "$f.err"; exit 0
  fi
  sleep $((attempt * 5))
done
echo "FAILED ${kind} page ${page}: $(tail -1 "$f.err")" >&2
exit 1

# GraphQL Queries Reference

Useful GitHub GraphQL queries for merge-queue triage in onyx-dot-app/onyx.

## Real merge-queue status for a PR

`mergeStateStatus` and `autoMergeRequest` on their own can lag or mislead. Query the queue entry directly:

```bash
gh api graphql -f query='
{
  repository(owner: "onyx-dot-app", name: "onyx") {
    pullRequest(number: PR_NUMBER) {
      isInMergeQueue
      mergeQueueEntry {
        position
        state
      }
    }
  }
}'
```

`mergeQueueEntry: null` with `isInMergeQueue: false` means it isn't queued (either never enqueued, fell out after a force-push, or already merged/closed — check `state` separately).

## Check whether a failure is pre-existing on main

Before treating a failing check as "caused by this PR," see if the same check already fails on main's current HEAD:

```bash
gh api graphql -f query='
{
  repository(owner: "onyx-dot-app", name: "onyx") {
    object(expression: "main") {
      ... on Commit {
        checkSuites(first: 20) {
          nodes {
            checkRuns(first: 50, filterBy: {checkName: "CHECK_NAME"}) {
              nodes { name conclusion status }
            }
          }
        }
      }
    }
  }
}'
```

If it shows the same `FAILURE` there, the PR didn't cause it.

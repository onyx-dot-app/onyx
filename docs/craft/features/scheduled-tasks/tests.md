# Scheduled Tasks — Tests

Companion to [`overview.md`](./overview.md). Coverage is a single
Playwright smoke test plus a manual checklist for the properties that
aren't worth automating.

## E2E Smoke

`web/tests/e2e/scheduled-tasks.spec.ts` — one spec,
`create, run, and verify a run row exists`.

1. Log in as the standard worker user.
2. Navigate to `/craft/v1/tasks`. If the route redirects to `/app`, the
   Onyx Craft feature flag is off and the spec soft-skips.
3. Click the "New scheduled task" button (or fall back to
   `/craft/v1/tasks/new` if the list is in its empty state) and fill the
   create form: a unique name, the prompt `say hi`, and an interval
   schedule of every 5 minutes.
4. Save. Wait for the URL to settle on the detail page
   (`/craft/v1/tasks/<id>`) and assert the active-status chip
   (`task-status-active`) is visible — that's "task created."
5. Click `run-now-button` to trigger an immediate run.
6. Wait up to 60 s for a row with `data-run-status="succeeded"` or
   `="failed"` to appear in the run history. Either is fine — we're
   proving the dispatcher → executor → run-history wiring is reachable
   end-to-end. A timeout means the wiring is broken (or the
   scheduled-tasks Celery worker isn't running).

Selectors locked in by the spec — any rename in the frontend should
update them in lockstep: `new-task-button`, `task-name-input`,
`task-prompt-input`, `interval-every`, `save-task`, `task-status-active`,
`run-now-button`, plus the `data-run-status` attribute on run rows.

## Running

```bash
npx playwright test scheduled-tasks
```

Requires the full Onyx stack running locally: web, API, Postgres, Redis,
and the dedicated `celery_worker_scheduled_tasks` worker. Without the
worker the run never reaches a terminal state and the test times out at
step 6.

## What's Deliberately Not Automated

This is a smoke test. It does not exercise:

- `FOR UPDATE SKIP LOCKED` concurrency on the dispatcher.
- The stuck-run sweeper.
- The approval-required path.
- Sidebar filtering of scheduled-run sessions.
- Per-user ownership boundaries on the HTTP API.
- DST / IANA timezone behavior.

Those properties rely on review and the manual checklist below.

## Manual Smoke Checklist (before merging)

Drive these by hand once per material change to the dispatch / executor
path:

- **Every-2-min task vs an Onyx-search prompt.** Walk away for 6 minutes,
  come back, confirm three runs with complete sessions and sensible
  `summary` text.
- **`Europe/London` Mon/Wed/Fri 9 AM.** Verify `next_run_at` is correct
  across the BST/GMT boundary and a force-tick at 9 AM local fires.
- **Pause mid-fire.** In-flight run completes, no new fire scheduled.
  Resume → next fire is computed forward from `now()` (no backfire).
- **Approval boundary.** Run sits in `AWAITING_APPROVAL`, the
  notification bell shows the entry, interactive Craft on the same
  sandbox remains usable.
- **Kill worker mid-run.** Stop `celery_worker_scheduled_tasks` while a
  run is `RUNNING`. Within an hour the sweeper transitions it to
  `FAILED` with `error_class="stuck"`.

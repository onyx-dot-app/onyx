# Scheduled Tasks — Tests

Companion to [`overview.md`](./overview.md). Lays out what each test
covers, where it lives, and which behaviors it locks in. The bulk of the
value is in the external-dependency unit layer — those tests run the real
DB and exercise actual SQL (FOR UPDATE SKIP LOCKED, indexes, run-row
state machine) while stubbing the slow / external bits (sandbox
provisioning, LLM, Celery enqueue).

## Test Layering

| Layer                    | Location                                                                | What it proves                                                  |
| ------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------------- |
| External-dep unit (core) | `backend/tests/external_dependency_unit/scheduled_tasks/`               | Dispatcher, executor, sweeper, sidebar filter against real DB.  |
| External-dep unit (API)  | `backend/tests/external_dependency_unit/craft/test_scheduled_tasks_api.py` | FastAPI handlers called directly: CRUD, run-now, banner.    |
| Playwright (E2E)         | `web/tests/e2e/scheduled-tasks.spec.ts`                                 | One full UI lifecycle: create → run-now → banner → pause/resume. |
| Manual smoke             | (checklist below)                                                       | DST / approval / crash-safety properties that aren't worth automating. |

No standard integration test was written: the API + dispatcher + executor
layers are already covered by external-dep unit tests with the real DB,
and the Playwright spec exercises the UI seam. Adding an integration test
would duplicate one of those without adding coverage.

## Backend — Dispatcher

`backend/tests/external_dependency_unit/scheduled_tasks/test_dispatch.py`

Direct invocation of `dispatch_due_scheduled_tasks.run(tenant_id=...)`
with the Celery `send_task` patched at the dispatcher's import site, so
no worker is contacted. The dispatcher writes rows to the real DB and the
assertions read them back.

Test classes:

- **`TestDispatcherClaims`**
  - `test_due_tasks_get_queued_run_rows` — two due tasks → two `QUEUED`
    `ScheduledTaskRun` rows with `trigger_source=SCHEDULED`,
    `next_run_at` advanced past now for each task.
  - `test_paused_and_deleted_tasks_not_claimed` — `PAUSED` and
    `deleted=true` rows with `next_run_at` in the past are excluded by
    the claim query, while an `ACTIVE` peer is picked up.
  - `test_prior_in_flight_writes_skipped_row` — when a prior run for the
    same task is `RUNNING`, the next dispatch inserts a `SKIPPED` row
    with `skip_reason="prior_in_flight"` and still advances
    `next_run_at` (recurring fires never get behind).
- **`TestDispatcherConcurrency`**
  - `test_parallel_ticks_claim_each_row_once` — two threads on separate
    sessions call the dispatcher behind a `threading.Barrier`. Exactly
    one `QUEUED` row is written for the contended task, which is the
    operational property `FOR UPDATE SKIP LOCKED` is there to provide.

Shared assertion style: filters runs by `task_id` (`_all_runs_for_task`)
rather than counting globally, because the DB is shared across tests in
the package — the dispatcher legitimately picks up leftover due rows
from sibling tests too. We assert facts about the rows we own, and use
`>=` on counts where leftovers may show up.

## Backend — Executor

`backend/tests/external_dependency_unit/scheduled_tasks/test_executor.py`

Calls `run_scheduled_task_logic(run_id)` directly against the real DB.
Two stubs replace the truly external bits:

- `SessionManager.create_session__no_commit` is patched to a thin DB
  insert that respects the requested `origin`, so we don't have to
  provision a real sandbox / allocate ports / mkdir document directories.
- `SessionManager._yield_acp_events` is patched per-test to emit a
  controlled list of ACP events (or raise mid-stream).

Test classes:

- **`TestExecutorHappyPath.test_success_writes_messages_and_summary`** —
  end-to-end happy path: run transitions `QUEUED → RUNNING → SUCCEEDED`,
  `session_id` populated, `BuildSession.origin == SCHEDULED`, exactly one
  `MessageType.USER` row containing `task.prompt`, accumulated
  `agent_message` text concatenates the stream chunks, `run.summary` is
  populated. Verifies the executor uses the shared `_persist_acp_events`
  consumer (so transcripts match interactive runs).
- **`TestExecutorApprovalGate.test_approval_required_marks_awaiting`** —
  emitting a `RequestPermissionRequest` event ends the run in
  `AWAITING_APPROVAL` (not `SUCCEEDED`), `session_id` is set, anything
  after the gate is dropped, and a `SCHEDULED_TASK_AWAITING_APPROVAL`
  `Notification` is written for the task author.
- **`TestExecutorFailure.test_exception_marks_failed_and_notifies`** —
  raising mid-stream lands the run in `FAILED` with `error_class` and a
  descriptive `error_detail`; a `SCHEDULED_TASK_FAILED` `Notification`
  is emitted.
- **`TestExecutorIdempotency.test_already_terminal_run_is_noop`** —
  pre-marking a run `SUCCEEDED` and seeding a poison-pill stream (which
  would raise if iterated) lets us prove the executor short-circuits on
  non-`QUEUED` rows. Important: protects against double-execution if
  Celery redelivers (worker died after committing the run but before
  acking the message).

## Backend — Stuck-run Sweeper

`backend/tests/external_dependency_unit/scheduled_tasks/test_sweeper.py`

- `test_old_queued_and_running_marked_failed_fresh_left_alone` — seeds
  three runs around the `STUCK_QUEUED_OLDER_THAN` /
  `STUCK_RUNNING_OLDER_THAN` thresholds and runs
  `cleanup_stuck_scheduled_runs.run(tenant_id=...)`. The two old rows
  flip to `FAILED` with `error_class="stuck"` and `error_detail`
  mentioning which threshold tripped; the fresh row is untouched. Why
  this matters: catches the "worker died mid-run" / "queue backed up so
  long the executor would be a no-op anyway" cases without any cron
  introspection of worker state.

## Backend — Sidebar Filter

`backend/tests/external_dependency_unit/scheduled_tasks/test_sidebar_filter.py`

- `TestSidebarOriginFilter.test_only_interactive_sessions_listed` —
  inserts one `INTERACTIVE` `BuildSession` and one `SCHEDULED`
  `BuildSession` for the same user (each with a user message so the
  sidebar's "has messages" filter matches). `get_user_build_sessions`
  returns only the interactive id. This is the single test that
  guarantees scheduled fires don't leak into the Craft sidebar — without
  it the executor's `origin=SCHEDULED` wiring or the sidebar query's
  filter could silently regress.

## Backend — HTTP API

`backend/tests/external_dependency_unit/craft/test_scheduled_tasks_api.py`

FastAPI route functions are called directly with a constructed `User` and
the test `db_session` (same pattern as
`permission_sync/test_cc_pair_sync_attempts_routes.py`); the Celery
enqueue is patched at the API module's import site, so no worker is
involved. The DB is real.

- **`TestCRUDHappyPath`**
  - `test_full_crud_lifecycle` — `create_task` → `list_scheduled_tasks`
    → `get_task` → `patch_task` (name + pause/resume) → soft `delete_task`.
    Verifies `next_run_at` is recomputed on resume and the soft-deleted
    row drops out of list/get.
- **`TestRunImmediatelyAndRunNow`**
  - `test_create_with_run_immediately_inserts_run_and_enqueues` — the
    `run_immediately` flag on create inserts a `QUEUED` run with
    `trigger_source=MANUAL_RUN_NOW` and enqueues
    `run_scheduled_task(run_id)` with the expected args.
  - `test_run_now_on_paused_task_inserts_run_and_does_not_touch_next_run_at` —
    Run Now works while the task is paused (off-schedule manual fire)
    and explicitly leaves `next_run_at` alone.
- **`TestPatchRecomputesNextRunAt`**
  - `test_timezone_change_recomputes_next_run_at` — patching the
    timezone alone recomputes `next_run_at` against the new IANA zone.
  - `test_status_paused_clears_next_run_at_and_resume_recomputes` —
    pause sets `next_run_at` to NULL; resume recomputes from `now()`.
- **`TestListRuns`**
  - `test_pagination_60_runs` — inserts 60 runs, verifies first page is
    `RUNS_DEFAULT_PAGE_SIZE` rows in newest-first order with
    `next_cursor` set; second page returns the remainder with
    `next_cursor=None`.
  - `test_other_users_task_returns_not_found` — ownership boundary: a
    second user calling `/runs` on the first user's task gets
    `OnyxErrorCode.NOT_FOUND`, not `FORBIDDEN` (don't leak existence).
- **`TestScheduledRunContext`**
  - `test_returns_context_when_session_linked_to_owned_run` — a
    `BuildSession` whose id is referenced by a run the caller owns
    returns `{task_id, task_name, started_at}` for the banner.
  - `test_returns_not_found_for_unrelated_session` — sessions with no
    backing run → 404.
  - `test_returns_not_found_for_other_users_run` — owning the session
    but not the underlying task → 404.

## Frontend — Playwright

`web/tests/e2e/scheduled-tasks.spec.ts`

One spec: **`create, run-now, banner, pause/resume lifecycle`**.

- Logs in as the standard worker user; if `/craft/v1/tasks` redirects to
  `/app` the test soft-skips (Onyx Craft feature flag off).
- Fills the create form: name, prompt, interval = 5 minutes. Saves.
- Lands on the detail page, sees `task-status-active`, clicks `run-now-button`.
- Waits up to 60 s for a `data-run-status="succeeded"` or `="failed"`
  row. If neither shows up in time, the spec annotates a soft-skip
  rather than failing — the scheduled-tasks Celery worker isn't
  guaranteed to be up in every CI environment.
- On `succeeded`: clicks the row, confirms the `scheduled-run-banner`
  and `back-to-task-button` render, and asserts the chat input is
  still present (follow-ups remain allowed on scheduled-run sessions).
- Pause / resume via `status-toggle`, then deletes for cleanup.

Selectors are pinned to `data-testid` (`task-name-input`,
`task-prompt-input`, `interval-every`, `save-task`, `run-now-button`,
`task-status-active`, `task-status-paused`, `status-toggle`,
`scheduled-run-banner`, `back-to-task-button`, `delete-button`,
`confirm-delete-task`). Any rename in the frontend should update these
hooks in lockstep.

## Test Fixtures

Local to `backend/tests/external_dependency_unit/scheduled_tasks/conftest.py`:

- `db_session`, `tenant_context`, `test_user` — re-exported from the
  craft conftest pattern so the package can be invoked on its own.
- `running_sandbox` — inserts a `Sandbox` row in `RUNNING` state for the
  test user; the executor refuses to run without one.
- `make_task` — factory keyword-arg defaults: `cron_expression="*/5 * * * *"`,
  `timezone="UTC"`, `editor_mode="interval"`, `status=ACTIVE`,
  `next_run_at = now()` (so the dispatcher claims it immediately).
  Callers override any of these.

The executor tests additionally use two `autouse` patches:

- `_stub_sandbox_manager` — replaces `get_sandbox_manager()` so
  `SessionManager.__init__` doesn't try to validate venv / template paths.
- `_stub_create_session` — replaces `create_session__no_commit` with a
  direct DB insert that respects the requested `origin`.

## Manual Smoke Checklist (before merging)

Cases not worth automating but worth driving by hand once per material
change to the dispatch / executor path:

- **Every-2-min task vs an Onyx-search prompt.** Walk away for 6 minutes,
  come back, confirm three runs with complete sessions and sensible
  `summary` text. Catches "the worker quietly stopped accepting work."
- **`Europe/London` Mon/Wed/Fri 9 AM.** Verify `next_run_at` is correct
  across the BST/GMT boundary and a force-tick at 9 AM local fires.
  Catches timezone bugs that unit tests with frozen clocks miss.
- **Pause mid-fire.** In-flight run completes, no new fire scheduled.
  Resume → next fire computed forward from `now()`, no backfire.
- **Approval boundary.** Run sits in `AWAITING_APPROVAL`, notification
  appears in the bell, interactive Craft on the same sandbox is still
  usable (no lease leaked).
- **Kill worker mid-run.** Stop the `celery_worker_scheduled_tasks`
  process while a run is in `RUNNING`. Within an hour the sweeper
  transitions it to `FAILED` with `error_class="stuck"`.

## Running the Suites

```bash
# External-dependency unit tests (real Postgres / Redis / etc.)
python -m dotenv -f .vscode/.env run -- \
  pytest backend/tests/external_dependency_unit/scheduled_tasks/ \
         backend/tests/external_dependency_unit/craft/test_scheduled_tasks_api.py

# Playwright (full stack must be running)
npx playwright test scheduled-tasks
```

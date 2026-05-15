# Scheduled Tasks

## Objective

Implement the **Scheduled Tasks** product surface in
[`docs/product/scheduled-tasks.md`](../../../product/scheduled-tasks.md): a user
saves a prompt + schedule, and the system runs the prompt as Craft on a
timer. Every fire creates a brand-new Craft session, executes the agent
headlessly, and records what happened.

V1 = schedule-only, single-user, no event triggers, no live-attach. The bar:
a user creates a task in `/craft/v1/tasks`, sees it fire without their
browser open, and clicks any past run to open the completed session.

## Important Notes

- **A run IS a `BuildSession`.** `scheduled_task_run.session_id` is a FK to
  `build_session.id`. Clicking a finished run opens the existing session
  view — no new transcript UI. Settled in the main plan (decision 3).
- **Every fire creates a fresh session** via the existing
  `SessionManager.create_session__no_commit` path, so sandbox provisioning,
  workspace setup, skills materialization, AGENTS.md generation, and packet
  logging run unchanged.
- **Headless executor reuses `send_message`'s persistence half.** Split
  `_stream_cli_agent_response` into `_yield_acp_events` (pure ACP generator)
  + `_persist_acp_events` (`BuildStreamingState` consumer writing
  `BuildMessage` rows). SSE endpoint composes the pair with an SSE
  formatter; executor wraps it with a drain-to-completion. Identical
  transcripts, no duplicated code.
- **Dedicated `scheduled_tasks` Celery worker — executor only.** The
  long-running executor (`run_scheduled_task`) runs on a new
  `celery_worker_scheduled_tasks` process registered in supervisord, the
  dev runner, and the Helm chart. Headless agent fires are long-running
  (LLM + tool calls in a sandbox), so colocating them on `heavy`
  (pruning, perms-sync, csv-export) would let a small handful of fires
  starve the rest of the heavy queue. Dedicated worker = isolated thread
  pool, isolated HPA / KEDA scaling, and its own Prometheus port (9098).
  The dispatcher and stuck-run sweeper are pure DB coordination work and
  run on the **primary** queue instead — routing them to the dedicated
  pool would let a saturated executor stall dispatch.
- **Schedule storage:** `(cron_expression, IANA timezone, editor_mode)`.
  All three editor modes compile to cron on save. `croniter` +
  `ZoneInfo(timezone)` handles DST. `editor_mode` is a UI hint only.
  `next_run_at` recomputed on every fire and every edit; pause sets it to
  NULL.
- **Concurrency:** `SKIP_IF_RUNNING` for recurring fires (prior run still
  in flight → write `skipped` row with `skip_reason`, still advance
  `next_run_at`), `QUEUE_ONE` for Run Now (works when paused, doesn't
  touch `next_run_at`).
- **Runs execute as the task author.**
  `create_session__no_commit(user_id=task.user_id)` — skills, Onyx search,
  OAuth grants, approval policies all flow through the same user-scoped
  paths the interactive UI uses.
- **Soft-delete preserves history.** `deleted=true` stops dispatch; runs
  and sessions stay so users can open past runs from the task's run
  history.
- **`BuildSession.origin` keeps scheduled runs out of the sidebar.** New
  enum column (`INTERACTIVE | SCHEDULED`, default `INTERACTIVE`, server
  default `'interactive'` for existing rows). Set at session-create time
  by the executor; the sidebar query filters `origin = INTERACTIVE`.
  Covers both scheduled fires and Run Now (both go through the executor
  with `origin=SCHEDULED`). A column beats a `NOT EXISTS` against
  `scheduled_task_run` because the dispatcher writes its run row before
  the executor creates the session — a join-based filter would briefly
  leak. Future non-interactive origins (eval runs, automation) reuse the
  same seam.
- **No retries in V1.** Failed = one row; user clicks Run now or waits.
- **Notifications piggyback on the existing `Notification` model.** Two new
  types (`SCHEDULED_TASK_FAILED`, `SCHEDULED_TASK_AWAITING_APPROVAL`). No
  email, no Slack (product req 9).
- **Stuck-run sweeper** (hourly): `queued > 15 min` and `running > budget`
  → `failed (stuck)`. Catches dead workers.
- **Out of scope:** live-attach, event triggers, shared tasks, templates,
  retry policy, budget caps, run diffing, calendar view, auto-disable on
  N failures, external task-management API.

## Architecture

```
Beat (30s, per tenant)                Celery "scheduled_tasks" queue
Primary queue                         (served by celery_worker_scheduled_tasks)
──────────────────────                ────────────────────────────────
dispatch_due_scheduled_tasks          run_scheduled_task(run_id)
  BEGIN;                                if run.status != 'queued': return
   SELECT FROM scheduled_task           mark 'running'
     WHERE active AND due               session = SessionManager
     FOR UPDATE SKIP LOCKED;              .create_session__no_commit(
   for each row:                              user_id=task.user_id)
     ├─ if prior run in flight         run.session_id ← session.id
     │     → insert skipped row         for event in _yield_acp_events(
     ├─ insert queued run                  session, task.prompt):
     ├─ next_run_at = croniter             _persist_acp_events([event])
     │     .next(now, tz=task.tz)        if budget exceeded → failed
     └─ enqueue run_scheduled_task ───►   if approval required →
            (run_id, expires=900,             awaiting_approval
             queue=scheduled_tasks)       mark succeeded / failed
  COMMIT;                                emit Notification if failed

Stuck-run sweep (hourly, primary queue)
──────────────────────                          │
cleanup_stuck_scheduled_runs                    ▼
  queued > 15m → failed (stuck)        BuildMessage rows (existing tables,
  running > budget → failed (timeout)   written by shared persist consumer)
```

## Data Model

```python
class SessionOrigin(str, Enum):              # interactive, scheduled
                                             # added to BuildSession; default INTERACTIVE

class ScheduledTaskStatus(str, Enum):       # active, paused
class ScheduledTaskRunStatus(str, Enum):    # queued, running, succeeded,
                                            # failed, skipped, awaiting_approval
class ScheduledTaskTriggerSource(str, Enum): # scheduled, manual_run_now

class ScheduledTask(Base):
    __tablename__ = "scheduled_task"
    id, user_id (FK user, CASCADE)
    name (str), prompt (text)
    cron_expression (str), timezone (IANA str), editor_mode (str)
    status (enum, default ACTIVE)
    next_run_at (DateTime tz, nullable)      # dispatcher's only read field
    deleted (bool, default False)
    created_at, updated_at
    runs ← back-populated, cascade all,delete-orphan
    __table_args__ = (
        Index("ix_scheduled_task_dispatch", "status", "deleted", "next_run_at"),
        Index("ix_scheduled_task_user_created", "user_id", desc("created_at")),
    )

class ScheduledTaskRun(Base):
    __tablename__ = "scheduled_task_run"
    id, task_id (FK scheduled_task, CASCADE)
    session_id (FK build_session, SET NULL)   # populated after executor creates session
    status (enum, default QUEUED), trigger_source (enum)
    skip_reason / error_class / error_detail (nullable)
    started_at (default now), finished_at (nullable)
    summary (str, ~120 chars of final agent message)
    __table_args__ = (
        Index("ix_scheduled_task_run_task_started", "task_id", desc("started_at")),
        Index("ix_scheduled_task_run_status", "status"),
    )
```

`next_run_at` is the only field the dispatcher reads — pause sets it NULL,
edit recomputes, `deleted=true` excludes from claims. `session_id` is
nullable for the brief moment between dispatcher INSERT and executor's
session create. No `attempts` counter (no retries in V1).

## API Spec

All endpoints raise `OnyxError`; typed FastAPI returns. Mounted at
`/api/build/scheduled-tasks` (existing `/build` prefix,
`require_onyx_craft_enabled` gating). Scoped to the authenticated user; no
admin view in V1.

- `GET    /scheduled-tasks` — list payload (id, name, human-readable
  schedule, status, next_run_at, last_run summary).
- `POST   /scheduled-tasks` — create. Compiles editor input → cron,
  validates timezone via `ZoneInfo`. Optional `run_immediately`.
- `GET    /scheduled-tasks/{id}` — task + next 3 fire times for UI preview.
- `PATCH  /scheduled-tasks/{id}` — partial edit. Recomputes `next_run_at` on
  schedule/timezone change. `paused` → NULL; resume → recompute. In-flight
  runs untouched.
- `DELETE /scheduled-tasks/{id}` — soft-delete.
- `POST   /scheduled-tasks/{id}/run-now` — inserts `manual_run_now` run,
  enqueues executor. Works when paused. Doesn't touch `next_run_at`.
- `GET    /scheduled-tasks/{id}/runs` — paginated, 50/page, `cursor=`,
  newest first.
- `GET    /build/sessions/{id}/scheduled-run-context` — optional task name +
  id + scheduled `started_at` if the session is from a scheduled run; 404
  otherwise. Used by the session-view banner.

No live-attach endpoint in V1.

## Schedule Semantics

5-field cron + IANA timezone, stored canonical. Editor mode is a UI hint.

- *Interval (N min/hr/day):* `*/N * * * *` / `0 */N * * *` / `M H */N * *`
  (M:H is the editor's required time-of-day for day-cadence).
- *Daily/weekly:* `M H * * <weekdays>` (e.g. `0 9 * * 1,3,5`).
- *Advanced:* user-typed, validated via `croniter`.

`compute_next_run_at` = `croniter(cron,
after).get_next(datetime, tzinfo=ZoneInfo(tz))`. Stored UTC; compared UTC
in dispatch. `ZoneInfo` handles DST — a 9 AM PT weekly fire stays 9 AM
local across PST/PDT.

Pause mid-fire: in-flight run completes, `next_run_at`→NULL. Resume:
recompute from resume time (no backfire). Past-due tasks fire once and
advance forward (standard cron). Cron with no future fires → reject at
PATCH/POST.

## Run Lifecycle

```
queued ─► running ─► succeeded
            │   └─► failed (executor crash | budget | ACP error)
            └─► awaiting_approval ─► (approvals project resumes) ─► running ─► ...

dispatcher also writes: skipped (prior run still in flight; next_run_at advances)
```

Resume mechanics for `awaiting_approval` are owned by the approvals
project; until that ships, treat as terminal-for-display.

Multiple scheduled runs and the interactive `send_message` path can
execute against the same sandbox concurrently — there is no
serialization lease.

## UI

- **List (`/craft/v1/tasks`):** name, schedule, status, last_run (relative
  time + success/failure icon), next_run, row actions (Run now,
  Pause/Resume, Edit, Delete). Empty state shows three starter prompts
  from the product doc.
- **Editor (`/new`, `/:id/edit`):** single form, three-tab segmented
  control for schedule mode. Prompt field reuses the Craft chat input
  (product req 10). Live "next 3 runs" preview computed client-side via
  `cron-parser`.
- **Detail (`/:id`):** header (name, schedule, status toggle, next_run,
  action buttons) + paginated run history table. Row click → session view
  for `succeeded`/`failed`; non-clickable with tooltip for
  `queued`/`running`/`awaiting_approval`/`skipped`.
- **Session view banner:** when the scheduled-run-context endpoint returns
  a result, render "This session was started by scheduled task X at Y. ←
  Back to task." above the transcript. The chat input stays available —
  users can send follow-up messages on a scheduled-run session.
- **Notifications:** two new bell entries — "Task X failed", "Task X needs
  approval" — deep-linking to the run row.
- **Mobile:** list/detail tolerable; editor explicitly requires desktop
  (product req 8).

## Tests

See [`tests.md`](./tests.md) for the testing plan, the layout of the
existing test suites, and the manual smoke checklist.

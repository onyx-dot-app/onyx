# Craft Scheduled Tasks

> Lets a user schedule a Craft prompt to run on a timer instead of typing it
> by hand. Each fire creates a brand-new headless session, runs the agent
> without anyone watching, and records what happened for later review.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** craft
**Edition:** CE
**Owns:**
`backend/onyx/server/features/build/scheduled_tasks/` (`api.py`,
`executor.py`, `schedule.py`), `backend/onyx/db/scheduled_task.py`,
`backend/onyx/background/celery/apps/scheduled_tasks.py`,
`backend/onyx/background/celery/tasks/scheduled_tasks/tasks.py`,
`backend/onyx/background/celery/configs/scheduled_tasks.py`

**Read first:** `docs/craft/features/scheduled-tasks/overview.md`. It is the
product plan and architecture diagram this document maps to code and
verifies against. `docs/craft/features/scheduled-tasks/pre-approvals.md` is
the design for the security-sensitive piece in §4.4. Both are implemented
designs, not aspirational, except where noted (§9).

---

## 1. What the user experiences

A user writes a prompt, picks a schedule (an interval, a daily/weekly
cadence, or a raw cron expression), and saves it at `/craft/v1/tasks`. From
then on, the task fires on its own: a fresh Craft session runs the prompt
headlessly, and the user can click "Run now" to fire it immediately without
waiting.

Every past run shows up in the task's run history. Clicking a finished run
opens the same session view used for an interactive chat; there is no
separate "run detail" screen. If a run needs an approval the task wasn't
configured to grant, or if it fails outright, the user gets a notification.
Scheduled runs never clutter the normal Craft session sidebar.

---

## 2. Surfaces

### HTTP endpoints (router prefix `/build/scheduled-tasks`, `api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/scheduled-tasks` | `list_scheduled_tasks` | User-scoped list: name, schedule, status, `next_run_at`, last run summary. |
| POST | `/scheduled-tasks` | `create_task` | Compiles editor input to cron via `schedule.compile_to_cron`. |
| GET | `/scheduled-tasks/{id}` | `get_task` | Task detail plus next 3 fire times. |
| PATCH | `/scheduled-tasks/{id}` | `patch_task` | Partial edit; recomputes `next_run_at` on a schedule change; pause sets it NULL. |
| DELETE | `/scheduled-tasks/{id}` | `delete_task` | Soft delete (`deleted=true`); history is preserved. |
| POST | `/scheduled-tasks/{id}/run-now` | `run_now` | Enqueues an out-of-band run; works even while paused; does not touch `next_run_at`. |
| GET | `/scheduled-tasks/{id}/runs` | `list_task_runs` | Paginated run history, newest first. |
| GET | `/build/sessions/{id}/scheduled-run-context` | (session API) | Returns task name/id and fire time if the session came from a scheduled run; 404 otherwise. Drives the session-view banner. |

All endpoints are scoped to the authenticated user; there is no admin view.

### Celery tasks (`scheduled_tasks/tasks.py`, dispatched on the primary queue
except the executor)

| Task | Queue | Cadence | Job |
|---|---|---|---|
| `dispatch_due_scheduled_tasks` | `OnyxCeleryQueues.PRIMARY` | every 30 s, per tenant | Claims due tasks with `FOR UPDATE SKIP LOCKED`, inserts a run row, advances `next_run_at`, enqueues the executor. |
| `run_scheduled_task` | `scheduled_tasks` | on demand | Thin wrapper around `run_scheduled_task_logic` (`executor.py`); the actual agent-driving work. |
| `cleanup_stuck_scheduled_runs` | `OnyxCeleryQueues.PRIMARY` | hourly | Marks runs stuck past a budget as failed. A `queued` run is stuck after `QUEUE_RESIDENCY_SECONDS` (15 min). A `running` run is stuck after the hard cap plus `TURN_RECLAIM_SLACK_SECONDS` (`build/timeouts.py`). |

Both beat entries are defined in
`backend/onyx/background/celery/tasks/beat_schedule.py:beat_task_templates`
alongside every other periodic task; see `[[background-jobs]]` for the
shared Beat/queue machinery this feature reuses rather than reimplements.

### The `scheduled_tasks` worker

`backend/onyx/background/celery/apps/scheduled_tasks.py` autodiscovers only
`onyx.background.celery.tasks.scheduled_tasks` and runs on its own Celery
app, queue, and Prometheus port. This is the worker
`[[background-jobs]]` found the `background/README.md` worker table omits
entirely: it exists, is wired into `supervisord.conf`, the Helm chart's
`celery-worker-*.yaml` set, and `backend/AGENTS.md`'s worker table, but not
into the README. The dispatcher and stuck-run sweeper deliberately run on
the **primary** queue instead of this dedicated one: they are cheap DB
coordination, and routing them onto a queue that a long-running executor
run could saturate would stall dispatch for every tenant
(`beat_schedule.py`, comment above the two entries).

### Environment configuration

| Variable | Effect |
|---|---|
| `CELERY_WORKER_SCHEDULED_TASKS_CONCURRENCY` | Thread-pool size for the dedicated worker (`background/celery/configs/scheduled_tasks.py:worker_concurrency`, per the pattern documented in `[[background-jobs]]`). |

---

## 3. Data model

- `ScheduledTask` (`onyx/db/models.py`, via `onyx/db/scheduled_task.py`):
  `user_id`, `name`, `prompt`, `cron_expression`, `editor_mode`, `status`
  (`ACTIVE`/`PAUSED`), `next_run_at` (nullable; the dispatcher's only read
  field), `deleted` (soft delete). Indexed on
  `(status, deleted, next_run_at)` for the dispatch claim, and on
  `(user_id, created_at desc)` for the list view.
- `ScheduledTaskRun`: `task_id` (FK, cascade), `session_id` (FK to
  `BuildSession`, `SET NULL`, nullable until the executor creates the
  session), `status` (`queued/running/succeeded/failed/skipped/awaiting_approval`),
  `trigger_source` (`scheduled`/`manual_run_now`), `skip_reason`/`error_class`/
  `error_detail`, `started_at`/`finished_at`, `summary` (short text pulled
  from the final agent message).
- `ScheduledTaskPreApprovedTarget`: one row per `(task, gated_app)` grant.
  `UNIQUE(scheduled_task_id, gated_app_id)`. The `gated_app` row is an
  external app or an MCP server. The table name is `scheduled_task_pre_approved_app`
  and predates MCP support. See §4.4.
- `BuildSession.origin` (`SessionOrigin`: `INTERACTIVE`/`SCHEDULED`): set by
  the executor at session-create time. The normal Craft sidebar query
  filters to `INTERACTIVE`, which is how scheduled runs stay out of it. A
  dedicated column was chosen over a join-based `NOT EXISTS` against
  `scheduled_task_run` because the dispatcher writes its run row before the
  executor creates the session, and a join-based filter would briefly leak
  the not-yet-linked session into the sidebar
  (`docs/craft/features/scheduled-tasks/overview.md`).
- `action_approval.decided_via` (nullable: `USER`/`PRE_APPROVAL`/`SESSION_GRANT`) and
  `action_approval.gated_app_id` (nullable FK): audit fields distinguishing
  a pre-approved forward from a human click, kept separate from `decision`
  so pre-approvals don't change what `decision == APPROVED` means elsewhere.

---

## 4. How it works

### 4.1 Creating a task and its schedule

`schedule.py` compiles one of three editor modes (`IntervalPayload`,
`DailyWeeklyPayload`, `AdvancedPayload`) to a canonical 5-field cron string
via `compile_to_cron`, validated with `croniter` (`_validate_cron`). The
cron is stored and always evaluated in UTC; `editor_mode` is only a UI hint
for redisplaying the form. `compute_next_run_at` and `next_n_fires` (used
for the "next 3 runs" preview) both wrap `croniter`.

### 4.2 Dispatch: turning "due" into a run

`dispatch_due_scheduled_tasks` (`tasks.py`, primary queue, one Beat entry
per tenant every 30 s):

1. Selects due `ScheduledTask` rows with `FOR UPDATE SKIP LOCKED`, so
   concurrent Beat ticks across replicas cannot double-claim the same task.
2. For each claimed task: if the task owner no longer has Craft enabled
   (`is_craft_enabled_for_user`), insert a `skipped` run row with
   `ScheduledTaskSkipReason.OWNER_CRAFT_DISABLED` and still advance
   `next_run_at`. Otherwise, if a prior run for that task is still in flight,
   insert a `skipped` run row (`ScheduledTaskSkipReason`) and still advance
   `next_run_at`; the schedule keeps moving even when a run overruns.
   Otherwise insert a `queued` run, advance `next_run_at`, and enqueue
   `run_scheduled_task(run_id)` on the `scheduled_tasks` queue with
   `expires=QUEUE_RESIDENCY_SECONDS` (15 min).
3. `run-now` (`api.py:run_now`) takes the same path but inserts a
   `manual_run_now`-sourced run directly, independent of `next_run_at`, and
   works even on a paused task.

### 4.3 Execution: running a turn with nobody watching

`run_scheduled_task_logic` (`executor.py`):

1. Re-checks the run is still `queued` (idempotency against a redelivered
   Celery task). Calls `SessionManager.ensure_sandbox_running` to create or
   wake the owner's sandbox (a failure marks the run `failed` with
   `sandbox_wake_failed`). Then marks the run `running`.
2. Creates a fresh session with `SessionManager.create_session`, under the
   per-user session creation lock, with `user_id=task.user_id` and
   `origin=SessionOrigin.SCHEDULED`. Because it is the same manager the
   interactive UI uses, workspace setup, skills materialization, and
   AGENTS.md generation run unchanged; nothing about the environment differs from
   an interactive session except the origin tag and headless driving.
   Since the session is headless, `nextjs_port` is not allocated for it,
   so it never provisions a webapp dev server; see
   `[[craft-webapp-proxy]]` §4.5.
3. Writes the user prompt as turn 0, links `run.session_id` (status
   `RUNNING`), and commits, before any agent turn or egress can occur. This ordering is load-bearing for §4.4's pre-approval boundary.
4. `_drive_agent` takes the per-session prompt slot, stamps the turn
   deadline (soft budget plus hard cap), and runs the prompt through
   `SessionManager.yield_sandbox_events`. It writes each event with
   `SessionManager.persist_sandbox_event` into a `BuildStreamingState`,
   then calls `finalize_persist`. The interactive path uses the same
   manager methods with an SSE formatter; the executor drains the events
   to completion. A scheduled run's transcript looks the same as an
   interactive one when replayed. The run budget is
   `SCHEDULED_RUN_HARD_CAP_SECONDS` (60 min, `build/timeouts.py`).
5. On success, marks `succeeded` with a summary
   (`_summary_from_state`/`_summary_from_session_messages`). On a
   `RequestPermissionRequest` the agent can't resolve alone, marks
   `awaiting_approval` and notifies (`NotificationType.SCHEDULED_TASK_AWAITING_APPROVAL`).
   On any executor-level failure (crash, budget exceeded, terminal agent error, a cancelled turn), marks
   `failed` and notifies (`NotificationType.SCHEDULED_TASK_FAILED`). There
   are no retries in this version: a failed run is one row, and the user
   re-runs by hand or waits for the next fire.

`cleanup_stuck_scheduled_runs` (hourly, primary queue) sweeps runs that
have been `queued` too long or `running` past budget and marks them
`failed`, catching a run whose worker died without updating the row. The
sweeper does not send a notification.

### 4.4 Pre-approvals: unattended egress without a human in the loop

Scope: this section covers only the egress-proxy gate
(`backend/onyx/sandbox_proxy/addons/gate.py`), the mechanism
`[[craft-external-apps]]` documents for interactive sessions. A second,
unrelated approval path, ACP `RequestPermissionRequest` (which is what
produces the `awaiting_approval` run status in §4.3), is owned by a
separate approvals project and is untouched by this section.

The problem: the gate's normal `ASK` policy parks a request for up to
180 seconds waiting for a human click, then expires it and the sandbox
gets a 403. A scheduled task's author is essentially never present during
a cron fire, so every gated action in a scheduled run would fail this way
by default.

**How a pre-approval is bounded, precisely:**

- **Granted per external app or MCP server, per task**, never per individual
  action and never globally. The gate resolves a request to exactly
  one target first, so a target-level grant covers every
  action that target exposes by construction. `ScheduledTaskPreApprovedTarget`
  is the row that encodes this: `(scheduled_task_id, gated_app_id)`.
- **The grant is only live while the specific run it applies to is
  actually running.** The gate's lookup (`_scheduled_task_grant` in
  `gate.py`, backed by `get_live_scheduled_run_grants` in
  `onyx/db/scheduled_task.py`) requires the session's owning
  `scheduled_task_run.status == RUNNING`, not merely
  `BuildSession.origin == SCHEDULED`. A `BuildSession` keeps
  `origin=SCHEDULED` forever, and the session view leaves the chat input
  open once a run finishes, so without the `RUNNING` check a follow-up
  message typed into a *finished* scheduled session would silently inherit
  the task's grants. The executor commits `session_id` with `RUNNING` in the
  same write before any agent egress can occur (§4.3 step 3), so there is
  no window where a grant could apply before the run row says so.
- **Admin `DENY` always wins, before a grant is ever consulted.** The
  gate's verdict order is `DENY` (403, no row) then `ALWAYS` (forward, no
  row) then `ASK` (the only branch where a pre-approval grant is checked at
  all). A grant cannot override a `DENY` policy; it only short-circuits the
  park-and-wait for actions the admin already permits with confirmation.
- **A partially-granted run degrades gracefully, per app.** Requests to an
  app the task didn't grant park and expire exactly as they would with no
  pre-approval feature at all; only the granted app's requests skip the
  park.
- **Every unattended forward is recorded, not silent.** A pre-decided
  `action_approval` row is inserted already `APPROVED`, tagged
  `decided_via=pre_approval`, and a
  `NotificationType.SCHEDULED_TASK_PRE_APPROVED_ACTION` notification fires
  on the first such forward per `(run, target)` (deduped via
  `create_notification`'s `additional_data` key, which must stay to exactly
  `(run_id, target_kind, target_id)` or the dedup breaks).
- **Fail-closed on the forwarding path.** mitmproxy's default behavior on an
  unhandled addon exception is to forward the original request, bypassing
  the gate. The auto-approved dispatch path is wrapped so any unhandled
  exception there returns a 403 instead, so a already-committed `APPROVED`
  row can never be followed by an unguarded forward.

Grants are managed as checkboxes in the task editor (`pre_approved_app_ids`
and `pre_approved_mcp_server_ids` on create/patch); only the task's author can see or change them, since
tasks and their runs are user-scoped. Editing a task's prompt does not
silently reset its grants: they are shown and edited as an explicit,
separate choice.

---

## 5. Contracts and invariants

1. **A pre-approved action must be bounded by exactly what the user
   granted: one app, one currently-`RUNNING` run of that task.** Any change
   that widens the grant lookup (e.g. matching on `origin=SCHEDULED` alone,
   or on a terminal-status run) reopens the follow-up-message leak
   described in §4.4.
2. **`DENY` must be checked before any pre-approval lookup runs.** A
   pre-approval is only ever consulted inside the `ASK` branch.
3. **A failed run must notify, not fail silently.** Every terminal failure
   path in `executor.py` calls `_notify` with
   `NotificationType.SCHEDULED_TASK_FAILED`; a new failure exit added to the
   executor that skips this call is a silent failure from the user's
   perspective. The one exception is `cleanup_stuck_scheduled_runs`. It marks
   a stuck run `failed` and does not notify the owner.
4. **The dispatcher and the executor must not double-fire the same tick.**
   `FOR UPDATE SKIP LOCKED` in `claim_due_scheduled_tasks` is the
   concurrency guard; `next_run_at` must be advanced in the same
   transaction that claims the task, per the module docstring in
   `onyx/db/scheduled_task.py`.
5. **A scheduled session must not appear in the interactive sidebar.**
   Gated on `BuildSession.origin`, not on the presence of a
   `scheduled_task_run` row (see §3 for why).
6. **Every scheduled-task Celery send needs `expires=` and `tenant_id`**,
   per the shared invariants in `[[background-jobs]]`; nothing in this
   feature is exempt from those rules.

---

## 6. Relationships

**Depends on**
- [[background-jobs]]: the Celery app/queue/Beat machinery this feature's
  dispatcher, executor, and sweeper all run on; this document does not
  duplicate that machinery.
- [[craft-sessions]]: `SessionManager.create_session`, `BuildSession.origin`,
  and the session view that renders both interactive and scheduled runs.
- [[craft-sandboxes]]: sandbox provisioning happens unchanged for a
  scheduled session; `[[craft-webapp-proxy]]` documents the one thing that
  is skipped (webapp dev-server provisioning, since `nextjs_port` is `None`).
- [[craft-external-apps]]: the egress-proxy gate and its policy model that
  pre-approvals short-circuit.
- [[notifications]]: `SCHEDULED_TASK_FAILED`, `SCHEDULED_TASK_AWAITING_APPROVAL`,
  `SCHEDULED_TASK_PRE_APPROVED_ACTION`.
- [[auth-and-identity]]: every endpoint and every grant is scoped to the
  authenticated task owner.
- [[multi-tenancy]]: dispatch and cleanup are per-tenant Beat entries, like
  every other tenant-scoped background task.

**Depended on by**
- Nothing outside Craft currently depends on this component.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| changes the dispatcher's claim query or locking | concurrent-tick safety (`FOR UPDATE SKIP LOCKED`), and that `next_run_at` still advances in the same transaction |
| changes run status transitions | the notification call sites in `executor.py`, and the run-history clickability rules in the frontend (`docs/craft/fix-live-scheduled-task-runs.md`) |
| changes the pre-approval grant lookup or its scope | re-read §4.4 in full; this is the part of the feature where a widened match is a real security regression, not just a UX bug |
| adds a new gated-app-request path in the egress proxy | whether it should be reachable by a pre-approval grant at all, and whether `DENY` still short-circuits before the grant check |
| changes `BuildSession.origin` handling | the sidebar filter query, and any other place that assumes `INTERACTIVE` is the only origin |
| changes the executor's session-creation call | verify `origin=SCHEDULED` and `session_id` are still committed with `RUNNING` before any agent turn (no window for a grant to apply before the run is actually running) |
| adds a new Celery task to this feature | which worker's `-Q` list includes its queue (see `[[background-jobs]]`'s table); whether it belongs on `scheduled_tasks` or on `primary`, per the reasoning in §2 |

---

## 8. How to verify a change

### Tests

```bash
# External dependency unit (real SQL): pre-approval grant scoping and
# executor persistence behavior.
cd backend && uv run pytest tests/external_dependency_unit/craft/test_scheduled_task_pre_approvals.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_scheduled_task_executor.py
# Unit: the gate's grant-source short-circuit, stubbed DB.
cd backend && uv run pytest tests/unit/sandbox_proxy/test_gate.py
# Unit: schedule compilation and dispatch-adjacent logic.
cd backend && uv run pytest tests/unit/onyx/server/features/craft/scheduled_tasks
# Integration: the HTTP API surface end to end.
cd backend && uv run pytest tests/integration/tests/craft/test_scheduled_tasks_api.py
# Playwright smoke: dispatcher -> executor -> run-history wiring.
cd web && bun run playwright scheduled-tasks
```

`docs/craft/features/scheduled-tasks/tests.md` documents the Playwright
spec's exact selectors (`new-task-button`, `task-status-active`,
`data-run-status`, etc.) and states plainly what it does not cover:
`FOR UPDATE SKIP LOCKED` concurrency, the stuck-run sweeper, the
approval-required path, sidebar filtering, and per-user ownership
boundaries on the HTTP API. Those rely on the manual checklist in that
file and on code review, not automation.

### Manual reproduction

1. Confirm the dedicated worker is up:
   `tail -f backend/log/celery_worker_scheduled_tasks_debug.log`, and Beat:
   `tail -f backend/log/celery_beat_debug.log`.
2. Create a task at `/craft/v1/tasks` with an interval schedule and a
   simple prompt.
3. Use "Run now" rather than waiting for the interval; confirm a run row
   appears as `running` then reaches a terminal state within the executor's
   budget.
4. Open the finished run from the task's run history; confirm it opens the
   normal Craft session view with the scheduled-run banner, and that the
   session does not appear in the regular Craft sidebar.
5. For the pre-approval path: configure a task with a granted app that has
   an `ASK`-policy action, run it, and confirm the action forwards without
   parking, an `action_approval` row exists with `decided_via=pre_approval`,
   and a `SCHEDULED_TASK_PRE_APPROVED_ACTION` notification appears. Then
   send a follow-up message on the same, now-finished session and confirm
   the same app's action *does* park (the `RUNNING` check must exclude it).

### What "working" looks like

- A due task fires within one Beat cycle (30 s) plus queue latency, not
  minutes later.
- A run that overruns its predecessor is recorded `skipped`, not silently
  dropped, and the schedule still advances.
- A failed run always produces a `SCHEDULED_TASK_FAILED` notification; no
  failure is invisible to the user.
- A pre-approval only fires for its own app, on its own `RUNNING` run.

---

## 9. Footguns

- **The `scheduled_tasks` worker is missing from `background/README.md`'s
  worker table**, as `[[background-jobs]]` §9 already documents; this
  document independently confirms the worker exists
  (`apps/scheduled_tasks.py`) and is wired into `supervisord.conf`, the
  Helm chart, and `backend/AGENTS.md`, just not the README.
- **`docs/craft/fix-live-scheduled-task-runs.md` addressed a real gap: a
  running scheduled task was not viewable until it finished.** Before that
  change, the frontend blocked opening `RUNNING` and `AWAITING_APPROVAL`
  rows even when the backend had already linked a `session_id`. The fix
  adds a live SSE path where the api-server attaches as another viewer of
  the sandbox pod's own opencode `/event` stream (filtered to the run's
  session id) rather than introducing a new transport (Redis pub/sub was
  considered and deliberately not used, since the api-server can already
  reach sandbox pods directly). It also changed the run-history
  clickability rule: `RUNNING`/`FAILED`/`SUCCEEDED`/`AWAITING_APPROVAL`
  runs are openable whenever they have a `session_id`; `QUEUED` (no
  session yet) and `SKIPPED` (no session at all) stay non-openable.
- **A scheduled session's chat input is not permanently locked.** Once a
  run reaches a terminal state, the user can send ordinary follow-up
  messages in that same session. This is intentional, but it is exactly
  the case §4.4's `RUNNING`-status check exists to keep out of the
  pre-approval grant.
- **There are no retries.** A failed run is terminal; nothing resends the
  prompt automatically. Do not assume idempotent retry behavior when
  reasoning about a partially-completed action inside a failed run.
- **The dispatcher and stuck-run sweeper deliberately do not run on the
  `scheduled_tasks` queue**, even though they are this feature's own
  tasks. They are cheap coordination work placed on `primary` specifically
  so a saturated executor pool cannot stall dispatch for other tenants.

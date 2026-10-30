# Craft Scheduled Tasks

> A user schedules a Craft prompt to run on a timer. Each fire creates a new
> headless Craft session in the owner's sandbox, runs one agent turn with
> nobody watching, and records a run row the user can open later.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE

---

## User experience

A Craft user writes a prompt, picks a schedule (an interval, a daily or weekly
time, or a cron expression), and chooses which connected apps the task may use.
New tasks start with every app off. For each enabled app the user can set
Auto-approve, Ask or Disabled per action, within the limits the admin set.
"Run once" fires the task at once, even when it is paused. Pause stops the
fires; Resume schedules the next fire from the time of resume, so missed fires
do not run.
Delete hides the task but keeps its runs, and a run already queued still runs.

Each fire adds a row to the task's run history. A run with a session opens in
the normal Craft session view, with a banner that names the task. A running
run streams live in that view. Scheduled sessions do not appear in the Craft
session sidebar. After a run ends, the user can send follow-up messages in the
same session, but app actions from that session are blocked. The user starts a
normal session to use personal app settings.

When a run fails in the executor, the user gets an INFO notification. It
shows in the notification list, not in the banner queue. A run that the
stuck-run sweeper fails, or whose task row is gone, fails with no notification
([[#failure-paths-notify]]). A scheduled fire that overlaps
a run still in flight, or a fire for an owner who lost Craft access, is
recorded as skipped, and the schedule keeps going. "Run once" does not check
for a run in flight, so a manual run can overlap a scheduled one. There are no
automatic retries.

---

## Scope

This component owns:
- the task API and schedule compilation;
- the dispatcher, the stuck-run sweeper and the headless executor;
- task and run storage, and the run history;
- the task pages and the per-task app settings editor.

Neighbours:
- [[craft-external-apps]]: enforces task app enablement and task choices in
  the egress proxy, and owns the precedence rules.
- [[craft-sessions]]: `SessionManager`, which creates and drives the session
  the same way as an interactive one.
- [[craft-sandboxes]]: wakes or provisions the owner's sandbox.
- [[craft-admin]]: the access decision the dispatcher checks for each owner.
- [[background-jobs]]: the shared Beat and queue machinery.

---

## Architecture

```
Beat (per tenant, every 30 s, primary queue)
  dispatch_due_scheduled_tasks
    claim_due_scheduled_tasks            FOR UPDATE SKIP LOCKED
    per task: owner lacks Craft      -> SKIPPED (owner_craft_disabled)
              prior run in flight    -> SKIPPED (prior_in_flight)
              else                   -> QUEUED run row
              always advance next_run_at
    commit, then send run_scheduled_task(run_id) on the scheduled_tasks queue

run_scheduled_task -> executor.py:run_scheduled_task_logic
  1 run must still be QUEUED (Celery may redeliver)
  2 SessionManager.ensure_sandbox_running(owner)  failure -> FAILED
  3 QUEUED -> RUNNING
  4 _drive_agent: create_session(origin=SCHEDULED), save prompt as turn 0,
    link run.session_id, commit before the first agent event
  5 prompt_slot, yield_sandbox_events, persist_sandbox_event, until done
    or the budget ends
  6 SUCCEEDED with a summary, or FAILED with an error class + notification

Beat (per tenant, hourly, primary queue)
  cleanup_stuck_scheduled_runs  QUEUED too long or RUNNING past budget -> FAILED
```

**Schedules.** `backend/onyx/server/features/build/scheduled_tasks/schedule.py:compile_to_cron` turns the three
editor modes into one 5-field cron string. Cron is stored and evaluated in
UTC. `editor_mode` only lets the form show the input again. The user enters
local times. The browser converts the payload to UTC with the offset of the
save date before it sends it, and compiles cron itself for validation and the
preview (`web/src/app/craft/v1/tasks/schedule.ts:localPayloadToUtcPayload`,
`compileToCron`). A change to the cron rules needs both compilers.

**Origin.** `create_session(origin=SessionOrigin.SCHEDULED)` marks the
session. The sidebar query filters on `INTERACTIVE`
(`server/features/build/db/build_session.py:get_user_build_sessions`). The
proxy uses the origin to refuse personal policies for a scheduled session.

**Live view.** `backend/onyx/server/features/build/session/api.py:get_session_scheduled_run_events` attaches the
API server as one more reader of the sandbox's event stream for a `RUNNING`
run. It sends keepalives until the executor stores the opencode session id, so
a quick click on a new run does not fail.

**App policies.** Task create and patch accept per-app settings.
`db/action_policy.py:replace_task_action_policies` stores them as
`ScheduledTaskEnabledApp` rows (which apps the task may use) and
`ScheduledTaskActionPolicy` rows (choices per action). An empty map stores no
choices; it does not copy personal choices. The editor copies personal choices
into the draft on the first edit or enable. Edits apply to the next request,
including requests of a run in progress.

---

## Contracts and traps

1. `advance-in-claim-txn` **Advance `next_run_at` in the claiming
   transaction.** The dispatcher
   (`db/scheduled_task.py:claim_due_scheduled_tasks`) holds `FOR UPDATE SKIP LOCKED` row locks
   until commit. A change that advances later, or claims without the lock,
   double-fires a tick across replicas.
2. `enqueue-after-commit` **Enqueue only after commit.** The executor must not
   see a run row that rolls back. If the process dies between commit and send,
   the run stays `QUEUED` and the sweeper marks it failed later. Nothing sends
   it again.
3. `send-expires-and-tenant` **Every send needs `expires=` and `tenant_id`.**
   Two places send the executor task: the dispatcher and, for manual runs,
   `backend/onyx/server/features/build/scheduled_tasks/api.py:_enqueue_executor`. Both expire after
   `QUEUE_RESIDENCY_SECONDS`, which is also the stuck-queued threshold, so one
   rule reclaims a message that expires unexecuted and its row
   (`background/celery/tasks/scheduled_tasks/tasks.py`). The `tenant_id` kwarg
   selects the tenant schema in the executor.
4. `link-session-before-turn` **Link the session to the run before any agent
   turn.** The proxy finds a task's authority through
   `ScheduledTaskRun.session_id` and a `RUNNING` status
   (`db/action_policy.py:get_active_scheduled_task_context`). An unlinked or
   finished run gives `no_active_session` for every app request. The authority
   also ends with the run
   ([[craft-external-apps#task-authority-ends-with-run]]). Do not add a
   fallback to personal policies for scheduled sessions.
5. `task-choices-default-ask` **Task choices follow the precedence in
   [[craft-external-apps]].** Two rules differ from personal choices: an app
   not enabled for the task denies every action, and a missing task choice
   means Ask, not the workspace default. When the app does not let users
   manage policies, the workspace policy applies to tasks too
   (`db/action_policy.py:effective_action_policy`).
6. `origin-filter-not-join` **Hide scheduled sessions by `BuildSession.origin`,
   not by a join.**
   `server/features/build/session/manager.py:SessionManager.create_session` commits the session and
   then sets up its session workspace. The executor links the session to the
   run only after that. A join on `scheduled_task_run.session_id` would show
   the new session in the sidebar during that window. Slack sessions use the
   same origin filter.
7. `executor-never-reraises` **Do not re-raise from the executor.**
   `server/features/build/scheduled_tasks/executor.py:run_scheduled_task_logic` turns errors into a `FAILED` row so Celery does
   not retry. A retry would run the prompt and its side effects twice.
8. `failure-paths-notify` **New failure paths must notify.** Executor failure
   paths call `server/features/build/scheduled_tasks/executor.py:_notify` with `SCHEDULED_TASK_FAILED`. The `TASK_MISSING` path
   and the stuck-run sweeper do not, so those failures are silent to the user.
9. `dispatch-on-primary` **Keep the dispatcher and sweeper on the primary
   queue.** They are short DB work. On the `scheduled_tasks` queue, long
   executor runs could stall dispatch for every tenant (comment in
   `background/celery/tasks/beat_schedule.py`).
10. `scheduled-session-may-get-port` **A scheduled session can get a Next.js
    port later.** `create_session` skips the port for non-interactive origins.
    When a follow-up turn must rebuild the session workspace (for example
    after sleep), `backend/onyx/server/features/build/session/session_ready.py:ensure_session_ready` reserves a
    port for any session that has none. Do not assume a scheduled session
    never has one.

---

## Decisions

- **A dedicated `BuildSession.origin` column** instead of a join, for the
  sidebar race in [[#origin-filter-not-join]], and because the proxy reads it
  on every request.
- **Skip, not queue, an overlapping fire.** A slow task cannot pile up runs.
  The skipped row makes the miss visible.
- **No retries.** A partly done run may have acted on external apps. The user
  decides whether to run it again.

---

## Known issues

- `ScheduledTaskRunStatus.AWAITING_APPROVAL` and the notification types
  `SCHEDULED_TASK_AWAITING_APPROVAL` and `SCHEDULED_TASK_PRE_APPROVED_ACTION`
  (`db/enums.py:ScheduledTaskRunStatus`, `configs/constants.py:NotificationType`)
  are defined, but nothing sets or sends
  them. The web app still handles the status
  (`web/src/app/craft/v1/tasks/components/StatusBadge.tsx`,
  `web/src/app/craft/hooks/useBuildSessionStore.ts`). Approvals in a scheduled
  run use the normal proxy wait.
- The `backend/onyx/server/features/build/scheduled_tasks/executor.py` docstrings give a 30-minute budget and a
  `sandbox_provisioning` skip, and the `backend/onyx/background/celery/tasks/scheduled_tasks/tasks.py` module docstring gives a
  45-minute stuck threshold. These are false leads. The code uses
  `SCHEDULED_RUN_HARD_CAP_SECONDS` (60 minutes,
  `server/features/build/timeouts.py`) plus `TURN_RECLAIM_SLACK_SECONDS`, and
  marks any wake failure `FAILED`.
- A run that dies without updating its row stays `RUNNING` until the hard cap
  plus `TURN_RECLAIM_SLACK_SECONDS`, then up to one more hour for the sweep.
- A daily or weekly time keeps the UTC time of the day it was saved. After a
  daylight-saving change, the task fires one hour off in local time until the
  user saves it again.
- An agent `RequestPermissionRequest` ends the run as `FAILED`
  (`agent_permission_required`). It does not pause for the user.

---

## Dependencies

- [[craft-external-apps]]: proxy enforcement and policy precedence.
- [[craft-sessions]]: `SessionManager.create_session`, `prompt_slot`,
  `yield_sandbox_events` and `persist_sandbox_event`.
- [[craft-sandboxes]]: `ensure_sandbox_running` for the owner.
- [[craft-admin]]: `is_craft_enabled_for_user`, checked for each owner at
  dispatch.
- [[background-jobs]]: Beat entries, queues and the worker set.
- [[notifications]]: `SCHEDULED_TASK_FAILED`.
- [[multi-tenancy]]: per-tenant Beat fan-out and the `tenant_id` kwarg.

---

## Recipes

- `celery-task` **A Celery task for this feature.** Copy `cleanup_stuck_scheduled_runs` for
  short DB work or `run_scheduled_task` for work that drives an agent; list the
  tasks with `git grep -n '@shared_task' backend/onyx/background/celery/tasks/scheduled_tasks/`.
  Short DB work goes on `primary` ([[#dispatch-on-primary]]); work that drives
  an agent goes on `scheduled_tasks`. Pass `expires=` and `tenant_id`
  ([[#send-expires-and-tenant]]).
- `run-status-or-error-class` **A run status or error class.** Copy an existing value of
  `ScheduledTaskRunStatus` or the closed `ScheduledTaskErrorClass` in
  `backend/onyx/db/enums.py`. Then update `getNonClickableReason` and
  `isScheduledRunInFlight` in `web/src/app/craft/v1/tasks/utils.ts`, and the
  notification calls ([[#failure-paths-notify]]).
- `investigate-task-did-not-run` **Investigate "my task did not run".** Read the task's run rows. A
  `SKIPPED` row names the reason (`owner_craft_disabled` or
  `prior_in_flight`). A `QUEUED` row that never starts means the
  `scheduled_tasks` worker is not running or the message expired. No row at
  all means the dispatcher did not claim the task: check `next_run_at` and
  that the Beat for the tenant runs.
- `investigate-silent-failure` **Investigate "my run failed and I got no notification".** Read the run's
  `error_class`. `STUCK` or `TASK_MISSING` is silent by design
  ([[#failure-paths-notify]]). A `STUCK` run with an `error_detail` of
  `queued > N min` means the `scheduled_tasks` worker did not pick it up. For other classes, search the logs
  for `Failed to create scheduled-task notification`. The failure notice is
  INFO, so look for it in the notification list, not the banner queue.
- `setup-task-policy-test` **Set up a task-policy test.** Set one task action to Auto-approve while the
  personal choice is Ask. Run the task: the action runs with no prompt. After
  the run ends, send a follow-up that uses the same action: the proxy blocks
  it.

---

## Verification

- Dispatch, executor and sweeps: `backend/tests/external_dependency_unit/craft/`.
- Task choices and enablement: `backend/tests/external_dependency_unit/permissions/`.
- Task context in the proxy: `backend/tests/unit/sandbox_proxy/`.
- Schedule compilation: `backend/tests/unit/onyx/server/features/craft/scheduled_tasks/`.
- The API: `backend/tests/integration/tests/craft/`.
- Playwright: `web/tests/e2e/scheduled-tasks/` needs the `scheduled_tasks`
  Celery worker. Without it, runs never finish and the spec times out.

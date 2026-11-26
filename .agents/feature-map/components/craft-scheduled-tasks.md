# Scheduled Tasks

> A user schedules a prompt to run on a timer. Each fire creates a new hidden
> chat owned by the user, runs one chat turn of the default agent with nobody
> watching, and records a run row that the user opens later as a chat.

**Verified against:** `0135795fdf` (2026-11-20)
**Edition:** CE

---

## User experience

A user opens "Scheduled Tasks" in the `/app` sidebar, writes a prompt, picks a
schedule (an interval, a daily or weekly time, or a cron expression), and
chooses which integrations the task may use. New tasks start with every
integration off. For each enabled integration the user can set Allow, Ask,
Blocked or Inherit per action, within the limits the admin set. "Run once"
fires the task at once, even when it is paused. The "Run on schedule" switch
on the task page (Pause or Resume in the list row menu) stops and starts the
fires; Resume schedules the next fire from the time of resume, so missed fires
do not run. Delete hides the task but keeps its runs, and a run already queued
still runs. The task list has a name search and a filter: all, Active, Paused,
or tasks with new results.

Each fire adds a row to the task's run history. A run opens at
`/app?chatId=<chat_session_id>`, with a banner that names the task. A running
run streams in the normal chat view. Scheduled chats are not in the chat
history list or chat search. After a run ends, the user can send follow-ups
in the same chat; those turns keep the task's integration settings.

When a run reaches an Ask action, the turn parks, the run shows "Awaiting
approval", and the owner gets a notification. The owner approves in the chat
and the turn continues. A run that nobody approves is cancelled at the next
fire (which then runs) or after 24 hours. Reject skips the action and the
turn finishes. A Stop in the chat cancels a running run, not a parked one.

A blue dot marks runs the owner has not opened: on each run, on each task row
and on the "Scheduled Tasks" sidebar tab, which polls
`GET /scheduled-tasks/unviewed-count` every 30 seconds. Opening the run's chat
marks the run viewed. "Mark all viewed" marks every run of the task.

A failed run sends an INFO notification. A fire that overlaps a run that still
runs is recorded as skipped. There are no automatic retries.

The Craft task pages (`/craft/v1/tasks`) read the same tasks through
`/build/scheduled-tasks` and stay until Craft is removed. A run row there
opens the run's chat. Runs from before the move to chat have no chat and do
not open.

---

## Scope

This component owns:
- the task API and schedule compilation;
- the dispatcher, the sweeper and the executor;
- task and run storage, and the run history;
- the task pages in `/app` and in Craft, and the run banner.

Neighbours:
- [[core-chat-loop]]: `run_chat_turn`, the headless turn the executor runs.
- [[mcp-and-custom-tools]]: durable approvals, which park and resume a run.
- [[chat-persistence]]: `ChatMessage.response_status`, the run's source of
  truth.
- [[craft-external-apps]]: the policy function that task settings feed.
- [[background-jobs]]: the shared Beat and queue machinery.

---

## Architecture

```
Beat (per tenant, every 30 s, primary queue)
  dispatch_due_scheduled_tasks
    _sync_chat_runs: interrupt ownerless responses, then
                     sync_chat_run__no_commit for each in-flight chat run
    claim_due_scheduled_tasks            FOR UPDATE SKIP LOCKED
    per task: cancel runs AWAITING_APPROVAL (superseded_by_next_fire)
              run QUEUED                -> started_at = now, send it again
              run RUNNING               -> SKIPPED (prior_in_flight)
              else                      -> QUEUED run row
              always advance next_run_at (cron fire + per-task offset)
    commit, send run_scheduled_task(run_id)

run_scheduled_task -> onyx/scheduled_tasks/executor.py:run_scheduled_task_logic
  1 run must still be QUEUED (Celery may redeliver)
    owner must be active, hold WRITE_CHAT and be in budget, as a chat send
  2 create the chat (default agent), link run.chat_session_id, RUNNING:
    one commit, under the run's row lock
  3 run_chat_turn(prompt, approval_mode=INTERACTIVE)  completes or parks
  4 sync_chat_run__no_commit: the response status gives the run status
  any exception -> FAILED (agent_exception) + notification

Approval in the chat -> the turn resumes on an API server; the next dispatch
tick moves the run to RUNNING and then to its end status.

Beat (per tenant, hourly, primary queue)
  cleanup_stuck_scheduled_runs  QUEUED too long -> FAILED (stuck)
                                AWAITING_APPROVAL > 24 h -> CANCELLED
```

**Run status.** `db/scheduled_task.py:sync_chat_run__no_commit` maps the
status of the run's first chat response (`get_run_response`):
running → RUNNING, suspended → AWAITING_APPROVAL, complete or limit →
SUCCEEDED with a summary, cancelled → CANCELLED, error → FAILED. It notifies
on FAILED and AWAITING_APPROVAL. It converges, so the executor and every
dispatch tick can call it.

**Schedules.** `backend/onyx/server/features/build/scheduled_tasks/schedule.py:compile_to_cron`
turns the three editor modes into one 5-field cron string, stored and
evaluated in UTC. The browser converts local times to UTC at the date of the
next fire (`web/src/app/craft/v1/tasks/schedule.ts`). A change to the cron
rules needs both compilers.

**Routes.** One router, `server/features/build/scheduled_tasks/api.py`, is
mounted at `/scheduled-tasks` and under `/build` behind the Craft gate.
`GET /scheduled-tasks/action-policies` is the new-task catalog and
`GET /scheduled-tasks/chat-sessions/{id}/run` feeds the banner (null for a
normal chat).

**Integrations.** Task create and patch accept
`integrations: [{integration_id, action_settings}]`, checked and stored by
`integrations/craft.py:replace_task_integrations__no_commit`. In the chat of
a run, `integrations/policy.py:chat_integrations` gives the chat the task's
integrations with the task's settings, also those the owner turned off, and
also after the run ends, so a VM command that outlives the run never gains
the agent's integrations. Tool construction, the approval check and the
sandbox proxy all read it. The
catalog (`list_task_integration_views`) lists what chat can run: MCP and
OpenAPI integrations, not API apps without an OpenAPI tool.

---

## Contracts and traps

1. `advance-in-claim-txn` **Advance `next_run_at` in the claiming
   transaction.** `claim_due_scheduled_tasks` holds `FOR UPDATE SKIP LOCKED`
   row locks until commit. Advancing later, or claiming without the lock,
   double-fires a tick across replicas.
2. `enqueue-after-commit` **Enqueue only after commit.**
   The executor must not see a run row that rolls back. If the process dies
   between commit and send, the run stays `QUEUED` and the sweeper fails it.
3. `send-expires-and-tenant` **Every send needs `expires=` and `tenant_id`.**
   The dispatcher and `server/features/build/scheduled_tasks/api.py:_enqueue_executor` both expire after
   `SCHEDULED_RUN_QUEUE_RESIDENCY_SECONDS` (3 h), which is also the
   stuck-queued threshold of `cleanup_stuck_scheduled_runs`. While a run is
   QUEUED, `started_at` is its queue clock: a fire that sends it again resets
   it. `_start_run` sets it to the real start, and `_sync_chat_runs` fails a
   started run with no chat response after `NO_RESPONSE_OLDER_THAN` (15 min).
   `find_stuck_runs` locks its candidates (`SKIP LOCKED`), so a sweep cannot
   fail a run that a fire requeues at the same time.
4. `link-session-before-turn` **The response is the run's source of truth.**
   Write run status only through `sync_chat_run__no_commit` or a cancel.
   The turn can end on any API server after an approval, so nothing at the
   end of the executor alone may decide the status.
5. `task-choices-default-ask` **A run chat keeps the task's authority.**
   `chat_integrations` uses the task's current links in the chat of a run,
   also after the run ends, so a command that outlives the run never gains
   the agent's integrations. A task edit applies to that chat too. Saved
   Always allow choices do not apply to a task link
   (`AgentIntegration.task_link`). The task's settings are link settings: an
   admin Blocked stays final
   (`integrations/policy.py:resolve_action_policies`).
6. `run-link-hides-chat` **The run link is what hides a scheduled chat.**
   History (`get_chat_sessions_by_user`), search and delete-all apply
   `db/chat.py:not_a_scheduled_run_chat`. The executor creates the chat and
   links it in one commit, so a run chat is never listed. The link has no
   foreign key, because adding one would lock `chat_session`; the dispatcher
   cancels a run whose chat was hard-deleted.
7. `executor-never-reraises` **Do not re-raise from the executor.** A Celery
   retry would run the prompt and its side effects twice.
8. `failure-paths-notify` **New failure paths must notify.** Use
   `notify_run_owner__no_commit`. The stuck sweep does not notify.
9. `dispatch-on-primary` **Keep the dispatcher and sweeper on the primary
   queue.** Long executor runs on `scheduled_tasks` would stall dispatch.
10. `cancel-before-fire` **A fire cancels a parked run, not a running one.**
    Only AWAITING_APPROVAL runs are cancelled; a RUNNING run makes the fire
    SKIPPED, and a QUEUED run takes the fire and is sent again. Two messages
    for one run are safe: `_start_run` starts only a QUEUED run, under its
    row lock. "Run once" cancels nothing. An approval can resume the
    response before the run status follows, so cancel only through
    `chat/run_store.py:cancel_parked_response`, which leaves an owned
    response alone; `stop_response` would stop the approved work.
11. `run-viewed-revision` **Run read state mirrors Outputs artifacts.**
    `mark_run_status` increments `version` when a run moves into a status
    with results (`has_results()`: terminal or AWAITING_APPROVAL). SKIPPED
    rows stay at version 0. `viewed_revision` only moves forward. A run is
    unviewed while `(viewed_revision ?? 0) < version`.

---

## Decisions

- **One run engine.** The dispatcher sends every task, old Craft tasks too,
  to the chat executor. Runs have no link to Craft build sessions, and Craft
  sessions have no scheduled-task authority. The migration that moved runs to
  chat failed the Craft runs that were still in flight.
- **Default agent only.** A task has no agent column yet.
- **The chat time cap.** A run has no cap of its own: it ends with its
  response, which stops itself at the chat deadline (`CHAT_EXECUTION_TIMEOUT_S`,
  one hour). The run then ends FAILED with `timeout`. A response whose worker
  died is interrupted through `interrupt_ownerless_responses`.
- **Skip, not queue, an overlapping fire.** A slow task cannot pile up runs.
- **No retries.** A partly done run may have acted on external integrations.

---

## Known issues

- A daily or weekly time keeps the UTC time of the save. After a
  daylight-saving change the fire is one hour off in local time; the pages
  show the true local time of each fire.
- After an approval, the run status follows the resumed turn only at the next
  dispatch tick (up to 30 s late).

---

## Dependencies

- [[core-chat-loop]]: `run_chat_turn`.
- [[mcp-and-custom-tools]]: durable approvals and `stop_response`.
- [[craft-external-apps]]: policy precedence.
- [[background-jobs]]: Beat entries, queues and the worker set.
- [[notifications]]: `SCHEDULED_TASK_FAILED`, `SCHEDULED_TASK_AWAITING_APPROVAL`.
- [[multi-tenancy]]: per-tenant Beat fan-out and the `tenant_id` kwarg.

---

## Recipes

- `celery-task` **A Celery task for this feature.** Copy
  `cleanup_stuck_scheduled_runs` for short DB work or `run_scheduled_task`
  for work that runs a turn. Short DB work goes on `primary`
  ([[#dispatch-on-primary]]). Pass `expires=` and `tenant_id`.
- `run-status-or-error-class` **A run status or error class.** Add it to
  `ScheduledTaskRunStatus` or `ScheduledTaskErrorClass` in
  `backend/onyx/db/enums.py`, to `_RUN_STATUS_BY_RESPONSE_STATUS` if a
  response status maps to it, and to the web types and status badges
  (`web/src/sections/scheduledTasks/StatusBadges.tsx`,
  `web/src/app/craft/v1/tasks/components/StatusBadge.tsx`).
- `investigate-task-did-not-run` **Investigate "my task did not run".** Read
  the task's run rows. A `SKIPPED` row names the reason. A `QUEUED` row that
  never starts means the `scheduled_tasks` worker is not running or the
  message expired. No row means the dispatcher did not claim the task: check
  `next_run_at` and the tenant's Beat.
- `investigate-silent-failure` **Investigate "my run failed and I got no
  notification".** `STUCK` is silent by design. For other
  classes, search the logs for `Failed to create scheduled-task notification`.
- `setup-task-policy-test` **Set up a task-policy test.** Give the task one
  integration with an action on Ask. Run once: the run parks as
  AWAITING_APPROVAL. Approve in the chat: the run ends SUCCEEDED within one
  dispatch tick. A follow-up after the run keeps the task's settings.

---

## Verification

- Dispatch, run sync, next-fire cancel, approval timeout, task authority and
  the hidden history: `backend/tests/external_dependency_unit/scheduled_tasks/`.
- The API: `backend/tests/integration/tests/craft/test_scheduled_tasks_api.py`.
- Playwright: `web/tests/e2e/scheduled-tasks/` needs the `scheduled_tasks`
  Celery worker (the `full` ODS profile).

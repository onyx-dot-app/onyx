# Scheduled Tasks

## Objective

Let users hand Craft a recurring job and walk away. A **Scheduled Task** is a saved
prompt + schedule pair: at each fire time, the system spins up a fresh Craft session,
runs the prompt, and records what happened. From the user's perspective, the task is
"Craft, on a timer" — same agent, same skills, same context, just kicked off by the
clock instead of a person.

Example tasks a user should be able to set up in V1:

- "Every hour, check if any new work has happened on Craft, and if so keep the Craft
  Linear board up to date."
- "Every Monday at 9am, summarize last week's customer escalations and post the
  summary to #cs-leadership."
- "At 5pm every weekday, run our churn-risk report and email it to me."

The bar for V1: a user can create a task in the Craft UI, see it run on schedule
without their browser open, and click into any past run to see exactly what the agent
did.

## Users

- **Task author** — the user who creates the task. Runs execute *as* this user, with
  their permissions and connected apps.
- **Admins** — visibility/oversight only in V1. They can see all tasks in their org
  through the existing admin Craft pages (covered separately under admin UI work).

## New Pages

Lives under `/craft/v1/tasks` (new section in the existing Craft left nav).

### 1. Scheduled Tasks list — `/craft/v1/tasks`

The landing page. A table of the user's tasks:

- Name
- Schedule (human-readable: "Every hour", "Mondays at 9:00 AM PT")
- Status (active / paused)
- Last run (relative time + success/failure indicator)
- Next run (relative time)
- Row actions: run now, pause/resume, edit, delete

Empty state: a short explainer + a "Create scheduled task" CTA with two or three
example prompts the user can start from.

Top-right primary action: **Create scheduled task** → opens the editor.

### 2. Task editor — `/craft/v1/tasks/new` and `/craft/v1/tasks/:id/edit`

A single form, not a wizard. Fields:

- **Name** — short label (defaults to a slug of the first line of the prompt).
- **Prompt** — the message that gets sent to Craft each run. Same affordances as the
  Craft chat input (multi-line, attachments come later).
- **Schedule** — three modes via a tab/segmented control:
  - *Interval* — "Every N minutes/hours/days."
  - *Daily/weekly* — pick days of week + time of day + timezone.
  - *Advanced* — raw cron expression with a live human-readable preview.
- **Timezone** — defaults to the user's timezone; explicit so weekly tasks behave
  predictably across DST.
- **Status** — active / paused toggle. Defaults to active.

Save → returns to the list. Save and run now → returns to the list and immediately
kicks off a run.

### 3. Task detail — `/craft/v1/tasks/:id`

Two sections stacked:

- **Header** — name, schedule, status toggle, next run time, action buttons (Run
  now, Edit, Delete).
- **Run history table** — most recent runs first:
  - Started at
  - Duration
  - Status (queued, running, succeeded, failed, skipped, awaiting approval)
  - Summary (first ~120 chars of the agent's final message, once complete)
  - Row click → opens the run's Craft session in the existing session view (only
    after the run has finished — see "Intentionally Not Doing" for why in-progress
    runs are not openable)

Pagination: show the last 50 by default with a "Load more" button.

### 4. Run view — existing Craft session view

A run **is** a Craft session. Clicking a run from the history table opens that
session in the standard `/craft/v1/session/:id` view the user already knows: the
full transcript, artifacts, search calls, approvals, etc. We add a small banner at
the top: "This session was started by scheduled task *Name* at *time*. ← Back to
task."

No new run-detail page is needed — the existing session view is the run detail view.

## User Flows

### Creating a task

1. User clicks **Scheduled Tasks** in the Craft nav.
2. Clicks **Create scheduled task**.
3. Fills in name, prompt, schedule, timezone. Saves.
4. Lands back on the list with the new task at the top and a next-run time computed.

### Editing a task

1. From the list or the task detail page, click **Edit**.
2. Make changes. Save.
3. The next scheduled run uses the updated values. In-flight runs are not affected.

### Reviewing what a task has been doing

1. User opens the task detail page.
2. Scans the run history table — status icons make failures obvious.
3. Clicks into any run to see the full transcript, what the agent searched, what
   external systems it touched, what it produced.

### Pausing / deleting

1. From the list, the user toggles a task to paused — no new runs fire, existing
   runs continue to completion, run history stays.
2. From the list or detail page, the user deletes a task. Confirms. Run history is
   preserved for audit (sessions stay accessible from chat history) but the task is
   gone.

### A run fails

The run row shows status *failed* with the error class (sandbox couldn't start, agent
errored, timeout, etc.). Clicking through opens the session view with the failure in
context. No retries in V1 — the user can manually click **Run now** if they want to
retry, or wait for the next scheduled fire.

### A run hits an approval

Run status is *awaiting approval*. The user gets the same in-app notification they
get for interactive approvals. Approving from the approvals inbox resumes the run;
the run row updates accordingly. (Detail in the approvals doc.)

## Requirements

1. **Tasks are personal.** Each task belongs to one user. Runs execute with that
   user's permissions, connected apps, and skill grants. No sharing in V1.
2. **Every run is a fresh session.** No state carries across runs except what the
   prompt asks the agent to look up (e.g. from Onyx search, from Linear, from a file
   the agent wrote to a shared location).
3. **Schedule expressivity covers the common 80%.** Interval, daily/weekly with time
   of day, raw cron. Timezone is explicit per task.
4. **Run history is durable and complete.** Every fired run produces a row with
   start/end time, status, and a link to the session — even if the run failed before
   the agent did anything.
5. **The user can always run a task now.** "Run now" creates a one-off session
   identical to a scheduled fire. It does not affect the schedule.
6. **Status reflects reality.** Paused = no new runs. Active = next-run time is
   accurate to within a minute of the actual fire time.
7. **The list is responsive and snappy.** A user with 50 tasks should not see a
   loading spinner longer than the rest of the Craft UI.
8. **Mobile-tolerable, not mobile-first.** The list and detail pages should be
   readable on a phone; the editor can require a desktop.
9. **Notifications opt-in, not opt-out.** Users get an in-app indicator for failed
   runs and approval-required runs by default. No email or Slack in V1.
10. **The task editor and list reuse existing Craft primitives** — same input
    component, same buttons, same layout shell. Scheduled Tasks should feel like
    part of Craft, not a bolt-on settings page.

## Intentionally Not Doing in V1

- **Live-streaming a run in progress.** While a run is executing, the user sees its
  status in the run history table but cannot open the session and watch the agent
  stream in real time — the current Craft streaming architecture is tied to the
  interactive request that started the session, so attaching a second viewer to a
  backend-launched run is non-trivial. V1 makes the user wait until the run finishes,
  then opens the completed session. Live-attach is a follow-up.
- **Event triggers** (run when a Slack message arrives, when a Linear ticket
  changes, when a file lands in a folder). Schedule-only for V1; event triggers are
  a follow-up.
- **Shared / team tasks.** Tasks are single-user. No "this task runs on behalf of
  the team," no co-owners, no handoff if the author leaves. We expect this to be
  the most-requested follow-up.
- **Templated tasks / a starter gallery.** No "here are 10 prompts you can clone."
  The example prompts in the empty state are the entire onboarding hint.
- **Inline run detail UI.** No bespoke run viewer — we send the user into the
  existing session view. We may build a stripped-down run summary later, but not
  before we see how people actually browse history.
- **Retries / backoff config.** A failed run is a failed run. The user re-runs it
  manually or waits for the next fire. No retry-policy fields on the task.
- **Per-run prompt overrides.** "Run now with a different prompt" is just opening
  a regular Craft session.
- **Importing/exporting tasks.** No JSON/YAML export, no API for managing tasks
  externally. UI-only in V1.
- **Cost previews or budget caps per task.** Out of scope; lives in the broader
  Craft usage/governance work, not here.
- **Run diffing.** No "show me what changed between this run and last run" view.
  Useful, but later.
- **Calendar/timeline visualization.** The table is the view. No Gantt, no
  calendar grid.
- **Pause-when-failing auto-disable.** A task that fails 10 times in a row stays
  active. We'll add auto-pause once we have signal on how often this matters.

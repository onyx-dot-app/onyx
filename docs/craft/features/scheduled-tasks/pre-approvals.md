# Scheduled Task Pre-Approvals

## Objective

Scheduled task runs execute headlessly. When a run's agent hits a gated
external-app action (effective policy `ASK`), the egress proxy parks the
request for `WAIT_TIMEOUT_S = 180` seconds waiting for a human decision.
The task author is almost never present during a cron fire, so the
approval row goes `EXPIRED`, the sandbox gets a `403`, and the run
degrades or fails.

Pre-approvals let the task author grant **app access at
task-configuration time** ("this task will need Slack"): future runs of
that task execute that app's gated actions without parking. Admin policy
stays supreme and every unattended forward leaves an audit row and a
notification.

**Granularity is per external app, per task.** The gated-action catalog
across the built-in providers is ~30 endpoints; a per-action checklist
would force the user to guess which endpoints their prompt ends up
hitting — they'd either under-check (run still expires) or bulk-check
everything. "My agent needs Slack" is the user's actual mental model.
It's also how the matcher is shaped: a `RequestMatch` resolves to
exactly one app (`resolve_app_for_url`, first match wins), so an app
grant covers every action in a match by construction.

**Scope.** This targets the egress-proxy gate
(`backend/onyx/sandbox_proxy/addons/gate.py`) only. The other approval
mechanism touching scheduled runs — ACP `RequestPermissionRequest`,
which marks the run `AWAITING_APPROVAL` (`executor.py`) — is owned by
the approvals project and is unchanged.

## Important Notes

Constraints from the existing code that shape the design:

- **The gate's verdict path** (`gate.py::_resolve_and_match`):
  `DENY` → 403 immediately (no row); `ALWAYS` → forward silently (no
  row); `ASK` → insert `action_approval` row (`decision=NULL`),
  announce, notify, park. The pre-approval short-circuit slots into the
  `ASK` branch only — admin `DENY` wins by construction, per action,
  because it fires before pre-approval is ever consulted. Only catalog
  actions with a stored `external_app_policy` row reach the matcher at
  all; "gated" means a stored row with `ASK`.
- **`SessionContext` does not carry `origin`** —
  `resolve_session_by_id` (`sandbox_proxy/identity.py`) selects only
  `BuildSession.id`. The short-circuit needs one new joined lookup:
  `BuildSession → ScheduledTaskRun (session_id FK) → ScheduledTask`;
  grants come along with the task row.
- **`origin == SCHEDULED` is necessary but NOT sufficient.** A
  `BuildSession` keeps `origin=SCHEDULED` forever, the session view
  keeps the chat input available, and identity resolution intentionally
  does not filter on status — so interactive follow-up turns into a
  finished scheduled session would otherwise auto-approve. The
  short-circuit therefore also requires the owning
  `scheduled_task_run.status == RUNNING`. The executor writes
  `session_id` and `RUNNING` in the same commit before any agent egress
  can occur (`executor.py`), so there is no race on the other side.
  This also means Run Now (including on a paused task) gets grants —
  it produces a `RUNNING` run through the same executor.
- **The gate runs on the mitmproxy asyncio event loop.** Sync DB work
  in the request hook blocks all in-flight flows; the existing
  ALWAYS/APPROVED forward path already goes through
  `asyncio.to_thread`, and the new grant lookup follows the same
  pattern.
- **Pre-decided rows bend an existing invariant.** Today every
  `action_approval` row starts `decision IS NULL` and
  `try_record_decision`'s conditional UPDATE is the sole race arbiter.
  Pre-approved rows are inserted already-`APPROVED`; there is no
  competing decider for such a row, so this is safe — documented at the
  insert site.
- **Catalog/policy drift is safe by construction.** Policy changes
  take effect immediately — evaluation is fresh per request, so
  `ASK→ALWAYS` makes a grant moot and `ASK→DENY` blocks regardless of
  it; grants referencing a deleted app are inert (the app no longer
  resolves by URL).
- **No LLM needed to assess "would this task require approvals".** The
  set of apps with gated actions is fully deterministic: the tenant's
  configured external apps × stored policies, filtered to apps with ≥1
  `ASK` action — read from the same sources the matcher uses
  (`get_policies` + `get_endpoint_catalog`), so the editor's list can
  never disagree with the gate.

## Architecture

```
sandbox HTTPS ──► gate (mitmproxy) ── match → decisive policy
                    ├─ DENY ───► 403                      (unchanged)
                    ├─ ALWAYS ─► forward                  (unchanged)
                    └─ ASK
                        │  session origin == SCHEDULED
                        │  AND owning run RUNNING
                        │  AND match.external_app_id ∈ task grants?
                        ├─ yes ► insert action_approval pre-decided
                        │        (APPROVED, decided_via=pre_approval),
                        │        notify, forward — no park
                        └─ no ─► park ≤ 180s              (unchanged)
```

The lookup runs once per gated request, threaded, before the pending
row would be persisted. Any condition failing → existing park flow,
untouched. A partially-granted run degrades gracefully: requests to
non-granted apps park and expire exactly as today — per-app isolation
is the point.

## Data Model

No new table. New columns:

- `scheduled_task.pre_approved_app_ids` — JSONB list of `external_app`
  ids, NOT NULL default `[]`. Grants are tiny, always accessed via the
  task, and whole-list-replaced from the editor form, so a normalized
  table buys nothing. Validated against the tenant's apps and deduped
  at write time; stale entries are inert.
- `action_approval.decided_via` — nullable (`user | pre_approval`,
  NULL for legacy/expired rows): the audit marker distinguishing a
  human click from a pre-approval. Kept separate from `decision` so
  pre-approvals don't pollute terminal-decision semantics everywhere
  `decision == APPROVED` is checked. It records the gate's verdict, not
  delivery — credential injection can still fail the forward, and the
  row stays `APPROVED`.
- `action_approval.external_app_id` — nullable FK (NULL for legacy
  rows), populated from `match.external_app_id` on every new gated
  insert. Needed because `app_name` is not unique (self-hosted
  instances share an `app_type`); the run-history feedback loop and its
  one-click enable key off this id.

The gate's grant lookup lives in `backend/onyx/db/scheduled_task.py`;
pre-decided inserts go through `insert_action_approval` in
`backend/onyx/server/features/build/db/action_approval.py`.

## API

- `ScheduledTaskCreate` / `ScheduledTaskPatch` gain
  `pre_approved_app_ids: list[int]`; `ScheduledTaskDetail` returns it.
  The write path validates ids against the tenant's apps and dedupes —
  existence only; the credential and ≥1-`ASK` filters below are
  editor-side advisory (a grant on a no-`ASK` app is inert, never
  consulted).
- `GET /api/build/scheduled-tasks/approvable-apps` (existing router,
  `require_onyx_craft_enabled`): the external apps the user can
  actually use (org credentials or `is_user_authenticated_for_app`)
  that have ≥1 `ASK` action. Shape:
  `{external_app_id, display_name, actions: [{action_type,
  display_name}]}` — the FE keys toggles on `external_app_id` and
  renders the action list in the disclosure expander.
- `RunSummary` (the `/runs` payload) gains the apps whose approvals
  expired during that run (`[{external_app_id, display_name}]`, joined
  from EXPIRED `action_approval` rows via `session_id`) — this powers
  the feedback loop.
- New `NotificationType.SCHEDULED_TASK_PRE_APPROVED_ACTION`, emitted
  per `(run, app)` on the first unattended forward so chatty tasks
  don't flood the bell. Dedup rides `create_notification`'s existing
  `additional_data` key, which must carry only the stable
  `(run_id, external_app_id)` pair — anything per-request in it would
  defeat the dedup.

## UI

- **Task editor** (`ScheduleTaskForm`,
  `web/src/app/craft/v1/tasks/components/`): an "Approvals" section
  with one toggle per approvable app — "Allow this task to use
  **Slack** without asking" — plus a "see what this allows" expander
  listing the covered actions, and warning copy on enable. Types in
  `interfaces.ts`, client calls in `api.ts`.
- **Task detail page**: shows enabled apps; run rows whose approvals
  expired surface "Needed **Slack** approval" with one-click enable
  (PATCHes the grant onto the task). Grounded in an action that
  actually fired — no guessing.

## Lifecycle & Security

- **Prompt edits clear grants.** A `PATCH` whose `prompt` value differs
  from the stored one resets `pre_approved_app_ids` to `[]` — the grant
  was made against a specific intent, and a rewritten prompt must not
  inherit it. Resubmitting an identical prompt does not reset; the
  editor warns and lets the user re-enable in the same submit. Schedule
  changes do not reset grants; cadence doesn't change intent.
- **The grant boundary is the app.** There is no cross-app
  "auto-approve everything" toggle — that would convert any prompt
  injection into write capability across every connected app.
- **Only the task author can manage grants** — tasks are user-scoped
  and runs execute as the author, so grants never cross users.

## Risks

- **Prompt injection against pre-approved writes is inherent.** A
  poisoned context can drive a granted app's write with no human
  checkpoint. Mitigations: per-app (not global) grants, `DENY`
  supremacy, prompt-edit reset, and the unattended-forward
  notifications.
- **An app grant covers actions the user never enumerated**, including
  catalog actions added in later releases. Mitigated by the
  covered-actions expander at grant time and admin per-action `DENY`.
- **One extra DB round-trip per gated request on scheduled sessions.**
  Acceptable — `ASK` is already the slow path (row insert + notify),
  and the lookup is a single indexed join behind `asyncio.to_thread`.

## Future Work

- **"Allow for this task" on the live `ApprovalCard`** when the session
  resolves to a RUNNING scheduled run — approving also grants the app.
- **Per-action "advanced" subset** within an app grant, if a real
  customer asks.
- **Payload-level constraints** (e.g. "only this channel").
- **LLM prompt classification** to suggest which apps to pre-enable.
  Deferred: false negatives defeat the feature, false positives widen
  the attack surface.

## Tests

- **External dependency unit** (primary; existing homes):
  - `tests/external_dependency_unit/craft/test_approval_gate.py`: ASK +
    app granted + RUNNING run → pre-decided APPROVED row,
    `decided_via=pre_approval`, no park; run SUCCEEDED → parks;
    interactive-origin session → parks; matched app not in grants →
    parks; `DENY` decisive → 403 regardless of grant.
  - db-ops tests: prompt-edit PATCH resets grants; create/patch rejects
    unknown app ids and dedupes.
- **Integration**
  (`tests/integration/tests/craft/test_scheduled_tasks_api.py`): create
  task with grants, read back via detail; approvable-apps shape; an
  expired approval surfaces a resolvable `external_app_id` on the run
  payload (the feedback-loop join).
- No Playwright — the editor section is a standard form addition.

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
                        │  _resolve_auto_approval: first grant
                        │  source to cover this request wins
                        │  (today: RUNNING scheduled run whose
                        │  task grants match.external_app_id)
                        ├─ hit ► mint action_approval pre-decided
                        │        (APPROVED, decided_via), notify,
                        │        forward (fail-closed: dispatch raise
                        │        → 403, never an unguarded forward)
                        └─ none ► park ≤ 180s             (unchanged)
```

The lookup runs once per gated request, threaded, before the pending
row would be persisted. No source hitting → existing park flow,
untouched. A partially-granted run degrades gracefully: requests to
non-granted apps park and expire exactly as today — per-app isolation
is the point.

**Grant-source seam.** The short-circuit is not monolithic. In
`gate.py`, `_try_auto_approve` is the generic orchestrator;
`_resolve_auto_approval(db, ctx, match)` is the single extension point —
grant sources are checked in order, first hit wins, `None` parks. Each
source returns an `_AutoApproval` dataclass carrying `decided_via` plus
the notification payload; `_try_auto_approve` mints the row and
`_notify_auto_approved` are source-agnostic. The only source today is
`_scheduled_task_grant` (app-level, RUNNING scheduled run). This is the
seam future grant sources plug into — they add a `_resolve_auto_approval`
source and reuse the mint/notify path unchanged.

**Fail-closed dispatch.** mitmproxy forwards the original request on any
unhandled addon exception, silently bypassing the gate. In `request()`,
the auto-approved forward (`_dispatch_injection_or_block`) is wrapped in
try/except that sets `http_403(INTERNAL_ERROR)` on any raise — so an
unhandled exception cannot make the proxy forward the original request
unguarded after an `APPROVED` row is already committed.

## Data Model

New table `scheduled_task_pre_approved_app` — one row per `(task, app)`
grant:

- `scheduled_task_id` → `scheduled_task.id` (`ON DELETE CASCADE`) and
  `external_app_id` → `external_app.id` (`ON DELETE CASCADE`), with a
  `UNIQUE(scheduled_task_id, external_app_id)` constraint that keeps
  grants idempotent and serves the per-task lookup. The FKs give real
  referential integrity — a grant can't point at a removed app, and
  removing either side drops the grant. `ScheduledTask.pre_approved_apps`
  is the ORM collection; `pre_approved_app_ids` is a read-only accessor
  over it, so the API contract (`list[int]`) is unchanged. The write
  path replaces the whole set (`set_pre_approved_apps`), validated
  against the configured apps (via the tenant-scoped session) and
  deduped order-preserving.
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
  instances share an `app_type`); the planned run-history feedback loop
  keys its one-click enable off this id.

The gate's grant lookup lives in `backend/onyx/db/scheduled_task.py`;
pre-decided inserts go through `insert_action_approval` in
`backend/onyx/server/features/build/db/action_approval.py`.

## API

- `ScheduledTaskCreate` / `ScheduledTaskPatch` gain
  `pre_approved_app_ids: list[int]`; `ScheduledTaskDetail` returns it.
  The write path validates ids via `_validated_app_ids` and dedupes
  (order-preserving) — existence only; a credential / ≥1-`ASK` filter is
  editor-side advisory, since a grant on a no-`ASK` app is inert and
  never consulted.
- New `NotificationType.SCHEDULED_TASK_PRE_APPROVED_ACTION`, emitted
  per `(run, app)` on the first unattended forward so chatty tasks
  don't flood the bell. Dedup rides `create_notification`'s existing
  `additional_data` key, which must carry only the stable
  `(run_id, external_app_id)` pair — anything per-request in it would
  defeat the dedup.

## Lifecycle & Security

- **Grants are explicit and visible.** They are managed as checkboxes in
  the task editor and follow normal `PATCH` semantics — supplying
  `pre_approved_app_ids` replaces the set, omitting it leaves grants
  unchanged. Editing the prompt does not alter grants: the granted apps
  are shown alongside the prompt, so the author keeps or clears them as a
  deliberate, in-view choice rather than relying on an automatic reset.
- **The grant boundary is the app.** There is no cross-app
  "auto-approve everything" toggle — that would convert any prompt
  injection into write capability across every connected app.
- **Only the task author can manage grants** — tasks are user-scoped
  and runs execute as the author, so grants never cross users.

## Risks

- **Prompt injection against pre-approved writes is inherent.** A
  poisoned context can drive a granted app's write with no human
  checkpoint. Mitigations: per-app (not global) grants, `DENY`
  supremacy, grants shown in-editor next to the prompt, and the
  unattended-forward notifications.
- **An app grant covers actions the user never enumerated**, including
  catalog actions added in later releases. Mitigated today by admin
  per-action `DENY`; the planned grant-time covered-actions expander will
  surface the scope.
- **Grant lookup on the gated path.** Memoized per session in-process
  (`cachetools.TTLCache` via `@cachedmethod`, 60s TTL) so a run firing
  many actions hits Postgres once, not per request. The TTL bounds staleness from the
  RUNNING → terminal transition: an interactive follow-up on a finished
  scheduled session re-parks once the entry expires. The lookup itself
  is two indexed reads behind `asyncio.to_thread`.

## Planned (not in this PR)

This PR is backend-only — no `web/` changes. The next increment is the
feedback-loop UI plus the two read APIs that feed it:

- **Task editor** (`ScheduleTaskForm`,
  `web/src/app/craft/v1/tasks/components/`): an "Approvals" section, one
  toggle per approvable app — "Allow this task to use **Slack** without
  asking" — with a "see what this allows" expander and warning copy on
  enable.
- **Task detail page**: shows enabled apps; run rows whose approvals
  expired surface "Needed **Slack** approval" with one-click enable
  (PATCHes the grant onto the task). Grounded in an action that actually
  fired — no guessing.
- `GET /api/build/scheduled-tasks/approvable-apps`: the external apps the
  user can use (org credentials or `is_user_authenticated_for_app`) with
  ≥1 `ASK` action, for the editor toggles.
- `RunSummary` expansion: the apps whose approvals expired during a run
  (joined from EXPIRED `action_approval` rows via `session_id`,
  resolvable through the shipped `external_app_id`), to drive the
  one-click enable.

## Future Work

The grant-source seam means future modes drop in as new
`_resolve_auto_approval` sources without restructuring `request()`:

- **Session-scoped grants** — (a) "auto-approve all for this session",
  (b) per-app session grant, (c) per-action-type session grant (e.g.
  "allow Slack send-message this session but not other Slack `ASK`
  actions" — a source can scope on `match.decisive.action_type`, not
  just `match.external_app_id`). The store backing session-scoped grants
  is still to build; the gate integration point is the seam.
- **"Allow for this task" on the live `ApprovalCard`** when the session
  resolves to a RUNNING scheduled run — approving also grants the app.
- **Payload-level constraints** (e.g. "only this channel").
- **LLM prompt classification** to suggest which apps to pre-enable.
  Deferred: false negatives defeat the feature, false positives widen
  the attack surface.

## Tests

- **External dependency unit** (real SQL):
  `tests/external_dependency_unit/craft/test_scheduled_task_pre_approvals.py`
  - `get_live_scheduled_run_grants`: RUNNING run returns
    `(run_id, grants)`; non-RUNNING (SUCCEEDED / FAILED /
    AWAITING_APPROVAL) → `None`; interactive / no-run session → `None`.
  - `insert_action_approval`: pre-decided `APPROVED` vs default-pending.
  - Grant patch semantics: a prompt edit preserves grants, supplied
    `pre_approved_app_ids` replaces the set, and re-submitting an existing
    grant is idempotent (no unique-key collision).
  - Create persistence + `_validated_app_ids` dedupe and unknown-id
    rejection.
- **Unit** (gate, stubbed DB):
  `backend/tests/unit/sandbox_proxy/test_gate.py`
  - Granted + RUNNING → skips park, mints the `PRE_APPROVAL` row,
    notifies; non-RUNNING / not-granted / other-app / lookup-error all
    park; `DENY` wins before the grant lookup is reached;
    dispatch-failure-after-approval fails closed (403).
- **End-to-end (manual, local kind cluster):** the gate path was
  verified against the real proxy with a real Slack `chat.postMessage`
  through the egress gate — a granted RUNNING run forwarded with injected
  creds, a `gate.auto_approved` log line, a `PRE_APPROVAL` row, and the
  notification; non-RUNNING and ungranted parked; `DENY` → 403.
- No Playwright — no `web/` changes in this PR.

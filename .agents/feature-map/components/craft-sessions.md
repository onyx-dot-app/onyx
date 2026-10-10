# Craft Sessions

> The Craft session and its turn lifecycle: creating a session, sending a
> message, running an interactive turn against the sandbox's opencode agent,
> interrupting it, approvals, artifacts, and history.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** craft
**Edition:** CE, with the Craft feature gate itself sitting outside this
document (see [[craft-admin]])
**Owns:**
`backend/onyx/server/features/build/api.py`, `models.py`, `packets.py`,
`configs.py`, `timeouts.py`, `utils.py`, `debug.py`,
`backend/onyx/server/features/build/session/` (`api.py`, `manager.py`,
`messages.py`, `streaming.py` only at the handoff boundary, `models.py`,
`errors.py`, `locks.py`, `interrupt_signal.py`, `llm_config.py`, `naming.py`,
`sandbox_lifecycle.py`, `session_ready.py`, `md_to_docx.py`),
`backend/onyx/server/features/build/interactive_turns/` (`api.py`,
`executor.py`, `models.py`, `state.py`),
`backend/onyx/server/features/build/approvals/api.py`,
`backend/onyx/server/features/build/db/build_session.py`, `action_approval.py`,
`artifact.py`, `receipt.py`, `sandbox.py`, `user_library.py`,
`backend/onyx/server/features/build/user_library/api.py`,
`backend/onyx/server/features/build/sandbox/user_library.py`

**Read first:** `.agents/feature-map/components/core-chat-loop.md` for the
contrast (Craft is a parallel turn engine, not the chat loop), `docs/craft/
craft-main-plan.md` for the product overview, and `docs/craft/features/
streaming/preserve-opencode-sessions.md` for opencode history durability,
which this document leans on heavily in §4.5 and §9.

This document does **not** own: sandbox provisioning and pod lifecycle
mechanics (`[[craft-sandboxes]]`), parsing the opencode event stream itself
(`[[craft-streaming]]`, `session/streaming.py`'s translation layer), the
webapp preview (`[[craft-webapp-proxy]]`), external app connection and OAuth
(`[[craft-external-apps]]`), or scheduled/recurring runs
(`[[craft-scheduled-tasks]]`, `backend/onyx/server/features/build/
scheduled_tasks/`). It calls into all of them and names the boundary at each
call.

---

## 1. What the user experiences

A user opens Craft and gets one session per conversation, listed in a
sidebar. Sending a message starts a turn: the agent may think, run tools
(read and write files, run shell commands, call connected external apps),
and stream its answer back, the same way a coding-agent CLI would. Unlike
chat, a Craft turn is not a fixed number of LLM calls the backend loops
over; the entire agentic loop runs inside the sandbox's `opencode serve`
process, and the backend's job is to start it, stream its events, persist
them, and know when to stop.

The welcome panel starts on Files. Sending the first message keeps its selected tab,
expanded folders, cached listings, and scroll position. Returning from an inline
preview restores the tree scroll position. Each mounted Files browser owns its listing cache.
Folder requests run independently and abort when their directory unmounts.
A claimed welcome sandbox stays available until the URL selects the session.
Late validity checks cannot reset it. Mounting Files revalidates visible folders.
Opening a folder fetches its current contents, even when its cached listing is empty.

The composer moves from the welcome position to the conversation footer with
a shared layout animation. Reduced-motion users get an immediate transition.

A session with stale skills shows a blue information notice after its active turn
ends. Its Reload action refreshes that session’s skills.

The user can interrupt a running turn at any time. Partial output stays
visible and stays saved; sending a new message does not erase what was
already produced. When the agent is about to do something that needs
permission (per the app policy in `[[craft-admin]]` and `[[craft-external-apps]]`),
the turn pauses and the user sees an approval card; the user can approve or
reject just that request, or approve it for the rest of the session. Files
the agent produces appear as artifacts the user can browse, download, or
(for Markdown) export as a `.docx`. New previewable outputs add tabs; only the first
eligible discovery in a task selects a file. Manual selection or dismissal suppresses
automatic selection until the next interactive turn. See [[craft-streaming]] for
inventory and selection rules. The user's own uploaded library files
(PDFs, spreadsheets) are available inside every session's sandbox.

---

## 2. Surfaces

### HTTP endpoints

All routes below are mounted under `/build` (or `/build/admin`) and sit
behind `require_onyx_craft_enabled` except the admin-only ones
(`backend/onyx/server/features/build/api.py:router`, `:admin_router`).
`[[craft-admin]]` owns the gate itself; this document owns what the gate
protects.

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/build/sessions` | `list_sessions` (`session/api.py`) | |
| POST | `/build/sessions` | `create_session` (`session/api.py`) | Reserve-then-provision; see §4.1. |
| GET | `/build/sessions/{id}` | `get_session_details` (`session/api.py`) | |
| POST | `/build/sessions/{id}/skills/reload` | `reload_session_skills` (`session/api.py`) | |
| GET | `/build/sessions/{id}/sandbox-status` | `get_sandbox_status` (`session/api.py`) | DB-only, for the FE sleep poll. |
| POST | `/build/sessions/{id}/restore` | `restore_session` (`session/api.py`) | Wakes a sleeping sandbox and rebuilds the workspace; 409s under concurrent restore. |
| POST | `/build/sessions/{id}/snapshot` | `create_session_snapshot` (`session/api.py`) | Per-session workspace snapshot. |
| POST | `/build/sessions/{id}/opencode-history-snapshot` | `create_session_opencode_history_snapshot` (`session/api.py`) | Sandbox-global opencode history capture; see §4.5. Manual capture hook for tests and operators; no frontend caller (see §9). |
| GET | `/build/sessions/{id}/outputs` | `get_output_inventory` (`session/api.py`) | Flat file paths, sizes, and metadata revisions; no persistent index. |
| GET | `/build/sessions/{id}/artifacts` | `list_artifacts` (`session/api.py`) | |
| GET | `/build/sessions/{id}/artifacts/{path}` | `download_artifact` (`session/api.py`) | |
| GET | `/build/sessions/{id}/export-docx/{path}` | `export_docx` (`session/api.py`) | Uses `session/md_to_docx.py`. |
| DELETE | `/build/sessions/{id}` | `delete_session` (`session/api.py`) | |
| GET | `/build/sessions/{id}/messages` | `list_messages` (`session/messages.py`) | |
| POST | `/build/sessions/{id}/send-message` | `send_message` (`session/messages.py`) | **The turn endpoint.** Returns `InteractiveTurnResponse`, not a stream; see §4.2. |
| POST | `/build/sessions/{id}/subagents/{subagent_id}/send-message` | `send_subagent_message` (`session/messages.py`) | Bypasses the interactive-turn queue entirely; streams synchronously via `SessionManager.send_subagent_message`. See §9. |
| POST | `/build/sessions/{id}/interrupt` | `interrupt_message` (`session/messages.py`) | See §4.4. |
| GET | `/build/sessions/{id}/turns/active` | `get_active_interactive_turn` (`interactive_turns/api.py`) | Poll for the current turn's id/status. |
| GET | `/build/sessions/{id}/turns/{turn_id}/events` | `get_interactive_turn_events` (`interactive_turns/api.py`) | SSE attach/resume to a running turn; also (re)starts the runner if it stalled. |
| GET/PUT/POST/PATCH/DELETE | `/build/sessions/{id}/generate-name`, `/name`, `/public`, `/files`, `/pptx-preview/{path}`, `/output-thumbnail/{path}`, `/webapp-info`, `/webapp-download`, `/download-directory/{path}`, `/upload`, `/files/{path}`, `/scheduled-run-context`, `/scheduled-run-events` | `session/api.py` | Naming, sharing (`sharing_scope`), workspace file browse and upload, webapp info, and the scheduled-run banner and live events. |
| GET | `/build/approvals/sessions/{id}/live` | `list_live_approvals` (`approvals/api.py`) | |
| POST | `/build/approvals/{approval_id}/decision` | `submit_decision` (`approvals/api.py`) | |
| POST | `/build/approvals/{approval_id}/session-grant` | `submit_session_grant` (`approvals/api.py`) | Pre-approval; see §4.6. |
| GET/POST | `/build/user-library/tree`, `/build/user-library/upload`, `/build/user-library/upload-zip`, `/build/user-library/directories` | `user_library/api.py` | User library CRUD. |
| DELETE | `/build/user-library/files/{document_id}` | `delete_file` (`user_library/api.py`) | |
| GET | `/build/admin/base-instructions` | `get_base_instructions` (`api.py`) | Owned by `[[craft-admin]]`. |

### Environment / timeouts (`backend/onyx/server/features/build/configs.py`,
`timeouts.py` unless noted)

| Variable | Default | Effect |
|---|---|---|
| `INTERACTIVE_TURN_HARD_CAP_SECONDS` | 1800 (30 min) | Hard budget per turn; the executor force-ends the turn past this. |
| `INTERACTIVE_TURN_SOFT_BUDGET_SECONDS` | 40% of the hard cap | Sandbox-side wrap-up steer, stamped via `stamp_turn_deadline`. |
| `RUNNER_STALE_AFTER_SECONDS` | 6x `SSE_KEEPALIVE_INTERVAL` | A `RUNNING` turn whose runner stopped heartbeating this long becomes reclaimable by another API pod. |
| `ACTIVE_TURN_TTL_SECONDS` | hard cap + 15 min slack | Redis TTL on the turn's cache record. |
| `REQUEST_ID_TTL_SECONDS` | `ACTIVE_TURN_TTL_SECONDS` + 15 min | Idempotency window for a repeated `client_request_id`. |
| `PROMPT_SLOT_LEASE_SECONDS` | 120 | Sandbox-side per-session prompt lease (see §4.3, locking). |
| `PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS` | 10 | How long a fresh turn waits for the slot before failing. |
| `PROMPT_SLOT_WAIT_OUT_ORPHAN_SECONDS` | lease + 10 | How long a *reclaimed* turn waits (longer, to outlast an orphaned holder). |
| `OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS` | env-configured | A single opencode step going silent this long aborts that step; the executor re-prompts (see §4.2). |
| `SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS` | env-configured | How long the sandbox proxy parks on an `ASK` request before treating it as expired; also the "live" window `list_live_approvals` uses. |
| `SESSION_FLOW_LOCK_LEASE_SECONDS` | derived from provisioning deadlines | Lease on the per-user session-creation lock. |
| `ENABLE_OPENCODE_DEBUGGING` | false | Gates `debug.py`'s pod-log-stream endpoint; 404s (not 403) when off. |

---

## 3. Data model

```
BuildSession ──< BuildMessage
             ──< Artifact
             ──< ActionReceipt
             ──< Snapshot
             >──1 Sandbox (many sessions share one sandbox per user, via
                           `Sandbox.user_id`, which is unique)

ActionApproval ── gated_app (GatedApp, shared with [[craft-admin]])
ActionReceipt  ── gated_app, approval (nullable, SET NULL on delete)
```

### `BuildSession` (`backend/onyx/db/models.py:BuildSession`)

| Column | Meaning |
|---|---|
| `status` | `BuildSessionStatus` (`ACTIVE`, etc.). |
| `origin` | `SessionOrigin.INTERACTIVE` vs. non-interactive callers (scheduled-tasks executor, Slack); the sidebar filters on `INTERACTIVE`. |
| `opencode_session_id` | The opencode-serve session id, minted lazily on first turn. Persisted across sandbox restarts (see §4.5). |
| `agent_provider` / `agent_model` | The session's persisted model pick, decoded by `llm_config.py:parse_agent_selection`. |
| `skills_hash` / `mcp_config_hash` | What the sandbox's config was last reconciled against; drives `reconcile_session_llm_config`'s short-circuit. |
| `nextjs_port` | Reserved per session for the webapp preview; unique per user (`uq_build_session_nextjs_port`). |

### `Sandbox` (one row per user, `backend/onyx/db/models.py:Sandbox`)

`status`, `provisioning_attempt_number` / `provisioning_started_at` (fencing
against stale provisioning attempts), `skills_hash`, `mcp_config_hash`,
`encrypted_pat`. Owned in depth by `[[craft-sandboxes]]`; this document only
reads it to decide whether a turn can run.

### `Artifact` (`backend/onyx/db/models.py:Artifact`)

One mutable row per `(session_id, path)`, upserted at turn end
(`db/artifact.py:upsert_artifact`). `content_hash` drives change detection: a
changed hash bumps `version` and clears `archive_file_id`; an unchanged hash
only refreshes metadata. `deleted=True` keeps the row (so a stale FE card
greys out instead of 404ing) rather than removing it.

### `ActionReceipt` (`backend/onyx/db/models.py:ActionReceipt`)

Records one external write-effect action a session performed:
`action_type`, `effect` (read/write, captured at record time so it survives
later catalog reclassification), `destination`, `link`, `operation_key` (lets
multi-request provider flows, e.g. a chunked Slack upload, coalesce into one
receipt), `status` (`PENDING` → `CONFIRMED`/`FAILED`, swept to `UNKNOWN` after
`PENDING_RECEIPT_TTL` = 10 min if orphaned).

### `ActionApproval` (`backend/onyx/db/models.py:ActionApproval`)

One agent-initiated gated request: `actions` (a non-empty JSONB list,
sorted strictest-policy-first so `actions[0]` drove the gating decision),
`payload`, `decision` (`NULL` = pending), `decided_via`
(`ApprovalDecidedVia.USER`, `SESSION_GRANT`, or `PRE_APPROVAL`; the last is written by the proxy for scheduled-task grants, see `[[craft-scheduled-tasks]]`), `gated_app_id` (the shared
`GatedApp` identity row from `[[craft-admin]]`, `SET NULL` on delete so the
row survives as an audit record).

### `Snapshot`

Per-session workspace archive metadata (`storage_path`, `size_bytes`); owned
in depth by `[[craft-sandboxes]]`.

### User library

The user library is **not** a Craft-specific table. It reuses the ingestion
schema (the [[cc-pairs-and-credentials]] vocabulary: cc-pair, `Document`) with
`DocumentSource.CRAFT_FILE`: one shared "User Library" `Connector` per
deployment, one no-auth `Credential` per user, and `Document` rows whose
`id` is the deterministic `CRAFT_FILE__{user_id}__{sha256(path)[:16]}`
(`db/user_library.py:build_document_id`). Ownership is encoded in that
prefix; `fetch_user_file_for_user` returns `NOT_FOUND` (never 403) for a
mismatched prefix so existence is never leaked across users.

---

## 4. How it works

### 4.1 Session create / resume

```
POST /build/sessions                          session/api.py:create_session
  └─ session_creation_lock(user_id)            session/locks.py
       └─ get_or_create_empty_session          session/manager.py
```

Session and sandbox identities are **committed before external
provisioning**: "reserve, then reconcile, then finalize"
(`session/api.py`, comment on `create_session`). A failed or
interrupted attempt leaves durable, repairable state instead of rolling back
to nothing; a later request converges on the same IDs. The Redis lock only
reduces duplicate provisioning work under concurrency; correctness comes
from the committed reservation plus the sandbox's
`provisioning_attempt_number` fence (owned by `[[craft-sandboxes]]`).

A session becomes runnable through `ensure_session_ready`
(`session/session_ready.py:ensure_session_ready`), called both from the
`restore` endpoint and, per §4.2, from the interactive-turn runner itself
when the workspace isn't there. It:

1. Resolves and validates the session's LLM config up front
   (`session_manager.build_llm_configs`), before any external work.
2. Calls `ensure_sandbox_ready` (owned by `[[craft-sandboxes]]`) to get a
   `RUNNING`, health-checked pod.
3. If `sandbox_manager.session_workspace_exists` is already true, marks the
   session `ACTIVE` and returns; this is the fast path.
4. Otherwise restores the session's latest `Snapshot` (or writes a fresh
   workspace template), pushes managed content, and marks `ACTIVE`.

The caller must already hold the user's `session_creation_lock`
(`session/locks.py:session_creation_lock`): this step both provisions and
writes into the sandbox, and must not interleave with a reap, a second
restore, or another turn doing the same rebuild
(`session_ready.py`, module docstring). There is no separate "end session"
endpoint; `DELETE /build/sessions/{id}` deletes the record (best-effort also
deleting the live opencode session), and otherwise a session's runtime is
reclaimed by `[[craft-sandboxes]]`'s idle-reap, out of this document's scope.

### 4.2 The turn

```
POST /build/sessions/{id}/send-message          session/messages.py:send_message
  └─ create_interactive_turn (QUEUED, cache)    interactive_turns/state.py
  └─ start_interactive_turn_runner               interactive_turns/executor.py
       └─ claim_turn_for_runner (RUNNING)         interactive_turns/state.py
       └─ run_claimed_interactive_build_turn
            └─ _drive_interactive_turn
                 ├─ _ready_session_runtime        (fast path, or ensure_session_ready)
                 ├─ prompt_slot (lease)            session/manager.py:prompt_slot
                 ├─ drive_one_prompt (× ≤3)        yields sandbox events
                 │    └─ yield_sandbox_events       session/manager.py → session/streaming.py
                 │         (hands off to opencode-serve in the sandbox; see [[craft-streaming]])
                 ├─ persist_sandbox_event (per event)
                 └─ finalize_persist (terminal flush, streamed paths)
```

`send_message` (`session/messages.py`) does **not** stream. It creates a
`BuildMessage` user row, mints an `InteractiveTurn` cache record
(`QUEUED`), and starts a background thread
(`executor.py:start_interactive_turn_runner`) that the frontend then attaches
to via `GET /turns/{turn_id}/events`. This is the first structural
difference from chat: `[[core-chat-loop]]`'s `handle_send_chat_message` is
itself the streaming response; Craft's send endpoint returns immediately and
the actual work happens in a detached thread that any API replica can pick
up (see §4.3, locking).

**The turn is not a bounded cycle loop.** Chat's `llm_loop.py` runs up to
`MAX_LLM_CYCLES` inference-plus-tool-call rounds itself. Craft's executor
does not run an agentic loop at all: `drive_one_prompt`
(`interactive_turns/executor.py:_drive_interactive_turn.drive_one_prompt`)
sends one prompt to the sandbox's long-lived `opencode serve` process and
streams whatever events come back until the process itself decides the turn
is done (a `PromptResponse` event) or the step goes silent past
`OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS`. The entire multi-step agentic
reasoning (planning, tool calls, sub-loops) happens **inside opencode in the
sandbox**; the backend only streams and persists. The one bounded loop the
executor does run is over `MAX_TIMEOUT_CONTINUATIONS` (2) inactivity
timeouts: on a step timeout it flushes the partial output as its own message,
then re-prompts with a fixed steering message
(`_TOOL_TIMEOUT_CONTINUATION_PROMPT`) telling the agent to split the work up.

**No multi-model support.** Chat can fan a turn out to 2-3 models at once;
a Craft turn always drives exactly one opencode session with one resolved
model (`session_llm_config`).

**Persistence is incremental with a terminal flush for streamed paths, unlike
chat's `_persist_model_outcome`.** Every terminal path that streamed (success,
the hard-cap deadline, an unrecoverable sandbox error, an interrupt, an
unexpected exception in the drive loop) calls `session_manager.finalize_persist(session_id,
state)` (`interactive_turns/executor.py`, at least 5 call sites) followed by
`finish_turn(...)` to move the cache record to its terminal status. A failure
before streaming skips the flush. If `prompt_slot` is not acquired, the executor
persists an error row with `persist_turn_error` and calls `finish_turn`
directly. Unlike
chat, where persistence happens once *after* the loop ends, Craft persists
incrementally: `persist_sandbox_event` writes and commits **each** streamed
event as it arrives (`_drive_interactive_turn.drive_one_prompt`, "the caller
just returns" branches all follow a commit), and `finalize_persist` only
flushes whatever the per-turn `BuildStreamingState` accumulated since the
last flush. So there is no single "save the whole turn" transaction to point
to the way `save_chat_turn` is one; correctness instead rests on: no
streamed terminal path may skip its `finalize_persist` + `finish_turn` pair.

### 4.3 Locking

Three independent locks/leases, at three different scopes:

| Lock | Scope | Guards | Source |
|---|---|---|---|
| `session_creation_lock(user_id)` | per user | Serializes session/workspace creation, restore, and the interactive-turn runner's `_ready_session_runtime` fallback path. The idle reaper (`sandbox_lifecycle.py:sleep_sandbox`) holds it only for the workspace listing and for the final recheck before termination. It releases the lock while it snapshots. | `session/locks.py:session_creation_lock` |
| `prompt_slot(sandbox_id, session_id)` | per session | **Serializes turns within one session.** A second `send-message` while a turn holds the slot gets a `CONFLICT` ("busy with a previous turn") from `acquire_active_turn_lock`, or, if it reaches the executor, a `finish_turn(FAILED, "Concurrent turn in flight...")`. | `session/manager.py:prompt_slot` → `sandbox.serve_transport.PromptSlot` |
| `acquire_active_turn_lock(cache, session_id)` | per session, Redis | Guards the handful of read-modify-write Redis round-trips in `interactive_turns/state.py` (create/claim/touch/finish) so two API pods can't race the same turn's status. Lease (`TURN_LOCK_LEASE_SECONDS` = 60s) is independent of turn duration; ownership is decided by the `runner_id` compare inside the lock, not by the lease. | `interactive_turns/state.py:acquire_active_turn_lock` |

This is a distinct fence vocabulary from chat's stop/processing fences, but
the same *shape*: a Redis key acting as a flag, with a bounded lease and an
explicit ownership token (`runner_id` here; chat's `processing_run_id`
plays the analogous role). It also mirrors the general lock/lease pattern in
`[[background-jobs]]` (a lease that must exceed the critical section, with
ownership decided by an explicit compare, not by the lease alone) without
sharing code with it.

### 4.4 Interrupt

```
POST /build/sessions/{id}/interrupt        session/messages.py:interrupt_message
  └─ SessionManager.interrupt_message       session/manager.py:1019
       ├─ request_interrupt(session_id)      session/interrupt_signal.py  (cache fence)
       └─ abort_opencode_session (thread)     best-effort direct sandbox abort
```

Two complementary signals, by design (`manager.py:interrupt_message`
docstring): the interrupt **fence** (`interrupt_signal.py:request_interrupt`,
a cache key with a 10-minute TTL) covers the whole turn lifecycle, including
a turn that hasn't POSTed its prompt to opencode yet; a direct best-effort
`abort_opencode_session` call stops sandbox-side work even when no live
runner is polling the fence (a dead or blocked runner, or a different API
replica). The executor checks `is_interrupt_requested` both before starting
a prompt and inside the event-streaming loop
(`interactive_turns/executor.py:_drive_interactive_turn.interrupt_requested`),
which also doubles as the hard-cap deadline check.

**Partial output is saved before the turn ends.** On every path that detects
an interrupt, the executor calls `session_manager.finalize_persist(session_id,
state)` and commits **before** calling `finish_turn(..., CANCELLED)`
(`interactive_turns/executor.py`, the `interrupt_requested()` branch and the
`slot.lost` branch both do this). So at the backend/DB level, an interrupted
turn's already-streamed content is durable; nothing rolls it back.

On the frontend, `useBuildStreaming.ts:interruptStreaming` sets an
`isInterrupting` flag and calls `reconcileInterruptedTurn` **after** posting
the interrupt (`web/src/app/craft/hooks/useBuildStreaming.ts`).
`reconcileInterruptedTurn` still exists and is the load-bearing fix for the
historical bug: it polls `fetchActiveTurn` until the backend turn is gone,
then, in `settle()`, reloads the session (`loadSession(..., { force: true,
preferPersisted: true })`) **before** flipping session status back to
`"active"` (`useBuildStreaming.ts`, comment: "Reload BEFORE the flip
to active: the flip triggers the queued auto-send, so reloading after would
race the freshly-started next turn"). A queued resend cannot fire until the
reload has repopulated the interrupted turn's persisted output. This is
current, verified behaviour, not the historical bug: interrupting and
resending does not scrap the interrupted turn's rendered output today.

### 4.5 History durability

Two distinct persistence surfaces, per `docs/craft/features/streaming/
preserve-opencode-sessions.md` and confirmed against
`session/sandbox_lifecycle.py`:

- **Per-session workspace snapshots** (`outputs/`, `attachments/`): created
  by `create_session_snapshot_keep_latest`
  (`sandbox_lifecycle.py`), restored by `ensure_session_ready`. Owned in
  depth by `[[craft-sandboxes]]`.
- **Sandbox-global opencode history** (`.opencode-data/`, shared by every
  `BuildSession` in one sandbox): captured by
  `sandbox_manager.create_opencode_history_snapshot`, which is called from
  three places (owned in depth by `[[craft-sandboxes]]` §4.5):
  1. `sleep_sandbox` (`sandbox_lifecycle.py`, comment: "Chat
     history lives outside session workspaces; capture it before the
     [terminate]"), before putting an idle sandbox to sleep. If the snapshot
     fails but the pod still passes a health check, the reap is skipped
     rather than sleeping a healthy sandbox without fresh history.
  2. `cleanup_idle_sandboxes_task` (`background/celery/tasks/build/tasks.py`),
     a periodic background sweep: any sandbox with a session whose latest
     snapshot is older than `idle_timeout / SNAPSHOT_INTERVAL_DIVISOR` (15
     minutes at the default 1-hour idle timeout) gets re-snapshotted,
     including its opencode history, while still `RUNNING`.
  3. `snapshot_opencode_history_before_recovery`
     (`sandbox_lifecycle.py`), best-effort, before terminating an
     **unhealthy** sandbox during recovery.

**There is no per-turn capture.** The background sweep (`cleanup_idle_sandboxes_task`)
tries to keep opencode history fresh, with a target of
`idle_timeout / SNAPSHOT_INTERVAL_DIVISOR`. It gives no hard bound. It captures
history only after it creates a workspace snapshot, and a capture failure is
best-effort. The
manual endpoint `POST /sessions/{id}/opencode-history-snapshot`
(`session/api.py`) forces a capture. Tests and operators use it
(`backend/tests/integration/common_utils/managers/build_session.py`); no frontend
code calls it.
A sandbox that crashes hard within that bound, or is forcibly killed outside
the reaper's control, can still lose opencode history for turns since the
last successful capture. `BuildMessage` rows in Postgres are unaffected;
what's at risk is opencode's own resumable session state, meaning a restored
session mints a **replacement** opencode session with no prior context.
State this precisely: `BuildMessage` history (what the user sees on reload)
is never lost; opencode's own resumable-agent-state can be, within the
background-sweep bound. See `[[craft-sandboxes]]` for the reaper, sweep, and
recovery mechanics this depends on.

### 4.6 Approvals

```
sandbox proxy blocks an ASK-policied request        (owned by [[craft-admin]] / [[craft-external-apps]])
  └─ insert_action_approval (pending row)            db/action_approval.py
  └─ ApprovalRequestedPacket over SSE                packets.py, session/streaming.py
       (FE fetches full contents from /live, Postgres stays source of truth)
GET  /build/approvals/sessions/{id}/live             approvals/api.py:list_live_approvals
POST /build/approvals/{id}/decision                  approvals/api.py:submit_decision
POST /build/approvals/{id}/session-grant              approvals/api.py:submit_session_grant
  └─ try_record_decision (conditional UPDATE)         db/action_approval.py
  └─ approval_cache.send_wake                          wakes the parked proxy request
```

The enforcement point is the sandbox egress proxy (`[[craft-admin]]` §4.2),
not this component: an `ASK`-policied request is held there, waiting on the
approval row's decision. This document owns the human-facing side: the
pending row, the packet that tells the frontend to render a card
(`ApprovalRequestedPacket`, carrying only ids so the frontend refetches
contents from `/live` and Postgres stays the single source of truth,
`approvals/api.py` module docstring), and the decision endpoints.

`try_record_decision` (`db/action_approval.py`) is a conditional `UPDATE ...
WHERE decision IS NULL`, the sole race arbiter; a second decision on an
already-decided row returns the existing decision if it matches
(idempotent) or a `CONFLICT` if it doesn't. A decision wakes the parked
proxy request via a `approval:wake:{id}` cache channel
(`_send_wake_best_effort`); a missed wake just falls back to the proxy's own
`SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS` wait.

**Pre-approval is "session-grant", not a separate mechanism.**
`submit_session_grant` (`approvals/api.py`) approves the specific request
*and* every other currently-pending or future request in the session that
matches the same `(gated_app_id)` target and whose required action types are
a subset of what was just granted (`actions_requiring_approval`,
`approval_cache.hydrate_session_grants`). It re-scans currently-pending rows
for the same target and approves those too in the same call. There is no
separate admin-side "pre-approve this action type" endpoint in this
component; that would be the app's static policy (`ALWAYS`/`DENY`) owned by
`[[craft-admin]]`, a different mechanism from this in-session grant.

**An approval genuinely blocks, it does not merely warn.** The proxy holds
the outbound request open until a decision lands or the wait times out
(`SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS`); nothing in this pipeline lets the
sandbox proceed on an undecided or expired row. `list_live_approvals`
explicitly filters to rows created within that same wait window, treating
anything older as orphaned (the proxy that was waiting on it is gone), so
the frontend never offers to decide a request that can no longer have any
effect.

### 4.7 Artifacts, receipts, and export

Artifacts are a manifest, not a store: `upsert_artifact`
(`db/artifact.py`) is called once per `(session, path)` at turn end, keyed on
a content hash so an unchanged file is a metadata-only touch while a changed
one bumps `version` and invalidates any cached archive. `download_artifact`
and `export_docx` (`session/api.py:559,610`) read the live file out of the
sandbox workspace; `md_to_docx.py:markdown_to_docx_bytes` converts a
Markdown artifact to `.docx` with `mistune` + `python-docx`, pure-Python, no
external binary.

Receipts (`ActionReceipt`) are a separate concern from artifacts: they
record one external write-effect action (send a Slack message, create a
Drive file), inserted `PENDING` before the action executes
(`insert_pending_receipt`) and finalized `CONFIRMED`/`FAILED` after
(`finalize_receipt`, itself a conditional-UPDATE race arbiter like
`try_record_decision`). A `PENDING` row older than 10 minutes is swept to
`UNKNOWN` (`sweep_stale_pending_receipts`) so a crashed recorder never looks
like a silently-still-in-progress send.

### 4.8 User library

Upload/CRUD lives in `user_library/api.py` (thin HTTP layer) over
`db/user_library.py` (file-store I/O, `Document` upserts, ownership,
quota via `get_user_storage_bytes`). Sync into a sandbox is one-way
(database/file-store to sandbox) and happens at two points, both reusing the
same builder, `sandbox/user_library.py:build_user_library_fileset`
(a flat `{path: bytes}` `FileSet`, skipping directories and `sync_disabled`
files):

1. **On upload, upload-zip, or delete**:
   `sync_user_library_to_active_sandboxes` (`sandbox/user_library.py`) pushes
   the rebuilt set synchronously (no Celery) to every active sandbox.
   `set_sync_disabled` (`db/user_library.py`) has no production caller and
   the API has no toggle route, so a `sync_disabled` change triggers no sync.
2. **At session provisioning** (both a fresh session and a restore, inside
   `ensure_sandbox_ready`/`ensure_session_ready`, §4.1):
   `session/sandbox_lifecycle.py:build_managed_content_payload` reads
   `library_files=build_user_library_fileset(user.id, db_session)` alongside
   the skills payload, and `push_managed_content` (provision phase
   `SandboxProvisionPhase.HYDRATE_MANAGED_CONTENT`) pushes both to the
   sandbox, the library to `USER_LIBRARY_MOUNT_PATH`.

`docs/craft/features/user-library-sync.md` describes this same three-layer
architecture (HTTP/DB/sandbox-sync) correctly, but names a function,
`hydrate_user_library`, that **does not exist** in the current code (nor does
`create_session__no_commit`, which the doc also cites); the actual call sites
are the two above. Treat the doc's architecture as current and its specific
function names as stale.

### 4.9 Model selection

```
send_message / reconcile_session_llm_config     session/manager.py
  └─ session_llm_config → build_llm_configs       session/manager.py:280
       └─ build_onyx_gateway_config               session/llm_config.py
            └─ _select_gateway_default: persisted session pick
                 → configured defaults (craft, then chat)
                 → recommended-models.json
                 → first visible model
```

Priority, per `llm_config.py:_select_gateway_default`: (1) the session's own
persisted `agent_provider`/`agent_model`, if still visible and accessible;
(2) the admin's Craft default (`fetch_default_craft_model`,
`LLMModelFlowType.CRAFT`); (3) the admin's chat default
(`fetch_default_llm_model`); (4) each provider's recommended model
(`recommended-models.json`); (5) the first visible model of the first
provider. Per `[[llm-providers]]`, `CRAFT` is a pointer flow that nothing
populates automatically, so step (2) is frequently empty and step (3) is
the common case in practice. `reconcile_session_llm_config`
(`session/manager.py`) re-validates this on every turn (a stored pick
may no longer be accessible) and rewrites the sandbox's `opencode.json` only
when the resolved config actually changed, tracked via a
`dispose_pending` cache marker so a crash between writing the file and
disposing the stale opencode instance is retried on the next turn rather
than silently leaving the instance on the old config until pod death.

**Session naming does not use this resolution at all.**
`naming.py:generate_session_name` calls `get_default_llm()` (the workspace
chat default, `onyx/llm/factory.py`), independent of the session's own
agent model or the `CRAFT` flow. A Craft session can run on one model and be
auto-named by a different one.

---

### Output links in assistant messages

`TextChunk.tsx` recognizes relative output links in live and saved messages.
Validated links open the selected file and its output panel on click. The message
supplies the session ID; a link cannot select another session. Links use the existing
owner-checked artifact routes. Rendering the message does not open or fetch artifacts.
`pathSanitizer.ts:parseOutputLink` rejects traversal, hidden segments, encoded
separators, control characters, and query or fragment syntax. Invalid output links
render as text. Other links retain the existing Markdown behavior.
These frontend files live under `web/src/app/craft/`.

### Output inventory

`GET /build/sessions/{id}/outputs` checks session ownership before reading the sandbox.
It returns visible output file paths, byte sizes, and string revisions built from modification time, change time, and size.
The scan excludes hidden entries and the root `web` source tree. It reads metadata without hashing file contents.
The response sets `complete=False` when scan limits, unreadable entries, or an unrestored workspace prevent a full inventory.
An existing workspace with no outputs directory returns a complete empty inventory.
Callers must preserve unseen files when the response is incomplete.
The endpoint does not store an index or create artifact records.

## 5. Contracts and invariants

1. **A turn must be serialized per session.** `prompt_slot` plus the
   active-turn Redis lock are what enforce this; a change that lets two
   turns run concurrently for one session breaks §4.3 and risks two writers
   racing `BuildStreamingState`/opencode.
2. **An interrupted turn must not lose persisted output.** Every path in
   `_drive_interactive_turn` that detects an interrupt or a lost prompt slot
   calls `finalize_persist` and commits before `finish_turn`. A new code
   path that ends a turn without this ordering silently reintroduces the
   historical UI-loss bug at the DB layer, not just the FE layer.
3. **An approval must block the action, not merely warn.** The proxy holds
   the request open; nothing in this component may introduce a path where
   the sandbox proceeds without a `decision`. `try_record_decision`'s
   conditional UPDATE is the only allowed way to set `decision`.
4. **A session must not outlive its sandbox without a defined recovery.**
   `session_runtime_intact` is the fast-path check; anything that fails it
   must route through `ensure_session_ready` under the user's
   `session_creation_lock`, never rebuild a workspace ad hoc.
5. **History must reach durable storage before a healthy sandbox can be reaped.**
   `sleep_sandbox` aborts the reap when a workspace snapshot fails or when
   the opencode history snapshot fails on a pod that passes `health_check`.
   If the pod is unreachable, `sleep_sandbox` logs a warning and sleeps the
   sandbox without a fresh history snapshot. See §4.5 for this gap.
6. **A `client_request_id` makes `send-message` idempotent**, not merely
   deduplicated at the HTTP layer: `get_turn_for_request` returns the
   existing turn for a repeated id rather than creating a second one.
7. **`runner_id` is the sole ownership token for a claimed turn.** A
   `touch_turn`/`finish_turn` call without the matching `runner_id` must
   fail closed (return `False`/`None`), never silently act on a turn another
   runner now owns.

---

## 6. Relationships

**Depends on**
- [[craft-sandboxes]]: sandbox provisioning, health checks, idle-reap,
  snapshot/restore mechanics, and the opencode-serve process itself. This
  document only calls into it (`ensure_sandbox_ready`,
  `session_workspace_exists`, `create_opencode_history_snapshot`).
- [[craft-streaming]]: the opencode event stream and its translation into
  `BuildMessage`/SSE. This document's boundary is
  `SessionManager.yield_sandbox_events` and `persist_sandbox_event`; what
  happens inside `session/streaming.py`'s translation is not owned here.
- [[craft-webapp-proxy]]: the `nextjs_port` this document reserves per
  session is consumed there.
- [[craft-external-apps]]: the action catalog, credential injection, and
  policy resolution behind every `ASK`/`ALWAYS`/`DENY` decision this
  document's approval flow surfaces.
- [[craft-admin]]: the access gate wrapping every `/build` route, the
  `CRAFT` default-model flow, and organization instructions baked into the
  sandbox at session-ready time.
- [[craft-scheduled-tasks]]: shares `SessionManager.persist_sandbox_event`
  and `subscribe_to_existing_session_events` so a scheduled run's transcript
  is identical to an interactive one, but drives its own executor outside
  the interactive-turn queue in this document.
- [[llm-providers]]: `CRAFT` `LLMModelFlowType`, gateway model catalog,
  recommended-models fallback.
- [[background-jobs]]: not a code dependency, but the lock/lease/ownership-
  token shape in §4.3 mirrors it.
- [[cc-pairs-and-credentials]] and [[indexing-pipeline]]: the user library
  reuses `Document`/`ConnectorCredentialPair` with
  `DocumentSource.CRAFT_FILE` rather than owning its own table.

**Depended on by**
- `web/src/app/craft/`: the entire Craft frontend drives sessions and turns
  through this document's endpoints.
- [[craft-scheduled-tasks]]: a fired schedule creates a fresh `BuildSession`
  through the same session machinery.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| changes the turn executor (`interactive_turns/executor.py`) | every streamed terminal path still calls `finalize_persist` before `finish_turn` (the prompt-slot rejection path persists an error row instead); the timeout-continuation loop's `MAX_TIMEOUT_CONTINUATIONS` cap; `[[craft-streaming]]`'s event shapes the executor switches on (`PromptResponse`, `ActivityTimeoutError`, `SandboxError`) |
| changes locking (`prompt_slot`, `acquire_active_turn_lock`, `session_creation_lock`) | the CONFLICT-vs-silent-failure behavior at each acquisition site; whether a reclaim (`claim_turn_for_runner`) can still race a live runner; `[[craft-sandboxes]]`'s reaper, which also touches sandbox state under related locks |
| changes interrupt (`interrupt_signal.py`, `interrupt_message`) | the FE's `reconcileInterruptedTurn` polling contract (`fetchActiveTurn` going to `null`); whether partial output still commits before `finish_turn(CANCELLED)`; the direct `abort_opencode_session` best-effort path staying best-effort (not blocking) |
| adds an approval point | `ApprovalRequestedPacket` plumbing through `[[craft-streaming]]`; `list_live_approvals`'s time-window filter; whether the new point's target maps to a `GatedApp (kind, target_id)` the session-grant matching in `submit_session_grant` can actually cover |
| changes session state (`BuildSession` columns, `session_ready.py`) | `session_runtime_intact`'s fast-path check; `reconcile_session_llm_config`'s short-circuit comparison; any snapshot/restore path in `[[craft-sandboxes]]` that reads these columns |
| changes artifact upsert or hashing | the FE artifact list/version display; `export_docx`/`download_artifact`, which read the live workspace, not the DB row's cached bytes |
| changes user library sync | both trigger sets (upload/delete synchronous sync via `sync_user_library_to_active_sandboxes`, and session-provisioning sync via `build_managed_content_payload`/`push_managed_content`); the shared `Document`/cc-pair machinery other ingestion consumers also read |
| changes opencode history capture points | `[[craft-sandboxes]]`'s reaper, background-sweep, and recovery paths that are the three callers; the manual `/opencode-history-snapshot` endpoint, if you wire up a per-turn caller for the first time |

---

## 8. How to verify a change

### Tests

```bash
# Executor / turn state unit tests
cd backend && uv run pytest tests/unit/onyx/server/features/craft/interactive_turns/

# Session lifecycle, LLM config, snapshot API
cd backend && uv run pytest tests/unit/onyx/server/features/craft/session/
cd backend && uv run pytest tests/unit/onyx/server/features/craft/sandbox/test_ensure_session.py
cd backend && uv run pytest tests/unit/onyx/server/features/craft/test_session_gateway_config.py

# Interrupt, approvals, session lifecycle (external-dependency unit)
cd backend && uv run pytest tests/external_dependency_unit/craft/test_interrupt_message.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_turn_heartbeat_refresh.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_session_lifecycle.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_action_approval_db.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_approvals_api.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_scheduled_task_pre_approvals.py

# Integration
cd backend && uv run pytest tests/integration/tests/craft/test_sessions_api.py
cd backend && uv run pytest tests/integration/tests/craft/k8s/test_approval_gate.py
cd backend && uv run pytest tests/integration/tests/craft/k8s/test_session_provisioning_api.py
cd backend && uv run pytest tests/integration/tests/craft/k8s/test_user_library_sync.py
cd backend && uv run pytest tests/integration/tests/craft/docker_e2e/test_approval_gate_docker.py
```

See `backend/AGENTS.md` for the authoritative command forms and required
env. `backend/tests/integration/common_utils/managers/build_session.py` and
`build_approvals.py` are the shared test-driver helpers for this component.

### Local dev

Craft sandboxes are real Kubernetes pods; there is no non-cluster shortcut
for interactive session/turn work. `docs/craft/dev/local-kubernetes.md` is
the canonical setup: a local `kind` cluster pinned to Kubernetes `>= 1.33`
(native restartable init sidecar containers require it), `telepresence` for
DNS/VPN into the cluster, and the vscode debugger attached to
`api_server`/`celery`/`web`. Use `docs/craft/dev/local-compose-craft.md`
instead only when the change is in the docker sandbox backend or
`sandbox-proxy` specifically (`SANDBOX_BACKEND=docker`); it is slower for
general Craft work.
`deployment/helm/dev/k8s-up.sh` removes Kindnet's CPU limit and waits for its
rollout on both new and existing clusters. CPU requests and memory settings stay
unchanged. This prevents the container's CPU quota from throttling network-policy
processing and blocking sandbox egress during OpenCode startup.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Sign in at `http://localhost:3000` as `admin_user@example.com` /
   `TestPassword123!`, open Craft, start a new session.
3. Send a message that triggers a tool call (e.g. "create a file called
   notes.txt with today's date"). Confirm the artifact appears in the
   session's artifact list.
4. Send a longer-running message, then click stop mid-turn. Confirm the
   partial output stays visible, then send a follow-up message and confirm
   nothing from the interrupted turn disappears.
5. Trigger an action that needs approval (an enabled external app with an
   `ASK` policy on some action, per `[[craft-admin]]`). Confirm the approval
   card appears and the agent's action does not proceed until you decide.
   Approve "for the session" and confirm a second matching request from the
   same app does not re-prompt.
6. Reload the page mid-turn. Confirm the turn stream resumes rather than
   restarting (`GET /turns/{turn_id}/events` reattaching).

### What "working" looks like

- Exactly one turn runs per session at a time; a concurrent send gets a
  clear `CONFLICT`, not a silently dropped or duplicated turn.
- An interrupted turn's output survives a reload and a follow-up send.
- A `DENY`/`ASK` action never completes before a decision is recorded.

---

## 9. Footguns

- **A Craft "turn" delegates its agentic loop to the sandbox.** Do not look
  for a chat-style `MAX_LLM_CYCLES` while-loop in the executor; the
  multi-step reasoning happens inside `opencode serve`, and the backend's
  loop (`MAX_TIMEOUT_CONTINUATIONS`) exists only to recover from a silent
  step, not to drive the agent's reasoning.
- **`/build/sessions/{id}/opencode-history-snapshot` is a manual capture
  hook.** Tests and operators call it. No frontend code calls it. Do not
  assume a per-turn or per-send history capture happens. The automatic
  capture points are idle-reap sleep, the periodic background sweep, and
  best-effort pre-recovery (§4.5).
- **Subagent messages skip the interactive-turn queue entirely.**
  `send_subagent_message` (`session/messages.py`) streams synchronously
  through `SessionManager.send_subagent_message` →
  `streaming.py:stream_subagent_turn`, bypassing `create_interactive_turn`,
  `prompt_slot`, and the whole cache-turn lifecycle in §4.2-4.3. A change to
  turn serialization or persistence that only touches
  `interactive_turns/executor.py` will not reach subagent child-session
  messages.
- **Session naming and the session's actual agent model can diverge.**
  `naming.py` always uses the workspace chat default LLM, never the
  session's resolved Craft model. Do not assume the name-generation call is
  a lightweight proxy for "what model is this session running".
- **A matching `opencode.json` does not prove the running instance picked
  it up.** `reconcile_session_llm_config` uses a `dispose_pending` cache
  marker set *before* writing the file (not after) specifically to survive
  a crash between the write and the dispose; a config that looks correct on
  disk can still be running against a stale instance until the marker is
  cleared.
- **The `/compact` slash command described in
  `docs/craft/features/compact-command.md` is a design doc, not (yet) wired
  up in the frontend picker or a backend `kind="compact"` turn** at the time
  of writing; the `CompactionPacket`/`CompactionMarker` rendering path it
  builds on **is** implemented (automatic compaction renders today), but the
  manual trigger is not. Verify against code before citing this doc as
  current behaviour.
- **The subagents-view redesign in
  `docs/craft/features/subagents/2026-05-28-subagents-view-design.md` is
  also a plan, not current behaviour.** Today's subagent UI is the single
  collapsible `TaskBody` card
  (`web/src/app/craft/components/tool-cards/TaskBody.tsx`); the doc's
  side-panel live-transcript view depends on an unshipped "universal panel"
  refactor.
- **User library files are ordinary ingestion `Document` rows**, not a
  Craft-only table. A change to generic document/connector logic (deletion,
  metadata handling, permission sync) can silently affect Craft's user
  library, and vice versa.

### Output document thumbnails

`GET /build/sessions/{id}/output-thumbnail/{path}` returns a cached JPEG first page
for an owned session’s PDF or PowerPoint file. The shared document converter
checks workspace confinement and applies advisory size preflight before bounded rendering. Full PowerPoint
previews still use the existing slide endpoint.

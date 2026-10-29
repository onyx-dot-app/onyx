# Craft Sessions

> A Craft session is one conversation with a coding agent that runs in the
> user's sandbox; this component owns the session row, the interactive turn
> (start, run, stop, finish), attachments, output cards, the user library and
> the session's model.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

A user opens Craft and starts a session. The sidebar lists their interactive
sessions. Sessions with another origin, such as scheduled runs, do not appear
there.

The welcome page does not wait for the first message. The browser
pre-provisions an empty session and its sandbox when the user lands, so files
can attach and the agent can start at once. The first message claims that
session. Two welcome tabs share one empty session. When one tab claims it, the
other tab provisions a new one ([[craft-frontend]]).

The user sends a message. The agent thinks, runs shell commands, edits files
and calls connected apps, and the answer streams into the transcript. The turn
runs on the server. The user can reload, leave Craft, or open a second tab, and
the page attaches to the same running turn again. After the first turn the
session gets a short generated name. A manual rename always wins.

The user can stop a turn at any time. The partial output stays visible and
saved. Only one turn runs in a session at a time. A message typed during a turn
waits in a browser queue ([[craft-frontend]]).

When the agent tries an action that needs permission, the turn pauses and an
approval card appears ([[craft-external-apps]]).

The user can attach files to a message. The files go into the session
workspace's `attachments/` directory, and the agent can read them in this and
later turns. A session has a limit on the number and total size of its
attachments. An upload past the limit gets a 429 and the file is not stored.

Files that the agent writes under `outputs/` appear as cards under the turn
that changed them. The user can open or download them, and export Markdown as
`.docx`. PDF and PowerPoint outputs show a first-page thumbnail, and a deck
opens as slide images that the sandbox renders
(`server/features/build/session/manager.py:SessionManager.get_pptx_preview`).
Files in the user's library are available in every session.

When it fails, the user sees an error message in the transcript that stays
after reload. It says that saved files remain and that a follow-up can
continue. The causes:
- the turn ran past its hard time limit (30 minutes for interactive turns);
- the agent stopped without a final response, or the turn failed;
- another turn still held the session, so the message was not processed.

With no visible chat model, a session cannot start. A sleeping sandbox wakes
on the next turn, and the turn waits while the session workspace is restored
([[craft-sandboxes]]).

---

## Scope

This component owns the session lifecycle and repair, the interactive turn
record and its runner, interrupt, session attachments and their quota, output
cards and export, the user library, model selection and session naming.

Neighbours own the rest:
- [[craft-sandboxes]]: the pod, provisioning, sleep, snapshots, the session
  workspace layout, and opencode history durability.
- [[craft-streaming]]: the opencode client, event translation, what each event
  saves, the packet vocabulary, and the attach SSE endpoint.
- [[craft-external-apps]]: the egress proxy, action policy, approvals, and the
  connect-app request flow.
- [[craft-frontend]]: the browser stores, the prompt queue, and transcript
  settlement.
- [[craft-webapp-proxy]]: the preview of the session's web app and its port.
- [[craft-scheduled-tasks]]: the scheduled executor, which reuses session
  creation, persistence and output capture.
- [[craft-admin]]: the Craft access gate and the Craft default model setting.

---

## Architecture

```
POST /build/sessions/{id}/send-message        session/messages.py:send_message
  acquire_active_turn_lock -> idempotency check -> busy check
  check_token_rate_limits; save USER BuildMessage; create InteractiveTurn
  start_interactive_turn_runner               daemon thread, returns turn_id
    claim_turn_for_runner                     RUNNING, new runner_id
    _ready_session_runtime                    fast path, or ensure_session_ready
    prompt_slot(sandbox, session)             per-session cache lease
      reconcile_session_llm_config; stamp_turn_deadline
      capture_turn_outputs                    outputs/ baseline
      drive_one_prompt (up to 3)              yield_sandbox_events -> persist_sandbox_event
      finalize_persist                        flush buffered text
      persist_turn_outputs                    output cards
      finish_turn                             SUCCEEDED / FAILED / CANCELLED
GET /turns/{turn_id}/events                   browser attaches ([[craft-streaming]])
```

**The send endpoint does not stream.** A daemon thread in the same API
process runs the turn
(`server/features/build/interactive_turns/executor.py:start_interactive_turn_runner`).
If the runner stops its heartbeat for `RUNNER_STALE_AFTER_SECONDS`, the attach
endpoint on any replica can claim and restart it
(`server/features/build/interactive_turns/state.py:claim_turn_for_runner`).

**The turn is not a bounded cycle loop.** Chat's loop runs LLM cycles itself
([[core-chat-loop]]). Here `drive_one_prompt` sends one prompt to opencode and
streams events until opencode reports the end of the turn. All planning and
tool calls happen inside opencode. The executor loops only on inactivity
timeouts: it flushes the partial output as its own message, then prompts again
with `_TOOL_TIMEOUT_CONTINUATION_PROMPT`, at most `MAX_TIMEOUT_CONTINUATIONS`
times. Before the hard cap, a sandbox plugin tells the agent to finish at the
soft budget (`server/features/build/timeouts.py:INTERACTIVE_TURN_SOFT_BUDGET_SECONDS`).
The ordering of all turn timeouts is in the module docstring of
`server/features/build/timeouts.py`.

**Persistence is incremental.** `persist_sandbox_event` commits each event, and
`finalize_persist` flushes the buffered text. There is no single
save-the-turn transaction.

**Three locks at three scopes.**
- `server/features/build/session/locks.py:session_creation_lock` (per user,
  Redis): serializes create, restore, the interactive and scheduled runners'
  wake paths, attachment upload and delete, and the idle sweep's checkpoint and
  cleanup ([[craft-sandboxes]]). The
  restore endpoint acquires without blocking and returns 409.
- `SessionManager.prompt_slot` (per session, a renewable cache lease from
  `server/features/build/sandbox/serve_transport.py:_ServeMixin.prompt_slot`):
  one prompt at a time, because opencode's `prompt_async` is not safe under
  concurrent calls. It fails open when the cache is down, except for skill
  reload, which fails closed. A fresh turn waits
  `PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS`. A reclaimed turn waits out the dead
  holder's lease. Session delete, skill reload and sub-agent follow-ups take
  the same slot.
- `server/features/build/interactive_turns/state.py:acquire_active_turn_lock`
  (per session, cache): guards the short read-modify-write of the turn record.
  The `runner_id` compare decides ownership, not the lease.

**Session create is reserve, then reconcile.** The create endpoint calls
`SessionManager.get_or_create_empty_session` under the creation lock. That call
takes the user row lock and returns the user's one empty session (no messages)
if it exists ([[#empty-session-shared]]). A broken empty session is repaired
in place with the same id, never deleted and replaced. The session row
(`INITIALIZING`) and its preview port commit before any sandbox work.
`SessionManager._reconcile_session` builds the session workspace and the
opencode session, then marks the row `ACTIVE`, or `FAILED` for repair on the
next request. Port rules are in [[craft-webapp-proxy]].

**Interrupt has two signals.** `SessionManager.interrupt_message` sets a fence
keyed by `turn_id` (`server/features/build/session/interrupt_signal.py:request_interrupt`),
then calls opencode's abort if the same turn is still active. The fence covers
a turn that has not sent its prompt yet. The direct abort stops sandbox work
when no runner polls the fence. It runs while it holds the active-turn lock, so
its HTTP timeout stays short
(`server/features/build/configs.py:OPENCODE_SERVE_ABORT_TIMEOUT`). The executor's `interrupt_requested` closure
checks the fence and the hard-cap deadline.

**Output cards.** `server/features/build/session/output_cards.py` compares a
complete manifest of `outputs/` before and after the prompt, while the runner
holds the prompt slot. Changed paths become `Artifact` rows owned by that
`turn_index`. All of `outputs/web` is one app card. A file's
`source_revision` comes from modification time, change time and size, not from
a content hash. A changed `source_revision` adds one to the row's `version`
(`server/features/build/db/artifact.py:upsert_artifact`). The viewed routes
(`server/features/build/db/artifact.py:mark_outputs_viewed`) record the
`version` the owner opened in `viewed_revision`. `viewed_revision` only grows,
and a value above the row's `version` gets 409. The bulk route locks and checks
every row before it writes, so the request succeeds or fails as a whole.

**Model selection.** `server/features/build/session/llm_config.py:_select_gateway_default`
picks, in order: the session's saved model, the admin Craft default, the admin
chat default, each provider's recommended model, then the first visible model.
Only chat-capable visible models qualify. Image attachments go to the model
only when the session's model accepts image input; every attachment also
reaches the agent as a path in the prompt
(`server/features/build/session/messages.py:send_message`). A model on
`send_message` rewrites
the session's saved model before the turn starts, so the browser sends one only
after the user picks it ([[craft-frontend#model-only-after-pick]]).
`reconcile_session_llm_config` runs on every turn and rewrites `opencode.json`
only when the resolved config changed. opencode sends the session id on every
gateway call (`server/gateway/configs.py:CRAFT_SESSION_HEADER`), and
[[llm-gateway]] uses it for attribution.

**User library.** Library files are ordinary `Document` rows with
`DocumentSource.CRAFT_FILE`, one shared connector per deployment and one
credential per user (`server/features/build/db/user_library.py:build_document_id`).
Uploads and deletes push the full file set to the user's sandbox when it is
`RUNNING` (`server/features/build/sandbox/user_library.py:sync_user_library_to_active_sandboxes`).
Provisioning pushes it again with the other managed content.

**Skills reload.** `SessionManager.reload_session_skills` refuses while the
sandbox is `PROVISIONING` and while a turn holds the prompt slot. It rewrites
the session's `opencode.json` and `AGENTS.md` before it disposes the live
opencode instance, so the next instance reads the new files ([[skills]]).

---

## Contracts and traps

1. `flush-before-finish` **Every terminal path that streamed flushes before it
   finishes.** In `server/features/build/interactive_turns/executor.py:_drive_interactive_turn`,
   each streamed exit calls `finalize_persist` and commits, then the `finally`
   runs `persist_turn_outputs` and `finish_turn`. The attach stream sends
   `turn_completed` only after `finish_turn`, and the browser then reads saved
   history ([[craft-frontend]]). An exit that skips the flush loses the tail of
   the transcript. An exit that leaves `completion_status` unset leaves the turn
   active, and once its heartbeat is stale an attached stream reclaims it and
   sends the prompt again. Only a runner that lost ownership may exit without
   a flush and a status, because its successor owns the turn.
2. `runner-id-ownership` **`runner_id` is the only ownership token.**
   `server/features/build/interactive_turns/state.py:touch_turn` and
   `finish_turn` with a stale `runner_id` change nothing. A `runner_id` of
   `None` skips the compare; only `send_message` uses it, for a turn that no
   runner has claimed. The runner checks ownership again after the slot wait
   and before the prompt POST. Do not add a path that writes the turn without
   the compare.
3. `prompt-slot-serializes-writers` **The prompt slot is the only serializer
   that covers every writer to the opencode session.**
   `server/features/build/session/manager.py:SessionManager.prompt_slot` is
   the entry point. The active-turn busy
   check in `send_message` does not cover sub-agent follow-ups or session
   delete. Anything that sends a prompt, rewrites the session's opencode
   config, or removes the session workspace must take `prompt_slot`.
   Attachment upload and delete do not take it: they only add or remove files
   that the agent reads by path.
4. `client-request-id-idempotent` **A repeated `client_request_id` returns the
   same turn.** `server/features/build/interactive_turns/state.py:get_turn_for_request`
   makes `send-message` idempotent for `REQUEST_ID_TTL_SECONDS`. The browser
   queue relies on this for retries ([[craft-frontend#queued-request-id-stable]]).
5. `interrupt-no-leak` **Interrupt must not leak to a successor.** The fence is
   keyed by `turn_id`, and the abort runs only if the selected turn is still
   the active turn. The runner clears its fence and deadline stamp only while
   it still owns the turn
   (`server/features/build/interactive_turns/executor.py:_can_clear_interrupt_fence`).
   Keep both checks.
6. `repair-through-ensure-session-ready` **Session repair goes through
   `ensure_session_ready` under the creation lock.**
   `server/features/build/session/session_ready.py:session_runtime_intact` is a
   database-only fast path. A `RUNNING` row is a claim, so the runner also
   checks the pod. Do not rebuild a session workspace anywhere else. An opencode
   instance keeps the config it saw at creation, so a turn that runs during a
   rebuild stays on the wrong config for the life of the pod (module docstring
   of `server/features/build/session/session_ready.py`).
7. `attachment-quota-row-lock` **The session row owns the attachment quota.**
   `server/features/build/session/manager.py:SessionManager.upload_file` locks
   the `BuildSession` row, checks `MAX_UPLOAD_FILES_PER_SESSION` and
   `MAX_TOTAL_UPLOAD_SIZE_BYTES`, and writes the file while it holds the lock,
   so concurrent uploads share one limit. A new path that writes into
   `attachments/` must take the same row lock. It must also hold
   `session_creation_lock`, as the upload and delete endpoints do, and commit a
   sandbox heartbeat before the write
   ([[craft-sandboxes#cleanup-proof-not-cache]]).
8. `dispose-pending-marker` **A matching `opencode.json` does not prove that
   opencode loaded it.** `SessionManager.reconcile_session_llm_config` sets a
   dispose-pending cache marker
   (`server/features/build/session/manager.py:mark_opencode_dispose_pending`) before it
   writes the file, so a crash between write and dispose is retried on the
   next turn. `ensure_session_ready` sets the same marker before a rebuild. A
   new config writer must set it first.
9. `output-attribution-complete-pair` **Output attribution needs a complete
   before-and-after pair.**
   `server/features/build/session/output_cards.py:capture_turn_outputs` takes
   the baseline and `persist_turn_outputs` compares against it. A reclaimed
   runner skips the baseline. An
   incomplete scan or lost ownership writes nothing. A later turn's row is
   never moved back to an earlier turn.
10. `user-library-rules` **User library ownership is the document id prefix.**
    `server/features/build/db/user_library.py:fetch_user_file_for_user` returns
    `NOT_FOUND`, never 403, for another user's file. `store_user_file` returns
    the old blob id: pass it to `cleanup_old_blobs` only after the final commit.
    Generic `Document` and connector changes (deletion, metadata, permission
    sync) also reach the library.
11. `empty-session-shared` **The empty session is shared, not private to one
    tab.**
    `server/features/build/session/manager.py:SessionManager.get_or_create_empty_session`
    returns the same session
    id to every caller until a message lands in it. Code that treats a
    pre-provisioned id as owned by one tab sends both tabs' first messages into
    one session. The browser polls
    `server/features/build/session/api.py:check_pre_provisioned_session` to detect a
    claim ([[craft-frontend#pre-provisioned-session-shared]]).
12. `artifact-lock-order` **Lock `Artifact` rows in bytewise path order.**
    Output capture (`server/features/build/session/output_cards.py:persist_turn_outputs`)
    upserts rows in `sorted()` path order in one transaction.
    `mark_outputs_viewed` locks with `Artifact.path.collate("C")` to match. A
    new writer that locks several rows in another order can deadlock with
    capture at the end of a turn.

---

## Decisions

- **Detached runner instead of a streaming request.** A turn can run for 30
  minutes. If one HTTP response held the turn, a reload or a replica restart
  would end it.
- **Reserve before provisioning.** A failed create leaves a durable
  `INITIALIZING` or `FAILED` row with the same ids, so a retry repairs it
  instead of creating orphans.

---

## Known issues

- **Opencode history has no per-turn capture.** Saved `BuildMessage` rows
  never get lost. The agent's own resumable state can, between background
  captures. A restored session that cannot find its opencode session id gets a
  new opencode session with no prior context ([[craft-sandboxes]],
  [[craft-streaming#only-404-replaces-opencode-session]]). Session delete
  removes the live opencode session only when the sandbox is active, and a
  failed removal does not stop the delete
  (`server/features/build/session/manager.py:SessionManager.delete_session`).
  It never edits the opencode history archive, so the deleted session's
  opencode rows can stay in the archive.
- **The history snapshot endpoint is a manual hook.**
  `POST /build/sessions/{id}/opencode-history-snapshot` forces a capture for
  tests and operators. No frontend code calls it, and no turn calls it.
- **Sub-agent follow-ups bypass the turn record.** `send_subagent_message`
  streams from the request itself
  (`server/features/build/session/streaming.py:stream_subagent_turn`). It has no
  `turn_id`, no reattach and no interrupt fence, and a client disconnect ends
  it. It does not save the follow-up prompt, and it saves its rows with
  `turn_index` 0. Reload rebuilds it on a best-effort basis from routing
  metadata.
- **Naming uses a different model.**
  `server/features/build/session/naming.py:generate_session_name` calls the
  admin default chat model, not the session's model.
- **No manual compaction.** Only opencode's automatic compaction appears in
  the transcript.
- `server/features/build/db/user_library.py:set_sync_disabled` has no route,
  so a `sync_disabled` change never triggers a sync.
- `server/features/build/db/receipt.py` (`ActionReceipt`) has no caller
  outside its tests. Nothing records external write actions or sweeps stale
  receipts.

---

## Dependencies

- [[craft-sandboxes]]: `ensure_sandbox_ready`, session workspace setup and
  restore, `prompt_slot`, and history capture.
- [[craft-streaming]]: `yield_sandbox_events`, `persist_sandbox_event`, and
  the attach endpoint the browser uses.
- [[craft-external-apps]]: approvals and action policy.
- [[craft-admin]]: the access gate and the Craft default model.
- [[llm-providers]]: provider access and the `CRAFT` and `CHAT` default flows.
- [[rate-and-usage-limits]]: `send_message` calls `check_token_rate_limits`.
- [[cc-pairs-and-creds]]: the library's connector and credential rows.

---

## Recipes

- `new-executor-exit` **A new terminal path in the executor.** Copy the `deadline_exceeded` exit
  in `_drive_interactive_turn`. List the exits with
  `git grep -n 'completion_status = ' backend/onyx/server/features/build/interactive_turns/executor.py`.
  Flush with `finalize_persist` and commit if anything streamed, add a
  user-visible row with `persist_turn_error`, set `completion_status`, and
  return inside the slot block so the `finally` runs output capture and
  `finish_turn` ([[#flush-before-finish]]).
- `new-workspace-writer` **A new writer to the session workspace.** Copy
  `SessionManager.upload_file` and its endpoint. Take `prompt_slot` if opencode
  can observe the change ([[#prompt-slot-serializes-writers]]), hold
  `session_creation_lock`, commit a sandbox heartbeat before the write, and
  add a session-row lock if a quota applies ([[#attachment-quota-row-lock]]).
- `investigate-stuck-turn` **Investigate a turn that does not finish.** Read the turn through the
  frontend: `GET http://localhost:3000/api/build/sessions/<id>/turns/active`,
  then `.../turns/<turn_id>`. The API does not return `runner_id` or
  `last_heartbeat_at`. For them, read the cache key
  that `server/features/build/interactive_turns/state.py:_turn_key` builds (the
  cache adds the tenant prefix), and compare the heartbeat age with
  `RUNNER_STALE_AFTER_SECONDS`. Search
  `backend/log/api_server_debug.log` for the `turn_id`. A live runner with
  no events points to the stream, not the turn.
- `session-test-setup` **Set up a session for a test.** Integration tests use the shared module
  session in `backend/tests/integration/tests/craft/conftest.py` and
  `backend/tests/integration/common_utils/managers/build_session.py`. Local
  sandbox setup is in the `onyx-craft-dev` skill.

---

## Verification

- Unit: `backend/tests/unit/onyx/server/features/craft/` (`interactive_turns/`,
  `session/`, and the timeout-order test).
- External dependency: `backend/tests/external_dependency_unit/craft/`.
- Integration: `backend/tests/integration/tests/craft/`, including the `k8s/`
  suite.
- By hand: stop a turn, reload, and send a follow-up. Nothing from the stopped
  turn may disappear.

# Craft Streaming

> How a Craft turn's output reaches the browser: the `opencode serve` client,
> the per-(sandbox, directory) event bus, the attach-based SSE endpoint, and the packet
> vocabulary. Craft does not reuse chat's `Packet`/`Placement` wire format; it
> has its own, and its reconnect story is weaker than chat's. See
> [[streaming-protocol]] for the contrast.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** craft
**Edition:** CE
**Owns:**
`backend/onyx/server/features/build/sandbox/opencode/serve_client.py`,
`sandbox/serve_transport.py`, `sandbox/opencode/event_bus.py`, `sandbox/sse.py`,
`sandbox/event_schema.py`, `packets.py`, `session/streaming.py`,
`session/messages.py`, `interactive_turns/api.py`, `interactive_turns/executor.py`,
`interactive_turns/state.py`,
`web/src/app/craft/hooks/useBuildStreaming.ts`, `utils/parsePacket.ts`,
`utils/subagentRouting.ts`, `services/apiServices.ts`

**Read first:** `docs/craft/features/streaming/opencode-serve-client.md` for the
client's design intent, and `docs/craft/issues/opencode-serve-event-stream-pitfalls.md`
for three real bugs this layer had to fix. Both are still accurate: **most of
`docs/craft/features/streaming/` describes history, not present behaviour**
(see §9).

---

## 1. What the user experiences

The user sends a message and watches the agent think, call tools (bash, edit,
search, a sub-agent task), and answer, all streaming token by token into the
Craft transcript. Approvals pop up mid-turn when the agent wants to touch a
connected external app. If the tab reloads or the connection drops mid-turn,
reopening the session re-attaches to the turn already running in the
background and continues rendering it live; it does not lose the turn, but it
also does not replay, byte-for-byte, whatever the client missed while
disconnected (see §5, §9).

Connected app setup cards link to **App permissions**. This opens Tools > Approval settings in plugin details, without delaying authentication.
The editor covers external apps and MCP servers. Workspace-disabled actions
remain visible and locked. Task editors use the same action rows with
independent saved choices.

Approval cards keep **Approve once**, **Approve for session**, and **Reject**.
All three call the approval decision endpoint. The session polls lightweight
approval status every ten seconds. Status changes refresh the history. The history
contains live requests and recent outcomes. Completed requests become compact,
neutral tool rows with details collapsed. Expired requests state that the action
did not run; only pending requests keep the attention border and decision buttons.
Approval cards use the server live status to show expiry. Device clock differences cannot block decisions.
The displayed approval deadline comes from the server; a browser does not own the wait.

The Working group shows the tool-call count without a failed-count badge.
Its tool details start collapsed, including failures; users can expand each call
to read its output.

A sub-agent ("task" tool) has a separate sub-agent view (`SubagentView.tsx`).
That view shows the sub-agent's own thinking and tool calls live while the
run is active. The parent transcript shows only the task prompt and the final
answer.

---

## 2. Surfaces

### HTTP endpoints (router prefix `/build`, unless noted)

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/sessions/{id}/send-message` | `messages.py:send_message` | Starts a turn and returns immediately with an `InteractiveTurnResponse` (a `turn_id`). Does **not** stream. |
| GET | `/sessions/{id}/turns/active` | `interactive_turns/api.py:get_active_interactive_turn` | Poll target: is a turn currently running for this session. |
| GET | `/sessions/{id}/turns/{turn_id}/events` | `interactive_turns/api.py:get_interactive_turn_events` | **The stream.** NDJSON-free SSE (`text/event-stream`), `event: message` records. Attach-only: does not start a turn, only follows one that `send-message` already created. |
| POST | `/sessions/{id}/subagents/{subagent_session_id}/send-message` | `messages.py:send_subagent_message` | Sends a follow-up prompt directly into a running sub-agent's opencode session. |
| POST | `/sessions/{id}/interrupt` | `messages.py:interrupt_message` | Sets the interrupt fence the runner polls (see §4.3). |
| GET | `/sessions/{id}/scheduled-run-events` | `session/api.py:get_session_scheduled_run_events` | Same wire format, for watching a Celery-driven scheduled run instead of an interactive turn. |

`get_interactive_turn_events` is the sole owner of turning a running turn into
bytes for one browser tab. Two tabs open on the same turn each get their own
subscriber queue off the same `PodEventBus` (§4.2); neither is authoritative.

### Environment configuration (`backend/onyx/server/features/build/configs.py`, `timeouts.py`)

| Variable | Default | Effect |
|---|---|---|
| `SSE_KEEPALIVE_INTERVAL` | 15s | Default keepalive cadence. Interactive browser attachments use 1s to detect completion missed during attachment. |
| `OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS` | derived from `SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS` | Renewed by turn activity. It aborts a silent prompt step after this long. The runner re-prompts up to `MAX_TIMEOUT_CONTINUATIONS` (2) times before it fails the turn (`interactive_turns/executor.py`). |
| `OPENCODE_SERVE_CONNECT_TIMEOUT` / `_REQUEST_TIMEOUT` / `_EVENT_READ_TIMEOUT` | 5s / 30s / 60s | HTTP timeouts from the API server to the in-pod `opencode serve` process. |
| `OPENCODE_SERVE_SESSION_INIT_TIMEOUT` | 90s | HTTP read/write timeout for `ensure_session` lookup and creation, which can initialize a cold directory. Ordinary requests use 30s. |
| `SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS` | 180s | How long a turn waits on an unanswered approval before it times out. |
| `RUNNER_STALE_AFTER_SECONDS` (`timeouts.py`) | `6 * SSE_KEEPALIVE_INTERVAL` | A `RUNNING` turn with no heartbeat this long is reclaimable by a new runner. |
| `INTERACTIVE_TURN_HARD_CAP_SECONDS` (`timeouts.py`) | 30 min | Hard wall-clock budget for one turn (`run_claimed_interactive_build_turn`). |
| `ACTIVE_TURN_TTL_SECONDS` (`timeouts.py`) | hard cap + reclaim slack | TTL of the turn's cache record. |

---

## 3. Data model

Like [[streaming-protocol]], packets themselves are never written to
Postgres as a stream; what gets written is either the *result* or, for a few
packet families, the packet itself as a `BuildMessage.message_metadata` blob.
This component does not own the `BuildMessage`/`BuildSession` tables
([[craft-sessions]] does), but it is the sole writer of the streaming rows on
them:

- `persist_sandbox_event` (`session/streaming.py:persist_sandbox_event`)
  accumulates `AgentMessageChunk`/`AgentThoughtChunk` text and flushes it as
  one `BuildMessage` row per `agent_message`/`agent_thought` block. It persists
  `ToolCallProgress` only on `status in ("completed", "failed")` (and every
  update for `todowrite`), and upserts `AgentPlanUpdate` in place
  (`upsert_agent_plan`). `ToolCallStart`, `CurrentModeUpdate`, `PromptResponse`,
  and unrecognized types are **not persisted**.
- A completed `task` tool call (a sub-agent) additionally persists a synthetic
  `agent_message` row (`source: "task_output"`) so the sub-agent's final answer
  shows up in the parent transcript even though its live activity was not
  captured (`session/streaming.py:persist_sandbox_event`, the `is_task_tool`
  branch).

**The turn itself is cache-backed, not a DB row**, unlike chat's
`ChatMessage`/processing-fence split:

- `InteractiveTurn` (`interactive_turns/state.py:InteractiveTurn`) lives in
  `CacheBackend` under a `turn_id` key, TTL `ACTIVE_TURN_TTL_SECONDS`. It
  carries `status` (`QUEUED`/`RUNNING`/`SUCCEEDED`/`FAILED`/`CANCELLED`),
  `runner_id`, and `last_heartbeat_at`.
- A session-scoped "active turn" pointer and a lock
  (`_active_turn_key`, `_active_turn_lock_key`) enforce one live turn per
  session.
- There is **no packet-level durable buffer** analogous to chat's
  `stream_buffer.py`. See §5.9.

---

## 4. How it works

### 4.1 The path from agent process to browser

```
opencode serve (in-pod)              GET /event (raw SSE from opencode)
  └─ PodEventBus._reader_loop         sandbox/opencode/event_bus.py
     one long-lived subscription per (sandbox_id, directory), fanned out by session_id
       └─ per-session Queue           _Subscription.queue
          ├─ OpencodeServeClient.send_message      (turn-owning path)
          │    consumes its own subscription, translates raw opencode
          │    events → SandboxEvent via translate_opencode_event
          └─ SandboxManager.subscribe_to_opencode_session
               (serve_transport.py)  same translation, for late/second attaches

translate_opencode_event() → SandboxEvent (AgentMessageChunk, ToolCallStart, …)
  │
  ├─ interactive_turns/executor.py: _drive_interactive_turn
  │    persists via persist_sandbox_event, forwards live via merge_events_with_announces
  │
  └─ interactive_turns/api.py: get_interactive_turn_events
       session_manager.subscribe_to_existing_session_events()
         → event_to_sse() → "event: message\ndata: {...}\n\n"
           → StreamingResponse(text/event-stream)
             → browser: processSSEStream() → parsePacket() → BuildMessageList
```

The turn-owning runner (`_drive_interactive_turn`) and the browser's SSE
attach are **two independent consumers of the same `PodEventBus`**, not
producer and consumer of one pipe. The runner drives the turn (posts the
prompt, persists rows, decides when the turn ends) whether or not a browser is
attached; the browser attach only subscribes to render it live. This is the
load-bearing difference from [[core-chat-loop]], where the HTTP request itself
drives the turn.

### 4.2 The opencode-serve client and the shared bus

`OpencodeServeClient` (`sandbox/opencode/serve_client.py:OpencodeServeClient`)
is an HTTP client over one `opencode serve` process per sandbox pod
(`ensure_session`, `send_message`, `get_message`, `abort`). It does not itself
own the SSE connection to opencode: that is `PodEventBus`
(`sandbox/opencode/event_bus.py:PodEventBus`), one reader per
`(sandbox_id, directory)` (the opencode `/event` stream is scoped by `?directory=`) that
opens `GET {base_url}/event`, parses raw SSE blocks
(`_parse_sse_block`), and dispatches each event to every subscriber whose
`session_id` matches (`PodEventBus._dispatch`). One dead upstream connection
reconnects with exponential backoff (1s → 30s) and gives up after 20
consecutive failures, self-closing the bus (`PodEventBus._reader_loop`).

`translate_opencode_event` (`serve_client.py:translate_opencode_event`) is the
single function that turns a raw opencode JSON event into zero or more
`SandboxEvent`s. It is the load-bearing translator the three pitfalls in §5
and §9 were found in.

### 4.3 The interactive turn lifecycle

`POST /sessions/{id}/send-message` (`session/messages.py:send_message`)
creates a `BuildMessage` (the user's message), a cache-backed `InteractiveTurn`
(`interactive_turns/state.py:create_interactive_turn`), and starts a
**daemon Python thread** in this API-server process
(`interactive_turns/executor.py:start_interactive_turn_runner`). It returns the
`turn_id` immediately; it never streams.

The thread claims the turn (`claim_turn_for_runner`, a runner-id compare-and-set
so at most one runner drives a turn), wakes the sandbox if needed
(`_ready_session_runtime`), then runs `_drive_interactive_turn`, which calls
`OpencodeServeClient.send_message` and both persists
(`persist_sandbox_event`) and forwards each event.

The browser never talks to this thread directly. It calls
`GET /sessions/{id}/turns/{turn_id}/events`
(`interactive_turns/api.py:get_interactive_turn_events`), which checks
the owned turn until the sandbox is ready,
then calls `SessionManager.subscribe_to_existing_session_events`
(`session/manager.py:subscribe_to_existing_session_events`), which subscribes
to the **same** `PodEventBus` by `opencode_session_id`. If the runner looks
dead (`RUNNER_STALE_AFTER_SECONDS` since its last heartbeat), the attach
endpoint restarts it (`maybe_start_runner`) rather than waiting for it
forever.

The interactive endpoint withholds the agent's `prompt_response` or `error` terminator.
It closes its live subscription, then checks the existing turn cache every 200ms for up to 30 seconds.
After finalization, it sends `turn_completed` with the turn ID, session ID, index, status, and error detail.
The runner captures outputs before it records the terminal state.
A late attachment to an owned terminal turn receives the same completion packet immediately.
An idle attachment checks the saved state each second if it missed the agent's terminal packet.
Timeouts and early stream closure leave recovery to the existing reconnect and status-read paths.

The browser uses `turn_completed` to fetch saved messages and output cards without initial completion polling.
It still checks for a successor after reading history, so another browser's new turn remains active.
The visible response remains active until history reconciliation finishes.
Scheduled runs retain their existing terminal packets and status checks.

`POST /sessions/{id}/interrupt` accepts an optional `turn_id` and sets a turn-scoped fence the runner's
`interrupt_requested()` closure polls; the runner aborts the opencode turn
and finishes with `CANCELLED`.

### 4.4 The packet vocabulary

Sandbox events and Onyx packets travel over the wire, serialized by
`event_to_sse` (`session/streaming.py:event_to_sse`) as
`event: message\ndata: {...}\n\n` with a `type` discriminator field. **Neither
is chat's `Packet`/`Placement`.** There is no `placement` field at all; routing
within a turn is carried ad hoc per packet (`sessionId`, `parentSessionId`,
`subagentSessionId` fields handled by `_routing_meta_from_event`).

**Sandbox events** (re-exported from the `agent-client-protocol` PyPI package
through the single wrapper `sandbox/event_schema.py`, historically called
"ACP events"; see §9):

| Type | Meaning |
|---|---|
| `AgentMessageChunk` (`agent_message_chunk`) | One chunk of assistant text or image content. |
| `AgentThoughtChunk` (`agent_thought_chunk`) | One chunk of the agent's reasoning. |
| `ToolCallStart` (`tool_call_start`) | A tool invocation began. Stream-only; not persisted. |
| `ToolCallProgress` (`tool_call_progress`) | Tool status/result update. Persisted on `completed`/`failed` (every update for `todowrite`). |
| `AgentPlanUpdate` (`agent_plan_update`) | The agent's todo/plan list. Upserted, one row per turn. |
| `CurrentModeUpdate` (`current_mode_update`) | Agent mode changed. |
| `PromptResponse` (`prompt_response`) | Agent stopped; carries `stopReason` (`"end_turn"`, `"cancelled"`, …). Interactive attachments replace this with committed completion; scheduled streams forward it. |
| `Error` (`error`) | opencode reported a turn-terminating failure. Carries a negative `code` sentinel: `TURN_ERROR_CODE_SESSION`, `_TIMEOUT`, `_TRANSPORT` (`event_schema.py`). |
| `ActivityTimeoutError` | Subtype of `Error` for a recoverable inactivity timeout (retry by re-prompting), distinguished by Python type, not `code`. |

**Onyx-defined packets** (`packets.py:BuildPacket`, a `Union`, not a
discriminated Pydantic union enforced at the type level the way chat's
`PacketObj` is):

Interactive attachments also serialize `InteractiveTurnCompletedPacket` from `interactive_turns/models.py` directly.
Its `turn_completed` type carries a terminal status: `SUCCEEDED`, `FAILED`, or `CANCELLED`.

| Type | Meaning |
|---|---|
| `ErrorPacket` (`error`) | Onyx-side error (session/sandbox not found), distinct from opencode's `Error`. Shares the `"error"` string with it. |
| `ApprovalRequestedPacket` (`approval_requested`) | A new approval card exists; carries only ids, frontend refetches contents. |
| `SubagentStartedPacket` (`subagent_started`) | A child opencode session was created for a `task` tool call. |
| `ConnectAppRequestPacket` (`connect_app_request`) | The agent's `connect_app` tool wants the user to connect an org app. |
| `ContextUsagePacket` (`context_usage`) | Token/cost usage snapshot. Captured into turn state, then persisted once per turn by `finalize_persist` as a `BuildMessage`. |
| `CompactionPacket` (`compaction`) | History was compacted; carries a summary. |

`SSEKeepalive` (`sandbox/sse.py:SSEKeepalive`) is a third, transport-only
marker: it never reaches the browser as JSON, only as the literal SSE comment
`": keepalive\n\n"` (`session/streaming.py:event_to_sse`).

---

### Completed transcript handoff

The streamed response remains visible until the server confirms completion and persisted history is available.
`turnSettlement` owns this handoff with reconciling, failed, and ready states.
Interactive completion and interruption use the same settlement path. Scheduled runs use their own saved run status as the completion boundary.
Approval pauses and failed scheduled runs never release queued interactive work.
Settlement reads turn status and messages independently of runtime discovery, artifacts, and navigation.
Failures retain the transcript and expose a retry for that same settlement.
The streaming hook claims ready queue work atomically, so repeated events or multiple mounted hooks cannot duplicate a send.
A queued prompt remains in the queue until the server accepts its turn.
Rejected queued starts remain available for explicit retry with the same request identity. Unrelated prompt failures do not authorize queue retries.
A clean stream close reconnects while the backend turn remains active. A successor turn replaces the old completion owner.
Stopping a pending start keeps cancellation intent until the accepted turn can be interrupted.
Earlier session instances and turns cannot publish settlement results.
Session metadata and artifacts may finish after a newer turn starts without replacing its transcript or status.

### Output inventory and panel navigation

Turn-end chat cards use the server artifact index, separate from the live output inventory below.
The browser refreshes card metadata after confirmed worker completion, alongside transcript loading, not the raw completion packet.
Card refresh failures are logged and do not block transcript loading.
Recovery settlement checks run every 250ms for the first second, then every second within the bounded retry window.
Each card belongs to the latest indexed producing turn and opens the current resource.
Three cards appear inline; the overflow action opens Outputs filtered to that turn.
Unread dots compare artifact version with the owner’s saved viewed revision.
An explicit output open acknowledges the captured card revision, even if its preview cannot render.
This records user acknowledgement, not successful content delivery. Newer revisions retain their unread state.
Opening the overview or loading a thumbnail does not mark an output viewed.
Live inventory determines file availability when a saved card still records a prior deletion.
Turn collections retain saved cards when a complete live inventory confirms that their files are missing.
These cards appear unavailable even when the saved deletion flag is stale.
Outputs filters survive welcome workspace claim. Folder unread markers follow the selected turn scope.
Reload retrieves card metadata without reconstructing attribution from sandbox files.
See [[craft-sessions]] §4.7 for capture and persistence boundaries.

The frontend keeps a temporary output inventory in each Zustand session.
`useBuildSessionStore.ts:refreshOutputInventory` reads one flat response from
`GET /build/sessions/{id}/outputs`. Each file has a path, size, and opaque revision.
The Files resource tab browses the accessible session workspace through directory requests.
Its search walks accessible directory listings without fetching file contents.
Session loading and pre-provisioning fetch the output inventory in the background.
Messages submit immediately; neither submission nor turn completion waits for inventory reads.
Complete inventories replace known files. Partial reads merge their results and preserve unscanned files.
Idle cached sessions reconcile revisions on entry and focus without changing resource tabs or selection.
Reload reconstructs live inventory. Browser metadata snapshots provide display hints until validation; see [[craft-webapp-proxy]] §4.
Reads allow 35 seconds per attempt, covering the backend's 30-second RPC deadline and HTTP overhead.
Failed reads retry twice, after one and two seconds.
An incomplete scan preserves known entries. A later complete response can remove missing files.

`useBuildSessionStore.ts:compareOutputInventory` compares paths and metadata
revisions. Completed shell and edit tools, including child-agent tools,
schedule a refresh. The private queue in `useBuildStreaming.ts` combines rapid
completions while the turn streams. Tool completions during a read coalesce into one pending refresh.
A terminal stream observation cancels pending discovery timers.
Canonical completion owns the final authoritative read, including recovery without a terminal packet.
Transcript reconciliation cancels earlier inventory reads. Passive reads defer until reconciliation ends.
Settlement starts a replacement inventory read even when it hands off to a successor turn.
That read can update file availability, but the predecessor cannot open or select tabs for the successor.
The store serializes all inventory reads per session, including focus and panel reads.
Queued reads preserve turn ordering; passive discoveries never select resources.
An already-settled turn also triggers reconciliation when the attach returns no stream.
Partial responses retain unseen entries. Failed responses preserve the last
inventory. Queued reads and responses from older turns are ignored.
Aborted queued reads do not issue a request. Completed queues are released.

Passive inventory reads never open or select tabs. During a task, newly created previewable files open tabs after a complete baseline.
The first eligible output can select a tab once per task. File and ready-webapp discovery share this selection lock.
Manual navigation, dismissal, and restored preferences lock selection until the next task.
App readiness requests coalesce per runtime and reject retired session, task, or sandbox results.
Existing local app tabs are reused. The first automatic opening also retains an Outputs overview tab.
Explicit file clicks open a file tab and use medium when the panel was closed.
Explicit opening preserves an existing medium or full layout.
Outputs, All Files, file previews, and Browser share one ordered, closeable tab collection per session.
File identity uses a normalized session-relative path. Browser identity remains separate from its selected app.
Resource tabs and their active ID are the only tab-selection model.
OutputPanelMode is the only source of panel visibility; no category adapter or stored open boolean remains.

Changed revisions invalidate file previews without selecting tabs. Deleted files retain explanatory tabs.
Viewer retention, cache invalidation, document controls, and browser snapshots belong to [[craft-webapp-proxy]] §4.
CSV previews use the shared parser and limit display to 1,000 rows, 100 columns, and 5,000 cells.
Malformed quoted fields show an error with a raw-download action.

Tabs and layout remain independent of stream rendering. Inventory responses require the same session instance.
Passive reads also require the captured turn; active reads can update metadata after a queued turn starts.
Tab creation and selection always check the requesting turn. Recreated sessions reject responses from retired instances.

The first accepted interactive turn starts automatic naming through the session store.
This happens after message persistence and before view ownership checks.
Naming survives navigation and unmount; failed submissions do not start naming.
It does not delay stream attachment. See [[craft-sessions]] for name persistence and fallback rules.

## 5. Contracts and invariants

1. **Craft does not reuse chat's `Packet`/`Placement`.** It has its own packet
   vocabulary (§4.4), no `placement` field, and no chat `turn_index`/`tab_index`
   coordinate system. Completion packets carry Craft's own turn index. A reader who assumes chat's contract will look for
   fields that do not exist here.
2. **`event_schema.py` is the sole import point for `acp.schema`.** Nothing
   else in the tree should `from acp.schema import ...` directly (verified:
   `grep -ri acp backend/onyx/server/features/build/` turns up only this
   wrapper, `serve_client.py`'s docstring, and `session/{streaming,manager}.py`
   /`session/api.py` importing the wrapper's names). Swapping or inlining the
   upstream types is a one-file change as long as this holds.
3. **An unknown packet must not crash the frontend.** `parsePacket`
   (`web/src/app/craft/utils/parsePacket.ts:parsePacket`) returns
   `{ type: "unknown" }` for anything it does not recognize, mirroring
   `findRenderer`'s `null` in [[streaming-protocol]]. Adding a packet type here
   needs a `parsePacket.ts` case or it renders as nothing.
4. **Agent execution ends on `session.idle` / `session.status:{type:idle}`. An error
   can end it earlier.** Interactive browser completion waits for the runner's saved terminal state (§4.3).
   `message.updated` with `info.error` and `session.error` both
   emit an `Error` terminator. `message.updated` fires once per inner opencode step, not once per
   turn; treating it as a terminator drops every step after the first (see
   `docs/craft/issues/opencode-serve-event-stream-pitfalls.md` §1). This is
   fixed in `translate_opencode_event`, not a live risk, but any new
   consumer of the opencode event stream must respect it.
5. **Tagged-union payloads (`session.status`) are inspected by `.type`, not by
   string equality on the outer field**, per the same pitfalls doc §2.
6. **Content deltas can arrive before their message's role is known.**
   `_is_assistant_message` (`serve_client.py`) hydrates unknown message ids via
   a synchronous `GET /session/{id}/message/{id}` rather than buffering and
   hoping metadata arrives later (pitfalls doc §3). A new content-classifying
   code path must go through this cache-or-hydrate chokepoint, not invent its
   own buffering.
7. **The runner is the only writer of persisted turn state; the browser
   attach never drives the turn.** `get_interactive_turn_events` only
   restarts a stalled runner (`maybe_start_runner`); it does not itself call
   `send_message`. Do not add a code path where an attach can duplicate a
   prompt POST.
8. **At most one runner drives a turn.** `claim_turn_for_runner`
   (`interactive_turns/state.py`) is a runner-id compare-and-set; a second
   runner only takes over once the first is stale
   (`RUNNER_STALE_AFTER_SECONDS`, six keepalive intervals). Do not add a second
   path that starts a runner without going through this claim.
9. **There is no packet-level reconnect buffer.** Unlike
   [[streaming-protocol]]'s `stream_buffer.py`, nothing compresses and stores
   every SSE line Craft emits. A client that attaches after missing events
   gets an empty per-subscriber queue (bounded, `maxsize=500`, per
   `_Subscription`). It receives only events the turn emits after the attach. What it lost is recoverable only
   through the **persisted** `BuildMessage` rows via
   `GET /sessions/{id}/messages`, which is a different, coarser shape (no
   `ToolCallStart`, no `CurrentModeUpdate`, no live deltas), not a replay of
   the wire format. Owned terminal turns replay only `turn_completed`, not earlier content. See §9.
10. **There is no terminal channel.** There is no `/build/sessions/{id}/terminal` websocket, no PTY
    bridge, and no `xterm.js` integration anywhere under `web/src/app/craft/`
    (verified by grep; the only websocket route in `webapp_proxy.py` is the
    Next.js dev-server HMR proxy, `websocket_webapp_hmr`, which is unrelated
    and belongs to [[craft-webapp-proxy]]).

---

## 6. Relationships

**Depends on**
- [[craft-sandboxes]]: `PodEventBus` and `OpencodeServeClient` talk to the
  `opencode serve` process the sandbox pod runs; session-preservation across
  sandbox sleep/restore is a sandbox-layer concern this component only
  consumes (opencode session id resolution in `_ensure_opencode_session_id`,
  `session/streaming.py`).
- [[craft-sessions]]: owns `BuildSession`/`BuildMessage`; this component is
  the writer of the streaming-derived rows on them.
- [[craft-external-apps]]: `ConnectAppRequestPacket` and
  `ApprovalRequestedPacket` originate from tool-permission handling this
  component's client surfaces but does not own.

**Depended on by**
- [[chat-frontend]] has no relationship to this component; Craft's frontend
  is entirely separate (`web/src/app/craft/`), which is itself the main
  consumer.
- [[craft-admin]]: no direct dependency, but disabling Craft for a user/org
  removes access to every endpoint in §2.
- [[craft-webapp-proxy]]: shares the session's live preview surface but not
  the event stream; cross-linked because both are per-session live channels
  reached through the same `/build` router.

**Contrast with [[streaming-protocol]]**
Chat's stream is one HTTP request that both drives and delivers the turn, with
a durable compressed buffer enabling a real resume. Craft's stream is a
detached background runner plus an attach-only SSE endpoint with no packet
buffer; reconnection means "see what's still live," not "replay everything I
missed."

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new `BuildPacket` type | `packets.py:BuildPacket` union; `event_to_sse`'s isinstance list (`session/streaming.py`); `parsePacket.ts` gets a case or it silently drops; decide persistence in `persist_sandbox_event` |
| adds a new sandbox event type (upstream opencode) | `event_schema.py`'s re-export list; `translate_opencode_event`'s dispatch; `SandboxEvent` union in both `serve_client.py` and `serve_transport.py`; `parsePacket.ts` |
| changes the transport (bus reconnect policy, keepalive cadence, SSE framing) | `PodEventBus._reader_loop` backoff/give-up constants; every consumer of `event_to_sse`'s framing (`interactive_turns/api.py`, `session/api.py` scheduled-run path); `processSSEStream` on web |
| changes the opencode-serve client (`OpencodeServeClient`) | both call sites, `send_message` (turn-owning) and `subscribe_to_opencode_session` (late-attach); the translator's `_TurnState` correlation logic; unit tests under `backend/tests/unit/onyx/server/features/craft/sandbox/test_translate_opencode_event.py` |
| changes the interactive-turn lifecycle (claim, heartbeat, stale timeout) | `RUNNER_STALE_AFTER_SECONDS`/`INTERACTIVE_TURN_HARD_CAP_SECONDS` relationship in `timeouts.py`; the attach endpoint's `maybe_start_runner` retry throttle; scheduled-run's separate Celery-driven path in `session/manager.py`, which reuses the bus but not the runner claim |
| adds a terminal/PTY-style channel | there is none today (§5.10); if built, follow the auth pattern in [[craft-webapp-proxy]]'s `current_user_from_websocket_cookie`, not a new scheme |
| changes subagent (`task` tool) surfacing | `is_task_tool` synthetic-message branch in `persist_sandbox_event`; `subagentRouting.ts`'s `classifySubagentEvent`; `SubagentView.tsx`, `AgentSwitcher.tsx` and `useBuildSessionStore.ts:viewSubagent` on the web side |

---

## 8. How to verify a change

### Tests

```bash
# Unit tests for the opencode-event translator (the highest-value tests here)
cd backend && uv run pytest tests/unit/onyx/server/features/craft/sandbox/test_translate_opencode_event.py

# Craft integration tests exercising a live turn end to end
cd backend && uv run pytest tests/integration -k craft
```

Frontend regression tests for output discovery and panel selection:

```bash
cd web && bun run test --runInBand useBuildStreaming.test.tsx useBuildSessionStore.test.tsx
```

`backend/tests/external_dependency_unit/craft/test_streaming_persistence.py`
exercises `persist_sandbox_event` against real sandbox-event payloads.

### Manual reproduction

`docs/craft/dev/local-compose-craft.md` is the setup guide for the Docker
sandbox backend specifically (proxy iteration); for general Craft streaming
work against the default Kubernetes backend, follow
`docs/craft/dev/local-kubernetes.md` instead (referenced by the compose doc).

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open the browser devtools Network tab, send a Craft message, and inspect
   the `GET /sessions/{id}/turns/{turn_id}/events` response: newline-delimited
   `event: message\ndata: {...}` blocks, each with a recognizable `type`.
3. Reload the tab mid-turn. Confirm the client calls
   `GET /sessions/{id}/turns/active` then re-attaches to `.../events`, and the
   transcript keeps growing rather than restarting.
4. Trigger a `task` (sub-agent) tool call. Confirm only its prompt and final
   text appear in the parent transcript. Open the sub-agent view and confirm
   it shows the sub-agent's thinking and tool calls (see §9).

---

## 9. Footguns

- **`docs/craft/features/streaming/` is mostly history, not a design to
  verify against.** `drop-acp-layer.md` states the ACP transport (`opencode
  acp`, `ACPExecClient`/`DockerACPExecClient`, `AGENT_TRANSPORT` env var) is
  fully deleted, and this is confirmed in code: only `event_schema.py`'s
  wrapper, `serve_client.py`'s docstring, and a few docstrings/imports in
  `session/{streaming,manager,api}.py` still say "acp" (as the name of the
  PyPI wrapper module, `sandbox.event_schema`, or historical comments); there
  is no live ACP exec-client code path left. `shared-acp-exec-client.md` and
  `docker-opencode-serve.md` describe now-deleted machinery entirely.
  `opencode-serve-client.md` and `preserve-opencode-sessions.md` are closer to
  current (the latter is actively cited by `session/streaming.py`'s own
  `_ensure_opencode_session_id`), but treat every doc under this directory as
  something to verify against `serve_client.py`/`serve_transport.py` before
  trusting, not as ground truth.
- **The event stream is a hint, not the source of truth.** All three bugs in
  `docs/craft/issues/opencode-serve-event-stream-pitfalls.md` (premature
  per-step termination, string-vs-tagged-union comparison, racing content
  deltas) share one lesson: when the stream is ambiguous, fall back to a REST
  call against opencode's persisted state (`get_message`), don't invent
  compensating stream-side logic.
- **Deploy-time gotchas are RBAC and env-refresh, not streaming logic**
  (`docs/craft/issues/opencode-serve-deploy-gotchas.md`): a missing `secrets`
  RBAC verb on the sandbox namespace, Kubernetes not refreshing
  `OPENCODE_CONFIG_CONTENT` on a live pod after a Secret update (needs a pod
  delete), and mutable image tags serving stale content under
  `IfNotPresent`. None of these are bugs in the translator; they surface as
  streaming symptoms (`ProviderModelNotFoundError`, connection refused on
  `/session`) that look like transport bugs but aren't.
- **No terminal/PTY channel exists.** An old design note that mentions one
  describes an unbuilt branch; see §5.10.
- **The sub-agent view follows the main turn stream, with no stream of its own.**
  `web/src/app/craft/components/SubagentView.tsx` renders from `ChatPanel.tsx`
  when `viewedSubagentSessionId` is set. `AgentSwitcher.tsx` sets it through
  `useBuildSessionStore.ts:viewSubagent`. There is no dedicated sub-agent
  event-stream endpoint. Child events arrive on the main turn stream.
  `utils/subagentRouting.ts:classifySubagentEvent` splits them from the main
  transcript. `useBuildStreaming.ts` (live path) and `useBuildSessionStore.ts`
  (history reload) both use it, so the two paths agree. The view reuses
  `BuildMessageList` and follows the run while the sub-agent status is `running`.
  The main transcript still gets a synthetic final-answer message for a
  completed `task` tool call (`persist_sandbox_event`'s `is_task_tool` branch).
- **A stuck runner is only reclaimed after `RUNNER_STALE_AFTER_SECONDS` (six
  keepalive intervals, ~90s).** A rapid page reload during that window can
  make the attach endpoint wait rather than force a restart; this is
  deliberate (avoids double-driving a healthy turn) but reads as latency if
  you don't know the constant.

### Output and transcript recovery

Webapp readiness and automatic selection belong to the session store, not the mounted chat panel.
See §4 for selection locks and preview-cache ownership.

Live text parts retain their OpenCode part ID across stream attachments. Delta packets append to that part. Authoritative snapshots replace its text in place. Text and thinking parts keep their position relative to tool events. Durable worker events retain delta text and the part ID. Persistence splits text at part or routing boundaries. Restoration combines segments of the same part before live snapshots replace them. Older saved rows without IDs retain their existing display behavior.

Transport failures retain the visible transcript and reconnect while the backend owner remains active. Permanent access and missing-session failures stop observation and use session-load recovery, which blocks submission until a reload succeeds. Terminal packets, including interactive errors, reconcile saved history before clearing the turn. The last assistant block retains its cursor during reconciliation without creating another message. A failed completion read removes the cursor and shows the existing retry action. Successful completion starts an authoritative output inventory read before it permits queued work.

Restored child text parts own the child transcript. Parent task completion settles those parts without inserting their combined text again.
The parent task result supplies a fallback only when no child response was saved.

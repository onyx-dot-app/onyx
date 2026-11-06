# Craft Streaming

> How a Craft turn's output gets from the agent in the sandbox to the browser:
> the `opencode serve` client, the per-pod event bus, the translation to Craft
> events, which events are saved, and the attach-only SSE endpoint, which has
> no replay buffer.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## Callers

The interface has two sides. On the server, the sandbox manager's
`send_message` yields translated Craft events from
`server/features/build/sandbox/opencode/serve_client.py:OpencodeServeClient`,
and `server/features/build/session/streaming.py:persist_sandbox_event` saves
the subset that history needs (Architecture, What gets saved). To a client,
`GET /build/sessions/{id}/turns/{turn_id}/events`
(`server/features/build/interactive_turns/api.py:get_interactive_turn_events`)
sends the same events as SSE, framed by `event_to_sse`.

- The turn runner in [[craft-sessions]] drives the turn and passes each event
  to `persist_sandbox_event`.
  It keeps [[#turn-ends-on-idle]] and [[#two-error-types]].
- The browser ([[craft-frontend]]) attaches and renders. It keeps
  [[#completion-is-turn-completed]], [[#no-replay-buffer]] and
  [[#subagent-events-on-parent-stream]].
- Developers who call the public API send
  `POST /build/sessions/{id}/send-message`, which returns a `turn_id`, then
  attach. They keep [[#completion-is-turn-completed]] and [[#no-replay-buffer]].
- The scheduled-run executor and viewer ([[craft-scheduled-tasks]]) use
  `persist_sandbox_event` and `event_to_sse`.
- Developers who add an event or packet type keep
  [[#new-packet-type-edits]].

---

## Scope

This component owns the transport and the vocabulary of a turn: the opencode
HTTP client and its retry rules, the event bus, the bus cache, the translation
from opencode events to Craft events, the Onyx packet types, SSE framing,
announce merging, what each event saves, the attach endpoint, and the web
packet parser and sub-agent routing.

Neighbours own the rest:
- [[craft-sessions]]: the turn runner, locks, the turn record and interrupt.
- [[craft-frontend]]: the browser stores and settlement.
- [[craft-sandboxes]]: the pod and its `opencode serve` process and credentials.
- [[craft-external-apps]]: approval and connect-app policy, the proxy-side
  wait, and the connect-app decision.
- [[streaming-protocol]]: chat's packet protocol, which Craft does not use.

---

## Architecture

```
opencode serve (in pod)          GET /event?directory=...   raw SSE
  PodEventBus._reader_loop       one reader per (sandbox_id, directory) per API process
  PodEventBus._dispatch          fan out by opencode session id, and to every ancestor
    subscriber queue (max 500)
      runner: OpencodeServeClient.send_message -> translate_opencode_event
              -> executor persists the saved subset ([[craft-sessions]])
      attach: subscribe_to_opencode_session -> translate_opencode_event
              -> merge_events_with_announces -> event_to_sse
              -> get_interactive_turn_events -> browser
                 processSSEStream -> parsePacket -> store ([[craft-frontend]])
```

**Two independent consumers.** The runner and each browser attach subscribe
to the same bus. The runner posts the prompt, saves rows and decides when the
turn ends, with or without a browser. The attach only renders. In
[[core-chat-loop]], by contrast, the HTTP request drives the turn.

**One bus per directory, per API process.** opencode scopes `/event` by the
`directory` query parameter, so the bus key is `(sandbox_id, directory)`
(`server/features/build/sandbox/opencode/event_bus.py:PodEventBus`). The bus
reconnects with backoff and closes itself after a run of failed reconnects.
`server/features/build/sandbox/serve_transport.py:_ServeMixin._get_or_create_event_bus`
replaces a closed bus on the next use. Child (sub-agent) sessions are learned
from `session.created`, and their events also go to the parent's subscribers.

**The translator.**
`server/features/build/sandbox/opencode/serve_client.py:translate_opencode_event`
turns one raw opencode event into zero or more Craft events. Its module
docstring lists the event-stream rules, each tied to a bug
it caused. Read it before you change the translator.

**The attach endpoint.**
`server/features/build/interactive_turns/api.py:get_interactive_turn_events`
sends keepalives until the session has an opencode session id and an active
sandbox. It then subscribes and forwards events. The subscription sends a
keepalive every second, so the loop sees a turn that ended before the
subscription opened. It holds back the agent's
terminal packets, closes the subscription, and polls the turn record until the
runner calls `finish_turn`. Then it sends `turn_completed`
(`server/features/build/interactive_turns/models.py:InteractiveTurnCompletedPacket`).
If the record does not settle within `TURN_COMPLETION_WAIT_SECONDS`, or the
subscription ends without a terminal packet, the stream closes without
`turn_completed`. It also tries to restart a stalled runner, at most every few
seconds. The scheduled-run stream
(`server/features/build/session/api.py:get_session_scheduled_run_events`) uses
the same framing but forwards the terminal packets.

**Announces.** The egress proxy and the connect-app flow run outside the turn
stream. `server/features/build/session/streaming.py:merge_events_with_announces`
runs three threads: the event iterator, an approval announce poller, and a
connect-app poller. The connect-app poller first restores the session's
pending requests, then pops new announces, and skips request ids it has sent.
The proxy announces an approval with an RPUSH to a per-session cache key
(`sandbox_proxy/approval_cache.py:announce_approval`). If the stream misses
it, the frontend still finds the approval through
`GET /build/approvals/sessions/{id}/status`.

**What gets saved.** `server/features/build/session/streaming.py:persist_sandbox_event`
buffers message and thought text and saves one row per block, split at part
and routing boundaries. It saves tool progress only on `completed` or
`failed` (every update for `todowrite`), and keeps one plan row per turn. A
completed `task` call also saves a synthetic `agent_message` with the
sub-agent's final answer. `finalize_persist` saves context usage once per
turn. Tool starts, mode updates and terminal packets are not saved.

---

## Contracts and traps

1. `no-chat-packet-placement` **Craft does not use chat's `Packet` and
   `Placement`.** There is no `placement` field. Routing inside a turn uses
   `sessionId`, `parentSessionId`, `partId` and `subagentSessionId` in the
   event metadata (`server/features/build/session/streaming.py:_routing_meta_from_event`).
   The `turn_index` here is Craft's own user-message count; chat's is in
   [[streaming-protocol]].
2. `turn-ends-on-idle` **A turn ends only on `session.idle` or
   `session.status` with type `idle`.** opencode sets `time.completed` on
   `message.updated` for every inner step. Treating that as the end drops every
   step after the first. `session.status.status` is a tagged union: compare its
   `type`, not the object, and build test fixtures from captured payloads
   (`server/features/build/sandbox/opencode/serve_client.py:translate_opencode_event`). An
   error in `message.updated` or `session.error` ends the turn early. Any new
   consumer of the raw stream must keep this rule.
3. `text-before-role` **Text can arrive before its role is known.**
   `server/features/build/sandbox/opencode/serve_client.py:_is_assistant_message`
   fetches an unknown message once over REST and caches it. Do not buffer
   deltas until metadata arrives: a stream drop would lose them. When the
   stream is unclear, read opencode's REST state. Do not add compensating
   stream logic.
4. `no-replay-buffer` **There is no replay buffer.** Unlike chat's stream
   buffer, nothing stores the SSE lines. A late subscriber gets only new
   events. A full subscriber queue drops events and logs a warning. opencode's
   `/event` has no `Last-Event-ID`, so the cumulative `part.text` on the next
   `message.part.updated` fills a text gap
   (`server/features/build/sandbox/opencode/serve_client.py:_reconcile_part_text`). Other gaps
   are filled by `GET /build/sessions/{id}/messages`, which has a coarser shape
   than the live stream.
5. `attach-never-drives` **The attach never drives the turn.**
   `server/features/build/interactive_turns/api.py:get_interactive_turn_events`
   may only call
   `start_interactive_turn_runner`, which claims through the `runner_id`
   compare ([[craft-sessions#runner-id-ownership]]). Do not add an attach path
   that posts a prompt.
6. `completion-is-turn-completed` **Completion is `turn_completed`, not the
   agent's terminal packet.** The interactive endpoint
   (`server/features/build/interactive_turns/api.py:get_interactive_turn_events`)
   sends it only after the runner has saved the transcript and output cards. A
   failed or stopped turn also ends with `turn_completed`, with its `status`
   and `error_detail`; the agent's own `error` packet never reaches the client
   on this path. The client gets an `error` event only when the endpoint
   itself fails. An attach after the turn ended gets only `turn_completed`.
   The browser uses it to
   start settlement. If you forward `prompt_response` to the browser on this
   path, the browser reads history before it is complete.
7. `new-packet-type-edits` **A new packet type needs edits on both sides.** Add
   it to `server/features/build/packets.py:BuildPacket`, to the `isinstance`
   list in `server/features/build/session/streaming.py:event_to_sse`, to the
   `ParsedPacket` union in `web/src/app/craft/utils/packetTypes.ts`, and to
   `web/src/app/craft/utils/parsePacket.ts:parsePacket` (an unknown type parses
   to `unknown` and renders nothing). Then decide whether
   `persist_sandbox_event` saves it.
8. `two-error-types` **Two different events use the type string `error`.**
   opencode's `Error` (from `server/features/build/sandbox/event_schema.py`)
   ends a turn and carries a negative code sentinel.
   `server/features/build/packets.py:ErrorPacket` is an Onyx-side failure.
   `server/features/build/sandbox/event_schema.py:ActivityTimeoutError` is a
   subtype of `Error` that the runner recovers
   from by prompting again; Python type tells it apart, not the code.
9. `event-schema-sole-acp-importer` **`server/features/build/sandbox/event_schema.py`
   is the only importer of `acp.schema`** in application code. Import event types from the
   wrapper, so an upstream package change stays a one-file change.
10. `only-connect-app-asks-reach-user` **Only `connect_app` permission asks
    reach the user.**
    `server/features/build/sandbox/opencode/serve_client.py:OpencodeServeClient._handle_permission_ask`
    allows every
    other `permission.asked` with a warning, because the session's opencode
    config (`server/features/build/sandbox/util/opencode_config.py`) is
    expected to cover every category. A new tool that needs user consent must
    not rely on an opencode permission ask.
11. `subagent-events-on-parent-stream` **Sub-agent events arrive on the parent
    stream.** There is no sub-agent stream.
    `web/src/app/craft/utils/subagentRouting.ts:classifySubagentEvent` splits
    child events from the main transcript, and both the live path and the
    history reload use it. Keep them on the same function.
12. `no-retry-post-session` **Do not retry `POST /session` on
    `RemoteProtocolError`.**
    `server/features/build/sandbox/opencode/serve_client.py:OpencodeServeClient._http_with_cold_pod_retry`
    retries a connect error always and a dropped connection only for idempotent
    calls. The server can have created the session before the drop.
13. `only-404-replaces-opencode-session` **Only a 404 may replace a saved
    opencode session id.**
    `server/features/build/sandbox/opencode/serve_client.py:OpencodeServeClient.ensure_session`
    reuses the
    saved id on 200 and creates a new opencode session only on 404, which the
    caller then saves. Any other lookup error raises and fails the turn. A
    change that treats other errors as "missing" lets an outage silently drop
    the agent's context.

---

## Decisions

- **Attach-only stream with a detached runner.** A turn outlives any one
  browser connection. The cost: a reconnect shows only live events, and
  settlement reads saved history ([[craft-frontend]]).

---

## Known issues

- **A stalled runner is reclaimed only after `RUNNER_STALE_AFTER_SECONDS`.** A
  reload in that window waits. This avoids driving a healthy turn twice.
- **No terminal channel.** There is no PTY or terminal websocket. The only
  websocket under `/build` is the preview HMR proxy ([[craft-webapp-proxy]]).
- **Sub-agent follow-ups stream from the request.** See [[craft-sessions]]
  Known issues.

---

## Dependencies

- [[craft-sessions]]: the turn record that the attach endpoint polls, and the
  runner that it may restart.
- [[craft-sandboxes]]: the `opencode serve` process, its credentials, and
  `SandboxManager`.
- [[craft-external-apps]]: the proxy and connect-app flow that produce
  announces, and the approval status route.

---

## Recipes

- `new-opencode-event-type` **A new opencode event type.** Copy the handling of an existing type in
  `translate_opencode_event`, such as `session.compacted`. List the handled
  types with `git grep -n 'etype ==' backend/onyx/server/features/build/sandbox/opencode/serve_client.py`.
  Add the type to `server/features/build/sandbox/event_schema.py` and the
  `SandboxEvent` unions in `server/features/build/sandbox/base.py` and
  `server/features/build/sandbox/opencode/serve_client.py`. Add a branch to
  `server/features/build/session/streaming.py:_get_event_type`, or
  `event_to_sse` sends the event with the type `unknown`.
- `new-packet-type` **A new packet type.** Copy `CompactionPacket` through `BuildPacket`,
  `event_to_sse` and `parsePacket` ([[#new-packet-type-edits]]). List the
  current packets with `git grep -n 'class .*Packet' backend/onyx/server/features/build/packets.py`.
- `investigate-stream` **Investigate a stream that shows nothing or stops.** First rule out
  faults that look like streaming bugs:
  - connection refused on `POST /session`: opencode has not bound its port, or
    it crashed;
  - 401 from opencode: the Basic-auth user is `OPENCODE_SERVER_USERNAME`. The
    client reloads the password once on a 401, in case a peer rotated it
    (`OpencodeServeClient._request`);
  - `/event` never becomes ready: the bus closed itself after repeated
    failures. Search `backend/log/api_server_debug.log` for
    "PodEventBus giving up".

  Then compare the live stream with opencode's REST state for the session
  ([[#text-before-role]]). A stopped runner is a turn fault, not a stream
  fault.

---

## Verification

- Translator and bus: `backend/tests/unit/onyx/server/features/craft/sandbox/`.
- Attach endpoint: `backend/tests/unit/onyx/server/features/craft/interactive_turns/`.
- Persistence with real payloads: `backend/tests/external_dependency_unit/craft/`.
- Web parsing and routing: the tests next to `web/src/app/craft/utils/` and
  `web/src/app/craft/hooks/`.
- By hand: reload mid-turn. The page must call `turns/active`, attach to the
  same turn, and keep growing the transcript. Start a sub-agent and check that
  only its prompt and answer show in the main transcript.

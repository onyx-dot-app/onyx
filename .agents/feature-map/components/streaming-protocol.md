# Streaming Protocol

> The wire contract between the chat backend and every client: the packet
> vocabulary, the `Placement` coordinates, the path from a worker thread to the
> HTTP body, and the buffer that lets a client resume a stream it lost.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## User experience

- **An end user** sees reasoning appear token by token, a tool block open before
  its results arrive, parallel tool calls in separate tabs, code that types
  itself while the model writes the tool arguments, and, in a multi-model turn,
  one column per model.
- **Reload or reconnect.** When the page reloads during an answer, the client
  replays everything the run has buffered and then follows the live run. When
  the buffer is gone or broken, the client shows the saved message instead.
  Closing the connection does not stop the run. Stop, the execution deadline
  (`CHAT_EXECUTION_TIMEOUT_S`) and lost session admission stop it.
- **Quiet phases.** During a long tool call the connection stays open, because
  the server sends heartbeats. The user does not see them.
- **When this layer breaks** on the server, live output loses packets and the
  user sees a `STREAM_GAP` error that asks for a reload. A packet type that a
  client does not know renders nothing, and no error appears.
- **An API caller** reads one JSON object per line. The response says
  `text/event-stream`, but the body is NDJSON, not SSE. Most lines are packets
  with `placement` and `obj`. Some lines are not: the session and message IDs
  at the start, and `StreamingError` objects ([[#not-every-line-is-a-packet]]).
  After a reload, the caller gets the stream ID from `current_stream` in the
  session detail response. To resume, the caller calls
  `GET /chat/chat-session/{id}/resume-stream?stream_id=<id>&cursor=0`. A 404
  means that no run with that stream ID can be resumed. While the turn is in
  preparation, the session reports `is_processing: true` but `current_stream`
  is null, and resume returns 404. Before the next send,
  the caller waits until `GET /chat/chat-session/{id}/status` reports
  `is_processing: false` ([[#stream-end-is-not-idle]]). The public guide is
  `documentation/developers/guides/chat_new_guide.mdx`.
- **A CLI user** gets the same stream through the Onyx CLI, which parses each
  line in `cli/internal/parser/parser.go:ParseStreamLine`. A type the CLI does
  not know becomes an `UnknownEvent` and shows nothing. A line that is not JSON
  shows as an error.

---

## Scope

This component owns the packet vocabulary, `Placement`, the line framing, the
path from the emitter to the HTTP body, the resume buffer and the resume
endpoint's read rules, the client mirrors of the vocabulary, the rule that a
stream's end does not mean the session is idle, and the rule that API
middleware keeps request context through a streamed body. It shares the
emitter and the delivery with [[core-chat-loop]], which owns when they run and
the session admission behind the status endpoint.

It does not own:
- the producers: [[core-chat-loop]] and each tool ([[tools-framework]]);
- the renderers: [[chat-frontend]] and [[mobile-app]];
- the saved-session replay, which rebuilds packets from saved rows:
  [[chat-persistence]];
- what `CitationInfo` means and its ordering rule: [[citations]].

---

## Architecture

```
send-chat-message -> chat/process_message.py:_stream_chat_turn   prepare, start_chat_turn, read the reader
  -> one chat-response thread per model: agent runtime events
  -> ChatDelivery.events (EventDispatcher worker)   one thread for every model
  -> chat/presentation.py:ResponsePresenter.consume -> chat/renderer.py MessageRenderer, ToolRenderer
  -> chat/emitter.py:Emitter.emit                   stamps model_index
  -> chat/execution.py:ChatTurnExecution._publish   drops packets once the turn is cancelled
  -> chat/stream_buffer.py:ChatDelivery.publish     one lock orders live and replay output
       -> ChatStream (reader) -> HTTP body          heartbeat after CHAT_HEARTBEAT_INTERVAL_S idle;
                                                    closing it detaches only the reader
       -> pending replay lines -> flush on the same EventDispatcher worker (50 ms or 32 KiB)
            -> StreamBufferWriter                   zlib chunks in the cache

resume-stream: get_processing_stream_id (must match stream_id) -> read_stream_chunks(cursor, 32 per read)
  -> blocks + StreamCursor line per batch -> poll until done or the owner lapses, with heartbeats
```

`chat/execution.py:start_chat_turn` publishes the ID lines and starts the turn
on its own threads, then returns the reader. `_stream_chat_turn` closes the
reader when the client disconnects; the run, its save and its buffer continue.
It turns a failure in setup or start into one `StreamingError` line.

**Line kinds.** `chat/models.py:AnswerStreamPart` lists what the backend
writes: `Packet`, `MessageResponseIDInfo`, `MultiModelMessageResponseIDInfo`,
`CreateChatSessionID` and `StreamingError`. Only `Packet` has a placement. A
per-model error puts `model_index` in `StreamingError.details`. The resume
endpoint adds a sixth kind,
`backend/onyx/server/query_and_chat/streaming_models.py:StreamCursor`, after each batch. It
is never buffered. When the send route itself fails
(`server/query_and_chat/chat_backend.py:handle_send_chat_message`), it writes a
bare `{"error": ...}` object with no newline, which is not a `StreamingError`.
A request that fails before `start_chat_turn` gets one `StreamingError` and no
ID lines.

**`Placement`.** `turn_index` is the rendering block. `tab_index` separates
parallel tool calls in one block. `sub_turn_index` is set for packets from a
tool that runs its own loop, such as the research agent. `model_index` is the
model column. It is `None` on packets that no `Emitter` tagged, such as
heartbeats. `chat/renderer.py:ResponseLayout.next_section` hands out turn and
sub-turn indexes.

**Packet families.**
`backend/onyx/server/query_and_chat/streaming_models.py:StreamingType` holds every type string, and `PacketObj` is the union that `Packet.obj` is
validated against. Families are control (`stop`, `section_end`, `error`,
`chat_heartbeat`), reasoning, answer (`message_start`, `message_delta`),
citations, one family per tool, deep research, and the coding agent with the
bash tool. `ToolCallArgumentDelta` streams the Python tool's code while the
model writes it; the configured reasoning tool streams as reasoning packets
instead (`chat/renderer.py:MessageRenderer.consume`). Other tools show their
arguments when they start. `chat/renderer.py:ToolRenderer.start` emits
`ToolCallDebug` before the start packet, only with `INTEGRATION_TESTS_MODE`.

**Buffer.** The key is the session ID plus the stream ID (the reserved assistant
message ID, or the user message ID in a multi-model turn). Keys live in the
cache backend (`cache/factory.py:get_cache_backend`): Redis, or Postgres when
`CACHE_BACKEND=postgres`. Chunks expire after `CHAT_STREAM_BUFFER_TTL_S`, and
after `CHAT_STREAM_BUFFER_DONE_TTL_S` once the run is done. A run over
`CHAT_STREAM_BUFFER_MAX_BYTES`, a replay backlog over 4 MiB, a cache error, or
a live delivery gap marks the buffer `truncated`. The run continues without
resume. Cache writes run outside the publication lock, so the ID lines, errors
and the user-cancel stop, which other threads publish, do not wait for the
cache. Answer, reasoning and tool packets come from the EventDispatcher worker
that also flushes the buffer, so a slow cache delays them. When live delivery
loses output (a presenter failure, failed run cleanup, or a dispatcher that
cannot close), `ChatDelivery.report_gap` sends a `StreamingError` with
`STREAM_GAP` that asks the user to reload. That error goes only to the live
reader, not to the buffer.

**Middleware.** The API server's middleware runs as pure ASGI callables, so a
context variable that a middleware sets stays set until the streamed body and
its background task end ([[#pure-asgi-middleware]]).

---

## Contracts and traps

1. `vocabulary-mirrored-by-hand` **The vocabulary is mirrored by hand, and no
   build step checks it.** The backend `StreamingType` and `PacketObj` are the
   source. These copy it: the web and mobile enums
   (`web/src/app/app/services/streamingModels.ts`,
   `mobile/src/chat/streamingModels.ts`), the
   renderer dispatch
   (`web/src/app/app/message/messageComponents/renderMessageComponent.tsx:findRenderer`,
   `mobile/src/components/chat/renderers/findRenderer.ts`), the widget
   (`widget/src/services/stream-parser.ts`), the Onyx CLI
   (`cli/internal/parser/parser.go`, `cli/internal/models/events.go`), the
   load-test parser (`tools/loadtest/onyx_client/stream_parser.py`) and the
   public developer docs (`documentation/developers/`). To find the current
   set, run `git grep -l reasoning_delta`. A
   missing entry is a silent break.
2. `old-bytes-across-deploy` **A rename or framing change meets old bytes.**
   `server/query_and_chat/chat_backend.py:resume_chat_stream` yields the
   buffered blocks without re-encoding, so a
   client that resumes across a deploy reads lines that the previous version
   wrote while that version's run still owns the session: until the run ends,
   or about 60 s after its pod dies, when the session admission lease lapses. Mobile builds and CLI binaries
   in the field keep the old vocabulary much longer. Accept the old name or
   framing, or add the new one beside it.
3. `unknown-packet-renders-nothing` **An unknown packet renders nothing.**
   `web/src/app/app/message/messageComponents/renderMessageComponent.tsx:findRenderer`
   returns `null` when no predicate matches. Keep that path for
   new families: an unguarded cast can throw instead.
4. `emitter-sets-model-index` **Only `chat/emitter.py:Emitter.emit` sets
   `model_index`.** It
   overwrites what the producer set. Lines that `chat/execution.py:ChatTurnExecution`
   or `ChatDelivery` publish directly, such as the user-cancel `OverallStop`
   and the `STREAM_GAP` error, and heartbeats have no `model_index`.
5. `not-every-line-is-a-packet` **Not every line is a packet, and heartbeats are
   the consumer's job.** Clients must check for `obj` before they read it, as
   `web/src/hooks/useChatSessionController.ts` does on resume. On web, the name
   `PacketType` means two things: the enum of type strings in
   `web/src/app/app/services/streamingModels.ts`, and the union of line shapes in
   `web/src/app/app/services/lib.tsx`. `web/src/app/app/services/lib.tsx:sendMessage`
   drops heartbeats with `withoutHeartbeats`.
   `web/src/app/app/services/lib.tsx:resumeStream` keeps them, because its
   caller uses them as liveness ticks, and also yields `StreamCursor` lines. A
   new consumer of `web/src/lib/search/streamingUtils.ts:handleSSEStream` sees
   both. Mobile resumes without `stream_id` and skips `StreamCursor` lines
   because they have no `obj`.
6. `turn-index-is-not-a-turn` **`turn_index` is not a backend turn.** It is a
   rendering block. `chat/renderer.py:ResponseLayout.next_section` gives each
   answer, reasoning or tool section its own index, so reasoning and the tool
   call from one inference are two blocks. Under a parent tool,
   `sub_turn_index` advances instead. Do not use `turn_index` to count LLM
   calls.
7. `tab-index-depends-on-narration` **`tab_index` depends on narration.** Only
   consecutive top-level tool calls in one model message share a `turn_index`
   as tabs (`chat/renderer.py:MessageRenderer.tool_placement`). Answer text or
   reasoning between two calls starts a new section, so the second call opens
   a new block at tab 0. A call in a later model step always opens a new
   block. Calls under a parent tool always take a new
   `sub_turn_index`. Saved-session replay uses the same renderer, so a change
   here changes reloads too.
8. `no-answer-end-packet` **The answer stream has no end packet, and errors are
   separate lines.** `AgentResponseDelta` ends at `OverallStop`. Each model's
   presenter sends one `OverallStop` with `stop_reason` `finished`, tagged with
   its `model_index`. `OverallStop` does not mean success: response errors
   arrive as `StreamingError`. After any cancellation,
   `ChatTurnExecution._publish` drops all producer packets, including that
   stop and the `SectionEnd` of open sections. A user Stop then ends with one
   untagged `OverallStop` with `user_cancelled`, sent after the saves report.
   A cancellation by the deadline, lost admission or a control failure ends
   the body with no `OverallStop` and no error. Clients must treat the end of
   the body as the end of rendering and close open sections there. A tool
   failure sends
   `backend/onyx/server/query_and_chat/streaming_models.py:PacketException` in
   its tab (`chat/renderer.py:ToolRenderer.complete`) only when the tool
   raised `ToolExecutionException` with `emit_error_packet=True`; other tool
   errors go only to the model. Its `exception` field is excluded from
   serialization, so the client gets a bare `error` packet with no message.
9. `tab-packets-interleave` **Tabs finish in any order.** Parallel calls run
   on their own threads, so packets of different tabs interleave and results
   arrive in completion order. Calls that a tool merges into one execution get
   the same packets in each tab. When a run ends,
   `chat/presentation.py:ResponsePresenter.consume` closes each open tab with
   its start packet, if not yet sent, and a bare `SectionEnd`. Key client state
   on `tab_index`. A new `ToolRenderer` branch must keep `start` and `complete`
   idempotent.
10. `replay-order-not-live-order` **Replay order is not live order.**
   Saved-session replay
   (`server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`)
   rebuilds a turn in its own order. A message with an execution record replays
   through `chat/presentation.py:replay_response` and the live renderer; an
   older row replays every `CitationInfo` after the answer
   ([[citations#citation-info-any-order]]). Do not add a packet whose meaning
   depends on its position.
11. `buffer-gap-ends-resume` **A buffer gap ends the resume, and the cursor
    counts chunks.** `chat/stream_buffer.py:read_stream_chunks` reports `gap`
    for a missing chunk, a bad chunk or a truncated buffer.
    `server/query_and_chat/chat_backend.py:resume_chat_stream` then ends the
    stream, and the client refetches the session. A capped read can say `done` with
    chunks still pending: read until `blocks` is empty. The cursor counts chunks,
    not packets. A client may keep a `StreamCursor.next_cursor` only together
    with every packet before it, and must send the matching `stream_id`, or it
    replays a cursor from another response. The first read fixes the restore
    boundary; `replay_complete` marks the end of the backlog. Lines that the
    writer has not flushed cannot be read.
12. `stream-end-is-not-idle` **The end of a stream does not mean the session
    is idle.** The body stays open after `OverallStop` until each response's
    save reports an outcome; a failed save sends `RESPONSE_SAVE_ERROR`. After
    the body closes, the turn keeps the session owner key until the final
    buffer flush and `chat/chat_processing_checker.py:ChatTurnAdmission.release`
    finish. A streamed send in that window gets HTTP 200 with one
    `StreamingError` (`error_code` `CONFLICT`, not retryable) and no ID lines,
    not an HTTP 409. Every client polls
    `server/query_and_chat/chat_backend.py:get_chat_session_processing_status`
    before it releases input or sends a queued message:
    `web/src/lib/chat/sessionReadiness.ts:waitForChatSessionIdle`,
    `mobile/src/chat/sessionReadiness.ts:waitForSessionIdle`,
    `cli/internal/api/client.go:IsChatSessionProcessing` and
    `widget/src/services/api-service.ts`. The CLI and widget stop with an error
    when an older server has no status endpoint. An old client in the field
    that sends as soon as the stream closes can meet the `CONFLICT` error.
13. `pure-asgi-middleware` **API middleware must be pure ASGI.** Each middleware
    on the API server is a function or class that wraps
    `await app(scope, receive, send)`, such as
    `utils/middleware.py:request_id_middleware`,
    `server/auth/captcha_api.py:CaptchaCookieMiddleware` and
    `backend/ee/onyx/server/middleware/tier_gate.py:tier_gate_middleware`. Do not
    use `BaseHTTPMiddleware` or `@app.middleware("http")`. That base class
    relays every body chunk through an AnyIO memory channel and a separate task,
    which costs CPU on each chunk of a long chat stream. A pure ASGI middleware
    sets its context variable around the whole call, so the request ID, tenant
    and endpoint context hold until the streamed body and its background task
    end, and reset on completion or cancellation. A middleware that measures or
    logs must wrap `send`: `server/middleware/latency_logging.py:latency_logging_middleware`
    logs at `http.response.start`, before the body. The MCP server is a separate
    app and uses `@app.middleware("http")` for its health check; do not copy it.
14. `cli-json-event-names` **The CLI event names are an output contract.**
    `ask --json` prints each event as `{type, event}`, with `type` from the
    event's `EventType()` in `cli/internal/models/events.go`. Scripts read
    these names and fields. Keep a name when you rename the wire type, or
    accept both, as [[#old-bytes-across-deploy]] requires for clients.

---

## Known issues

- The web enum keeps `MESSAGE_END`. The mobile enum keeps `MESSAGE_END` and
  `TOP_LEVEL_BRANCHING`. The backend sends neither. Mobile drops
  `top_level_branching` so that it can talk to older servers. The
  `MESSAGE_END` in `backend/onyx/agents/events.py` belongs to the runtime event
  model, not to this protocol. `image_generation_heartbeat` is in the backend
  vocabulary, but no code sends it.
- **A resumed content-free incognito run loses its tail.**
  `chat/stream_buffer.py:StreamBufferWriter.mark_done` with `delete_on_done`
  deletes the keys right after the final flush. A `resume-stream` reader that
  has not read to the end stops when the meta key disappears, and shows the
  saved message. Incognito teardown
  (`chat/incognito_context.py:_finish_incognito_teardown`) deletes all buffer
  keys of the session, which ends any open resume.
- **A resume after a pod dies hangs, then ends with no error.** No other pod
  continues the run. `resume_chat_stream` sends heartbeats until the session
  admission lease lapses (the `chat/chat_processing_checker.py:ChatTurnAdmission`
  owner key: 60 s after publish, 120 s during preparation), not the response
  owner lease in `ChatRunStore`. It then ends with no done marker and no error line. The client
  must reload the saved session.
- **The parse fallback cannot recover a packet.** When a line fails to parse,
  `handleSSEStream` and the mobile buffer extract flat `{...}` objects. Every
  packet is nested, so the fallback yields fragments such as a bare `placement`.
  On web, parse failures go only to the console.

---

## Dependencies

- [[core-chat-loop]]: owns the emitter, delivery and buffer lifecycle per run,
  and the session admission that the status endpoint reads.
- [[citations]]: produces `CitationInfo`.
- [[tools-framework]]: each tool's packet sequence.
- [[multi-tenancy]]: the tenant middleware and the tenant-aware cache that holds
  the buffer.

---

## Recipes

- `packet-type` **A packet type.** Copy the file reader packets
  (`FileReaderStart`, `FileReaderResult`). List every place that knows them
  with `git grep -il file_reader`. The search must ignore case: the web
  renderers and hooks switch on the enum member `PacketType.FILE_READER_START`,
  not on the wire string.
  1. Add the value to `StreamingType`, the model class beside the other packet
     models, and the model to `PacketObj`.
  2. Build it in a `chat/renderer.py:ToolRenderer` branch (`start` for the
     arguments, `update` for a `details` type, `complete` for the final
     result), or in `MessageRenderer` for message content. If a new runtime
     `AgentEvent` produces it, add a branch in
     `chat/presentation.py:ResponsePresenter.consume`, which ignores event types
     it has no branch for. Do not build a `Placement` or call the `Emitter`
     directly. One branch serves the live stream and runtime replay.
  3. Add the type and interface to the web and mobile enums from
     [[#vocabulary-mirrored-by-hand]].
  4. Add a renderer case on web and on mobile. On web, follow
     [[chat-frontend#packet-type-web-sets]]. Mobile keeps its own copies of the
     grouping sets ([[mobile-app]]).
  5. For reload, follow [[chat-persistence#replay-new-tool]]. Runtime replay
     (`chat/presentation.py:replay_response`) calls `ToolRenderer.complete` with
     the saved result only, so the final `details` alone must produce the
     packet; packets built from progress-only details do not replay. A non-tool
     packet replays only if the saved response record keeps its data. The
     builders in `translate_assistant_message_to_packets` serve only legacy
     rows (NULL `response_status`), so a new packet needs no builder there.
  6. Update the other consumers from [[#vocabulary-mirrored-by-hand]]. The
     non-streaming API (`chat/process_message.py:gather_stream_full`) builds
     `ChatFullResponse` from the saved response snapshot, not from packets, so
     decide whether the snapshot needs the new data.
     `chat/process_message.py:gather_stream` ([[slack-bot]]) builds its answer
     from root answer and citation packets and skips packets with a
     `sub_turn_index`.
  7. If a test mocks the stream, update `web/tests/e2e/utils/chatMock.ts`.
- `cli-packet-type` **A packet type in the CLI.** Copy the search start event:
  list every place that knows it with `git grep -n SearchStartEvent -- cli`. A
  parser case alone shows nothing. Add the event struct and its `EventType()`
  name in `cli/internal/models/events.go`, the case in
  `cli/internal/parser/parser.go:ParseStreamLine`, then a render case in the
  interactive view (`cli/internal/tui/app.go`) and in the `ask` text output
  (`cli/cmd/ask.go`). The `--json` output carries the event with no extra code
  ([[#cli-json-event-names]]).
- `api-middleware` **A new API middleware.** Copy
  `utils/middleware.py:request_id_middleware`. List the registered middleware
  with `git grep -n "add_middleware" -- backend/onyx backend/ee/onyx`. Add a
  case to `backend/tests/unit/onyx/server/middleware/test_streaming_context.py`,
  which fails when a `BaseHTTPMiddleware` is in the stack
  ([[#pure-asgi-middleware]]).
- `investigate-missing-block` **Investigate a missing block or a bad resume.**
  In the browser network tab, copy the `send-chat-message` request as cURL and
  run it with `curl -N` against
  `http://localhost:3000/api/chat/send-chat-message`. Each line must be JSON;
  find the packet with its `placement`. If the line is there, the fault is in a
  renderer ([[chat-frontend]], [[mobile-app]]). If it is not, the fault is in
  the producer. For a resume, call
  `/api/chat/chat-session/<id>/resume-stream?cursor=0` while the run is live. A
  404 means the session owner key or the processing fence is missing, the
  `stream_id` does not match the fence, or the buffer meta key
  (`chatstream_<session_id>_<stream_id>:meta`) is missing. A stream that ends
  early means a gap ([[#buffer-gap-ends-resume]]). If the input stays busy
  after the stream ends, call `/api/chat/chat-session/<id>/status`
  ([[#stream-end-is-not-idle]]).

---

## Verification

- Unit: `backend/tests/unit/onyx/chat/` (emitter, stream buffer, renderer,
  replay, argument deltas) and `backend/tests/unit/onyx/server/middleware/`
  (context through a streamed body).
- Integration: `backend/tests/integration/tests/streaming_endpoints/`.
- Clients: `cli/internal/parser/parser_test.go`, the readiness tests beside
  each client's readiness code, and `web/tests/e2e/chat/stream_recovery.spec.ts`.
- Playwright: `web/tests/e2e/chat/`. The helpers in
  `web/tests/e2e/utils/chatStream.ts` parse a real body, and
  `web/tests/e2e/utils/chatMock.ts` builds mock bodies.
- By hand: in the browser network tab, each line of the `send-chat-message`
  body is JSON. Reload during an answer: the client must call `resume-stream`
  and show the same answer. Wait through a long tool call: heartbeat lines
  arrive and never render.

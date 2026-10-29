# Streaming Protocol

> The wire contract between the chat backend and every client: the packet
> vocabulary, the `Placement` coordinates, the path from a worker thread to the
> HTTP body, and the buffer that lets a client resume a stream it lost.

**Verified against:** `a4e97fcea1` (2026-10-29)
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
- **Quiet phases.** During a long tool call the connection stays open, because
  the server sends heartbeats. The user does not see them.
- **When this layer breaks**, the user sees a hole in the answer and no error.
  A packet type that a client does not know renders nothing.
- **An API caller** reads one JSON object per line. The response says
  `text/event-stream`, but the body is NDJSON, not SSE. Most lines are packets
  with `placement` and `obj`. Some lines are not: the session and message IDs
  at the start, and `StreamingError` objects. To resume, the caller calls
  `GET /chat/chat-session/{id}/resume-stream?cursor=0`. A 404 means that no run
  can be resumed. The public guide is
  `documentation/developers/guides/chat_new_guide.mdx`.
- **A CLI user** gets the same stream through the Onyx CLI, which parses each
  line in `cli/internal/parser/parser.go:ParseStreamLine`. A type the CLI does
  not know becomes an `UnknownEvent` and shows nothing. A line that is not JSON
  shows as an error.

---

## Scope

This component owns the packet vocabulary, `Placement`, the line framing, the
path from the emitter to the HTTP body, the resume buffer and the resume
endpoint's read rules, the client mirrors of the vocabulary, and the rule that
API middleware keeps request context through a streamed body. It shares the
emitter and the buffer writer with [[core-chat-loop]], which owns when they run.

It does not own:
- the producers: [[core-chat-loop]] and each tool ([[tools-framework]]);
- the renderers: [[chat-frontend]] and [[mobile-app]];
- the saved-session replay, which rebuilds packets from saved rows:
  [[chat-persistence]];
- what `CitationInfo` means and its ordering rule: [[citations]];
- the runtime renderer and presentation modules, which are not wired:
  [[agent-runtime]].

---

## Architecture

```
producer (llm_step, tool)            Packet(placement, obj)
  -> Emitter.emit                    no-op after drain_done; stamps model_index
  -> merged_queue                    one queue for all models
  -> writer _publish                 get_json_line(packet) ->
       StreamBufferWriter.append_line   zlib chunks in the cache, flushed at 32 KiB
                                        or when the queue idles
       tee -> reader -> HTTP body       reader adds ChatHeartbeat when idle
                                        for CHAT_HEARTBEAT_INTERVAL_S

resume-stream: get_processing_stream_id -> read_stream_chunks(cursor, 32 per read)
  -> replay blocks -> poll until done or the fence lapses, with heartbeats
```

**Line kinds.** `chat/models.py:AnswerStreamPart` lists what the backend
writes: `Packet`, `MessageResponseIDInfo`, `MultiModelMessageResponseIDInfo`,
`CreateChatSessionID` and `StreamingError`. Only `Packet` has a placement. A
per-model error puts `model_index` in `StreamingError.details`.

**`Placement`.** `turn_index` is the rendering block. `tab_index` separates
parallel tool calls in one block. `sub_turn_index` is set for packets from a
tool that runs its own loop, such as the research agent. `model_index` is the
model column. It is `None` on packets that no `Emitter` tagged, such as
heartbeats.

**Packet families.**
`backend/onyx/server/query_and_chat/streaming_models.py:StreamingType` holds every type string, and `PacketObj` is the union that `Packet.obj` is
validated against. Families are control (`stop`, `section_end`, `error`,
`chat_heartbeat`), reasoning, answer (`message_start`, `message_delta`),
citations, one family per tool, deep research, and the coding agent with the
bash tool. `ToolCallArgumentDelta` streams string arguments for tools whose
`should_emit_argument_deltas` returns true (`chat/tool_call_args_streaming.py`).
`ToolCallDebug` appears only with `INTEGRATION_TESTS_MODE`.

**Buffer.** The key is the session ID plus the stream ID (the reserved assistant
message ID, or the user message ID in a multi-model turn). Keys live in the
cache backend (`cache/factory.py:get_cache_backend`): Redis, or Postgres when
`CACHE_BACKEND=postgres`. Chunks expire after `CHAT_STREAM_BUFFER_TTL_S`, and
after `CHAT_STREAM_BUFFER_DONE_TTL_S` once the run is done. A run over
`CHAT_STREAM_BUFFER_MAX_BYTES`, or a cache error, marks the buffer `truncated`.
The run continues without resume.

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
   wrote, until `CHAT_STREAM_BUFFER_TTL_S` passes. Mobile builds and CLI binaries
   in the field keep the old vocabulary much longer. Accept the old name or
   framing, or add the new one beside it.
3. `unknown-packet-renders-nothing` **An unknown packet renders nothing.**
   `web/src/app/app/message/messageComponents/renderMessageComponent.tsx:findRenderer`
   returns `null` when no predicate matches. Keep that path for
   new families: an unguarded cast can throw instead.
4. `emitter-sets-model-index` **Only `chat/emitter.py:Emitter.emit` sets
   `model_index`.** It
   overwrites what the producer set. Packets that the writer publishes itself,
   such as the stop `OverallStop`, and heartbeats have no `model_index`.
5. `not-every-line-is-a-packet` **Not every line is a packet, and heartbeats are
   the consumer's job.** Clients must check for `obj` before they read it, as
   `web/src/hooks/useChatSessionController.ts` does on resume. On web, the name
   `PacketType` means two things: the enum of type strings in
   `web/src/app/app/services/streamingModels.ts`, and the union of line shapes in
   `web/src/app/app/services/lib.tsx`. `web/src/app/app/services/lib.tsx:sendMessage`
   drops heartbeats with `withoutHeartbeats`.
   `web/src/app/app/services/lib.tsx:resumeStream` keeps them, because its
   caller uses them as liveness ticks. A new consumer of
   `web/src/lib/search/streamingUtils.ts:handleSSEStream` sees them.
6. `turn-index-is-not-a-turn` **`turn_index` is not a backend turn.** It is a
   rendering block. The loop sets it to the cycle count plus the number of
   cycles that produced reasoning, so reasoning and the tool call from one
   inference are two blocks. Inside a nested loop, `sub_turn_index` advances
   instead. Do not use `turn_index` to count LLM calls.
7. `tab-index-depends-on-narration` **`tab_index` depends on narration.** Native
   tool calls start at tab 1 when the model wrote answer text before them, so
   they render as their own group (`chat/llm_step.py:_extract_tool_call_kickoffs`,
   `tab_index_start`). Calls that the fallback parser recovers from text start
   at 0 (`chat/llm_step.py:extract_tool_calls_from_response_text`).
8. `no-answer-end-packet` **The answer stream has no end packet, and errors are
   separate lines.** `AgentResponseDelta` ends at `OverallStop`. `OverallStop`
   ends rendering. It does not mean success: errors arrive as `StreamingError`.
   `backend/onyx/server/query_and_chat/streaming_models.py:PacketException`
   never reaches the wire, because its `exception` field is excluded from
   serialization.
9. `replay-order-not-live-order` **Replay order is not live order.**
   Saved-session replay
   (`server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`)
   rebuilds a turn in its own order, for example all `CitationInfo` after the
   answer ([[citations#citation-info-before-text]]). Do not add a packet whose meaning depends
   on its position.
10. `buffer-gap-ends-resume` **A buffer gap ends the resume, and the cursor
    counts chunks.** `chat/stream_buffer.py:read_stream_chunks` reports `gap`
    for a missing chunk, a bad chunk or a truncated buffer.
    `server/query_and_chat/chat_backend.py:resume_chat_stream` then ends the
    stream, and the client refetches the session. A capped read can say `done` with
    chunks still pending: read until `blocks` is empty. The cursor counts chunks,
    not packets, so web and mobile resume from 0 and rebuild the message from the
    full replay. Lines that the writer has not flushed cannot be read.
11. `pure-asgi-middleware` **API middleware must be pure ASGI.** Each middleware
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
12. `cli-json-event-names` **The CLI event names are an output contract.**
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
  model, not to this protocol.
- `SectionEnd` has a code comment that marks it for removal, but renderers
  still use it to close blocks.
- **A resumed content-free incognito run loses its tail.**
  `chat/stream_buffer.py:StreamBufferWriter.mark_done` with `delete_on_done`
  deletes the keys at completion without a last flush. A client that reads
  through `resume-stream` stops at that point and shows the saved message. The
  writer also stops buffering when the incognito session ends.
- **The parse fallback cannot recover a packet.** When a line fails to parse,
  `handleSSEStream` and the mobile buffer extract flat `{...}` objects. Every
  packet is nested, so the fallback yields fragments such as a bare `placement`.
  On web, parse failures go only to the console.

---

## Dependencies

- [[core-chat-loop]]: owns the emitter, writer and buffer lifecycle per run.
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
  2. Emit it through the `Emitter` with a real `Placement`.
  3. Add the type and interface to the web and mobile enums from
     [[#vocabulary-mirrored-by-hand]].
  4. Add a renderer case on web and on mobile. On web, follow
     [[chat-frontend#packet-type-web-sets]]. Mobile keeps its own copies of the
     grouping sets ([[mobile-app]]).
  5. If the packet must survive a reload, add it to the replay in
     `translate_assistant_message_to_packets` ([[chat-persistence]]). Replay can
     rebuild a packet only from saved data, the `ToolCall` row or the message.
     Save the data first.
  6. Update the other consumers from [[#vocabulary-mirrored-by-hand]]. The
     non-streaming path (`chat/process_message.py:gather_stream_full`) ignores
     packet types it does not know, so decide whether `ChatFullResponse` needs
     the new data.
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
  404 means the processing fence or the buffer meta key
  (`chatstream_<session_id>_<stream_id>:meta`) is missing. A stream that ends
  early means a gap ([[#buffer-gap-ends-resume]]).

---

## Verification

- Unit: `backend/tests/unit/onyx/chat/` (emitter, stream buffer, tool
  placement, argument deltas) and `backend/tests/unit/onyx/server/middleware/`
  (context through a streamed body).
- Integration: `backend/tests/integration/tests/streaming_endpoints/`.
- CLI: `cli/internal/parser/parser_test.go`.
- Playwright: `web/tests/e2e/chat/`. The helpers in
  `web/tests/e2e/utils/chatStream.ts` parse a real body, and
  `web/tests/e2e/utils/chatMock.ts` builds mock bodies.
- By hand: in the browser network tab, each line of the `send-chat-message`
  body is JSON. Reload during an answer: the client must call `resume-stream`
  and show the same answer. Wait through a long tool call: heartbeat lines
  arrive and never render.

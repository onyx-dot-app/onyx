# Streaming Protocol

> The wire contract between the chat backend and every client. It defines the
> packet vocabulary, where each packet belongs in the UI, how packets travel
> from a worker thread to an HTTP response, and how a client resumes a stream
> it lost.

**Domain:** core-loop
**Edition:** CE
**Owns:**
`backend/onyx/server/query_and_chat/streaming_models.py`, `placement.py`,
`backend/onyx/chat/emitter.py`, `stream_buffer.py`,
`web/src/app/app/services/streamingModels.ts`, `web/src/lib/search/streamingUtils.ts`,
`mobile/src/chat/streamingModels.ts`, `mobile/src/chat/ndjson.ts`

---

## 1. What the user experiences

None of this is directly visible. It is the substrate that makes the chat
experience possible: reasoning appearing token by token, a search tool block
opening before its documents arrive, an image placeholder resolving into a
picture, a page reload picking an in-flight answer back up instead of losing
it. When this layer is correct, the user never thinks about it. When a packet
type has no frontend renderer, or a client cannot parse a line, the user sees
a hole in the answer with no error.

---

## 2. Surfaces

### HTTP endpoints (router prefix `/chat`, `chat_backend.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/chat/send-chat-message` | `handle_send_chat_message` | Live stream. NDJSON `text/event-stream` when `stream=true`; a multi-model request streams too, via `multi_model_stream_generator`. |
| GET | `/chat/chat-session/{id}/resume-stream` | `resume_chat_stream` | Replays the durable buffer from `cursor`, then tails the live run. 404 when there is no resumable run. |
| GET | `/chat/get-chat-session/{id}` | `get_chat_session` | Not a live stream. Returns the persisted session; the frontend renders it through the same packet types. |

`handle_send_chat_message` builds its NDJSON body with `get_json_line`
(`backend/onyx/server/utils.py:get_json_line`), which `json.dumps`s the packet and
appends `"\n"`. Both `stream_generator` and `multi_model_stream_generator` write
one JSON object per line this way.

### Environment configuration (`backend/onyx/configs/chat_configs.py`)

| Variable | Default | Effect |
|---|---|---|
| `CHAT_HEARTBEAT_INTERVAL_S` | 15 | Cadence of `ChatHeartbeat` packets, live and resumed. |
| `CHAT_RESUME_POLL_INTERVAL_S` | 0.2 | Poll interval `resume_chat_stream` uses while tailing a live run. |
| `CHAT_STREAM_BUFFER_TTL_S` | 3600 | TTL of each buffered chunk and the run's meta key while the run is in progress. |
| `CHAT_STREAM_BUFFER_DONE_TTL_S` | 600 | TTL applied to the same keys once the run finishes. |
| `CHAT_STREAM_BUFFER_MAX_BYTES` | 16 MiB | Cap on compressed bytes per run; past this the buffer is marked `truncated` and resume stops being possible. |
| `INTEGRATION_TESTS_MODE` | | Enables `ToolCallDebug` packets (`llm_loop.py`, guarded by `if INTEGRATION_TESTS_MODE and tool_calls`) and `mock_llm_response`. |

`_RESUME_MAX_CHUNKS_PER_READ = 32` (`chat_backend.py`) caps how many buffer chunks
`resume_chat_stream` decompresses per loop iteration, bounding peak memory on a
resume read.

---

## 3. Data model

This component has no tables. Packets are never written to Postgres; the chat
tables under [[chat-persistence]] store the *result* of a turn (`ChatMessage`,
`ToolCall`, `SearchDoc`), not the packet stream that produced it.

The only durable storage here is the **stream buffer**, a transient,
cross-pod cache structure (`backend/onyx/chat/stream_buffer.py`), used so any
api-server pod can replay and tail an in-flight run:

- **Chunk keys** (`chatstream_{chat_session_id}_{run_id}:{chunk_n}`): zlib-compressed
  concatenations of the raw NDJSON lines written since the last flush
  (`StreamBufferWriter.flush`, threshold `_FLUSH_THRESHOLD_BYTES = 32 KiB`).
- **Meta key** (`chatstream_{chat_session_id}_{run_id}:meta`): a `StreamBufferMeta`
  (`chunk_count`, `done`, `truncated`) as JSON.
- Both live in `CacheBackend` (Redis, or Postgres on the lite deployment flavor)
  with TTL `CHAT_STREAM_BUFFER_TTL_S`, extended to `CHAT_STREAM_BUFFER_DONE_TTL_S`
  once `mark_done` runs.
- Incognito (content-free) runs set `delete_on_done=True`: `mark_done` deletes
  every chunk and the meta key immediately instead of expiring them, so no
  content survives past the run.
- A missing chunk before `done` is set (`allkeys-lru` eviction, expiry) is a
  **gap**: `read_stream_chunks` returns `gap=True`, and callers must fall back to
  the persisted message rather than replay a broken sequence.

---

## 4. How it works

### 4.1 Packet vocabulary

Every packet is a `Packet(placement: Placement, obj: PacketObj)`
(`streaming_models.py:Packet`). `PacketObj` is a `Union` discriminated on the
literal `type` field (`Field(discriminator="type")`), and `StreamingType`
(`streaming_models.py:StreamingType`) is the single source of truth for the
string values.

| Family | Type(s) | Meaning |
|---|---|---|
| Control | `SectionEnd` | Closes the current tool/reasoning block on the frontend. |
| Control | `OverallStop` | Ends the whole run. Carries `stop_reason` (`"user_cancelled"` or unset for natural completion). Also the terminator for `AgentResponseDelta`, which has no dedicated end packet. |
| Control | `TopLevelBranching` | Sent ahead of parallel tool calls (`num_parallel_branches`) so the frontend allocates all branches before any of them renders, instead of rendering one and re-flowing. |
| Control | `PacketException` | Carries a Python `Exception` (`Field(exclude=True)`, never serialized); used internally, not over the wire as JSON (see §9). |
| Control | `ChatHeartbeat` | Payload-less keepalive so idle proxies do not kill a silent stream. |
| Reasoning | `ReasoningStart` / `ReasoningDelta` / `ReasoningDone` | Opens the reasoning block, streams its tokens, closes it. |
| Answer | `AgentResponseStart` | Opens the final answer block. Carries `final_documents` and `pre_answer_processing_seconds`. |
| Answer | `AgentResponseDelta` | One chunk of the answer (`content`). No end packet; see `OverallStop` above. |
| Answer | `CitationInfo` | One citation: `citation_number` (LLM-visible ordinal) to `document_id` (connector doc id, matches the DB). See [[citations]]. |
| Debug | `ToolCallDebug` | Full tool name/args/id, only under `INTEGRATION_TESTS_MODE`. |
| Debug | `ToolCallArgumentDelta` | Streams tool-call arguments (`tool_type`, `argument_deltas`) before the tool executes; used by, e.g., the Python tool renderer to show code as it is typed. |
| Search tool | `SearchToolStart`, `SearchToolQueriesDelta`, `SearchToolFilterDelta`, `SearchToolDocumentsDelta` | Opens the internal/web search block (`is_internet_search` distinguishes them), streams expanded queries, streams applied filters, delivers the found documents. |
| Open URL tool | `OpenUrlStart`, `OpenUrlUrls`, `OpenUrlDocuments` | Three-stage sequence: start, the URLs to crawl, the crawled documents. |
| Image tool | `ImageGenerationToolStart`, `ImageGenerationToolHeartbeat`, `ImageGenerationFinal` | Placeholder, keepalive during generation, then all images at once (`GeneratedImage` list). |
| Python tool | `PythonToolStart`, `PythonToolDelta` | Code block, then `stdout`/`stderr`/`file_ids` as they arrive. |
| Custom tool | `CustomToolStart`, `CustomToolArgs`, `CustomToolDelta` | Placeholder, args, then a typed response (`data` or `file_ids`, optionally `CustomToolErrorInfo`). |
| File reader tool | `FileReaderStart`, `FileReaderResult` | Placeholder, then the retrieved excerpt (`file_id`, char range, text previews). |
| Memory tool | `MemoryToolStart`, `MemoryToolDelta`, `MemoryToolNoAccess` | Placeholder, an add/update memory op, or a no-access notice. |
| Deep research | `DeepResearchPlanStart/Delta`, `ResearchAgentStart`, `IntermediateReportStart/Delta`, `IntermediateReportCitedDocs` | Plan text, sub-agent kickoff, intermediate report text and its cited docs. |
| Coding agent | `CodingAgentStart`, `CodingAgentThinkingDelta`, `CodingAgentFinal` | Query/repo, thinking tokens, final answer. Shares the run with `BashToolStart`/`BashToolDelta` for the shell it drives. |
| Bash tool | `BashToolStart`, `BashToolDelta` | Command, then `stdout`/`stderr`/`exit_code`/`timed_out`. |

### 4.2 `Placement`

`Placement` (`placement.py:Placement`) is the coordinate every packet carries:

- `turn_index`: the frontend's rendering block index, not a backend turn. One
  LLM inference producing reasoning plus a tool call is one backend step but
  advances `turn_index` more than once (`llm_step.py:_increment_turns` pattern,
  driven from `llm_loop.py`).
- `tab_index`: disambiguates parallel tool calls that share a `turn_index`, so
  each gets its own tab in the UI (`llm_step.py`, built during fallback tool
  extraction with `enumerate(matched_tool_calls)`).
- `sub_turn_index`: nesting level for a tool that calls other tools; `None` at
  the top level.
- `model_index`: which model produced the packet in a multi-model turn (`0`,
  `1`, or `2`); `None` for pre-LLM setup packets yielded before any `Emitter`
  runs. **Only the `Emitter` sets this field.**

### 4.3 The emitter path

`Emitter.emit` (`emitter.py:Emitter.emit`):

1. No-ops immediately if `drain_done` is set, so a cancelled turn's workers stop
   pushing packets without blocking on the queue.
2. Copies the packet's `Placement` with `model_index` overwritten
   (`base.model_copy(update={"model_index": self._model_idx})`). The producer's
   own `model_index`, if any, is discarded here.
3. Puts `(model_idx, tagged_packet)` onto the shared `merged_queue`, the same
   queue every model's worker thread writes to, per [[core-chat-loop]].

`NullEmitter` (`emitter.py:NullEmitter`) implements the same interface but
discards every packet. It is used where tools run outside a chat turn (the
Search API, the MCP server), so tool code does not need to branch on whether it
is inside a streaming context.

### 4.4 Transport

`handle_send_chat_message` and `resume_chat_stream` both return
`StreamingResponse(..., media_type="text/event-stream")`
(`chat_backend.py:handle_send_chat_message`, `chat_backend.py:resume_chat_stream`),
but the body is **NDJSON**, not SSE framing: one `json.dumps(...) + "\n"` line
per packet (`onyx/server/utils.py:get_json_line`), no `data:` prefix, no `event:`
field.

On the frontend, `handleSSEStream` (`web/src/lib/search/streamingUtils.ts:handleSSEStream`)
reads the response body, decodes it, splits the accumulated buffer on `"\n"`,
and `JSON.parse`s each complete line, holding the trailing partial line for the
next chunk. If a line fails to parse, it falls back to a regex,
`line.match(/\{[^{}]*\}/g)`, and tries to parse each match individually.
`sendMessage` (`web/src/app/app/services/lib.tsx:sendMessage`) wraps this in
`withoutHeartbeats` (`lib.tsx:withoutHeartbeats`), which drops any packet whose
`obj.type === "chat_heartbeat"` before the caller ever sees it.
`resumeStream` (`lib.tsx:resumeStream`) uses the same `handleSSEStream`, but does
**not** filter heartbeats: callers use them as liveness ticks.

Mobile mirrors this independently: `mobile/src/chat/ndjson.ts:NdjsonBuffer` is a
pure line-buffer with the same brace-recovery fallback, explicitly commented as
matching web's `handleSSEStream` internals.

### 4.5 Buffering and resume

`process_message.py` constructs one `StreamBufferWriter` per run
(`process_message.py`, near `stream_buffer = StreamBufferWriter(...)`) and calls
`stream_buffer.append_line(get_json_line(...))` for every packet before it
reaches the HTTP response, in addition to yielding it live. `flush` compresses
and writes a new chunk once `_FLUSH_THRESHOLD_BYTES` of pending text accumulates;
`mark_done` finalizes the meta record when the run ends.

`resume_chat_stream` (`chat_backend.py:resume_chat_stream`) replays from
`cursor` via `read_stream_chunks`, yielding decompressed blocks verbatim, then
either detects `done` or falls into a poll loop (`CHAT_RESUME_POLL_INTERVAL_S`)
that checks `is_chat_session_processing` to tell a live writer from a dead one,
emitting `ChatHeartbeat` packets on `CHAT_HEARTBEAT_INTERVAL_S` while waiting.

---

## 5. Contracts and invariants

1. **`StreamingType` is the single source of truth for type strings, and two
   clients mirror it by hand**: `web/src/app/app/services/streamingModels.ts:PacketType`
   and `mobile/src/chat/streamingModels.ts`. Nothing enforces this at build
   time. Adding, renaming, or removing a value in `StreamingType` and not
   updating both frontends is a silent break.
2. **A packet with no frontend renderer renders as nothing.** `findRenderer`
   (`web/src/app/app/message/messageComponents/renderMessageComponent.tsx:findRenderer`)
   returns `null` when no `is*Packet` predicate matches a group. A new packet
   type needs both a TypeScript interface and a case in this dispatch (and its
   mobile equivalent) or it is silently dropped from the UI.
3. **`model_index` is stamped only by `Emitter.emit`.** No producer (tool,
   `llm_loop`, `llm_step`) should set it directly; `emit` overwrites whatever
   was there.
4. **Every packet needs a `Placement`.** `Packet` has no default for
   `placement`; a packet built without one fails validation before it can be
   emitted.
5. **Unknown packet types must not crash a client.** The frontend union
   (`PacketType` in `web/src/app/app/services/lib.tsx`) and the backend
   discriminated union are both closed sets; a client that receives a `type`
   it does not recognize should degrade to "render nothing for this group",
   not throw. `findRenderer`'s `null` return is this behavior; verify a new
   family does not bypass it with an unguarded cast.
6. **The replay path must produce packets the frontend renders identically, but
   not necessarily in the same order.** `GET /chat/get-chat-session/{id}`
   reconstructs a session for display without re-running the turn. Whatever it
   emits must satisfy the `PacketObj` union. Ordering is **not** identical: live
   streaming interleaves `CitationInfo` with the answer text
   (`citation_processor.py:_process_citation`), while replay emits every
   `CitationInfo` after the whole answer block and under a separate
   `turn_index` (`session_loading.py:create_citation_packets`, and the
   `# Citations come after the message` comment beside its call site). This is
   safe only because the frontend folds citation packets into a map rather than
   consuming them positionally. Do not "fix" the ordering difference, and do not
   introduce a packet family whose meaning depends on position. See
   [[chat-persistence]] and [[citations]].
7. **Mobile parses this exact stream.** `mobile/src/chat/streamingModels.ts` and
   `mobile/src/chat/ndjson.ts` consume the same NDJSON body as web. A framing or
   vocabulary change reaches [[mobile-app]] as certainly as it reaches
   [[chat-frontend]].
8. **`AgentResponseDelta` has no end packet.** Code that assumes every stream
   family closes with a matching `*Done`/`*End` packet needs a special case
   for the answer stream, which closes via `OverallStop`.
9. **`PacketException.exception` never serializes.** It is `Field(exclude=True)`;
   the field exists for in-process error propagation, not for the wire. A
   client-visible error goes out as `StreamingError`
   (`backend/onyx/chat/models.py:StreamingError`), a sibling of `Packet` in the
   `AnswerStreamPart` union, not as a `PacketObj`.
10. **The stream buffer can develop a gap.** `read_stream_chunks` returning
    `gap=True` means the sequence is unrecoverable; `resume_chat_stream` ends
    the stream rather than replay a broken run, and the client must fall back
    to `GET /chat/get-chat-session/{id}`.

---

## 6. Relationships

**Depends on**
- [[core-chat-loop]]: `llm_loop.py` and `llm_step.py` are the packet producers;
  `process_message.py` owns the `Emitter` and `StreamBufferWriter` lifecycle per
  run.
- [[citations]]: `CitationInfo` packets originate from the citation processor
  running inside the loop.
- [[tools-framework]]: each tool family's packets are defined by that tool's
  contract with the loop.

**Depended on by**
- [[chat-frontend]]: `findRenderer` and the renderer tree are the sole consumer
  of the packet stream on web.
- [[mobile-app]]: parses the identical NDJSON stream with its own mirrored enum
  and buffer.
- [[chat-persistence]]: `save_chat_turn` persists what the packets represented;
  the session-replay path renders persisted rows back through this same packet
  vocabulary.
- [[slack-bot]], [[discord-bot]], [[onyx-api]], [[mcp-server]]: any surface that
  drives a turn through [[core-chat-loop]] either consumes this stream directly
  or uses `NullEmitter` to opt out of it.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a packet type | `StreamingType` and the `PacketObj` union; `web/src/app/app/services/streamingModels.ts:PacketType` and its interface; `mobile/src/chat/streamingModels.ts`; a `findRenderer` case (and mobile's `findRenderer.ts`) or the packet silently renders nothing |
| renames a packet type | every hand-mirrored enum above; any Playwright mock stream in `web/tests/e2e/utils/chatMock.ts` that hardcodes the old string; a saved stream buffer chunk mid-flight uses the old name until it drains |
| changes `Placement` (adds/removes/redefines a field) | every call site that constructs `Placement(...)` in `llm_loop.py` and `llm_step.py`; `Emitter.emit`'s `model_copy(update=...)`; the frontend `Placement` interface in `streamingModels.ts`; the grouping logic that keys off `turn_index`/`tab_index` in [[chat-frontend]] |
| changes a tool's packet sequence (adds/reorders/removes a stage) | that tool's renderer under `web/src/app/app/message/messageComponents/renderMessageComponent.tsx` and its mobile equivalent; [[tools-framework]] for the tool's producer-side contract |
| changes the transport framing (NDJSON, line delimiter, SSE headers) | `handleSSEStream` and `withoutHeartbeats` on web; `NdjsonBuffer` on mobile; `resume_chat_stream`'s replay, since buffered chunks are raw NDJSON bytes written by the old framing |
| changes stream buffer TTLs or chunk size | resumability window for slow clients; `_RESUME_MAX_CHUNKS_PER_READ` memory bound in `chat_backend.py` |

---

## 8. How to verify a change

### Tests

```bash
# Frontend Playwright specs that assert directly on the packet stream.
cd web && bunx playwright test tests/e2e/chat/chat_message_rendering.spec.ts
```

`web/tests/e2e/utils/chatStream.ts` (`parseChatStreamBody`, `getPacketObjectsByType`)
and `web/tests/e2e/utils/chatMock.ts` (`buildMockStream`, `mockChatEndpoint`) build
and parse mock NDJSON bodies matching this exact format; use them when a test
needs to assert on packet ordering or a new packet type without a real LLM call.

`INTEGRATION_TESTS_MODE=true` is required for tests that need `ToolCallDebug`
packets to assert which tool ran and with what arguments
(`llm_loop.py`, gated by `if INTEGRATION_TESTS_MODE and tool_calls`), and to use
`mock_llm_response` at all (`process_message.py` raises otherwise).

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open the browser devtools Network tab, send a chat message that triggers a
   search and an answer, and inspect the `send-chat-message` response body: it
   should be newline-separated JSON objects, each with a `placement` and `obj`.
3. Reload mid-answer; confirm the client calls `resume-stream` and the buffered
   packets replay before the live tail resumes.
4. Wait through a quiet stretch (or throttle the LLM) and confirm
   `chat_heartbeat` lines appear roughly every `CHAT_HEARTBEAT_INTERVAL_S`
   seconds, and that they never appear in the rendered UI.

### What "working" looks like

- Every packet line is valid JSON with a `placement` and a recognized `obj.type`.
- No packet type in the response goes unrendered unless it is intentionally
  invisible (e.g. `ChatHeartbeat`, `SectionEnd`).
- A resumed stream is visually identical to what the live stream would have
  produced.

---

## 9. Footguns

- **`turn_index` is not a backend turn.** It is a frontend rendering block
  boundary. Do not use it to count LLM inferences or tool-call cycles; use the
  loop's own cycle counters for that (see [[core-chat-loop]]).
- **Heartbeats are filtered client-side, not server-side.** `send-chat-message`
  emits `ChatHeartbeat` packets over the wire; `withoutHeartbeats` in
  `lib.tsx` strips them before the rest of the app sees them. A consumer that
  bypasses `sendMessage` and calls `handleSSEStream` directly will see
  heartbeats mixed into its packets.
- **The frontend's regex fallback can silently mis-parse.** `handleSSEStream`'s
  `line.match(/\{[^{}]*\}/g)` only recovers flat (non-nested) JSON objects. A
  malformed line containing a nested object (e.g. a tool packet with a `data`
  object) can extract a partial, wrong object instead of failing loudly.
- **`PacketException` cannot reach the client as-is.** Its `exception` field is
  excluded from serialization; sending one directly over the wire yields an
  `obj` with no usable content. Client-visible errors must go out as the
  sibling type `StreamingError`, not as a `Packet` wrapping `PacketException`.
- **A capped buffer read (`max_chunks`) can return `done=True` with more data
  still pending.** Any new reader of `read_stream_chunks` must loop until
  `blocks` comes back empty, not stop at the first `done=True`.

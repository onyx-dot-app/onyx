# Core Chat Loop

> The turn engine. It takes one user message, assembles context, runs an LLM with
> tools until the LLM stops calling them, streams packets out, and saves the result.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE, with EE additions in prompt and search layers
**Owns:**
`backend/onyx/chat/process_message.py`, `backend/onyx/chat/agent.py:ChatAgent`, `backend/onyx/chat/renderer.py:MessageRenderer`, `backend/onyx/chat/models.py`,
`emitter.py`, `stop_signal_checker.py`, `chat_processing_checker.py`, `stream_buffer.py`,
`backend/onyx/server/query_and_chat/chat_backend.py`

**Read first:** `backend/onyx/chat/README.md`. It is the design rationale for this
component, written by the people who built it. This document maps it to code and
adds verification guidance.

---

## 1. What the user experiences

The user types a message and sends it. The assistant may think out loud, may run
one or more tools (search the company index, search the web, run code, generate an
image), and then streams an answer with citations. The user can stop generation at
any point, and gets to keep whatever was produced. If the browser tab reloads
mid-answer, the answer resumes rather than being lost.

A user can also send one message to two or three models at once and compare the
answers side by side, then mark one as preferred.

---

## 2. Surfaces

### HTTP endpoints (router prefix `/chat`, `chat_backend.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/chat/send-chat-message` | `handle_send_chat_message` | **The turn endpoint.** Returns NDJSON `text/event-stream` when `stream=true`, else a single `ChatFullResponse`. |
| GET | `/chat/chat-session/{id}/resume-stream` | `resume_chat_stream` | Replays the durable buffer, then tails the live stream. |
| POST | `/chat/stop-chat-session/{id}` | `stop_chat_session` | Sets the stop fence for one stream. Optional `stream_id` query parameter. Without it, the endpoint stops the stream in the processing fence. |
| POST | `/chat/create-chat-session` | `create_new_chat_session` | |
| GET | `/chat/get-chat-session/{id}` | `get_chat_session` | Replays saved packets for a loaded session. |
| GET | `/chat/get-user-chat-sessions` | `get_user_chat_sessions` | |
| PUT | `/chat/rename-chat-session`, `PATCH /chat/chat-session/{id}` | `rename_chat_session`, `patch_chat_session` | |
| DELETE | `/chat/delete-chat-session/{id}`, `/chat/delete-all-chat-sessions` | `delete_chat_session_by_id`, `delete_all_chat_sessions` | |
| PUT | `/chat/update-chat-session-{model,temperature,reasoning}` | `update_chat_session_model`, `update_chat_session_temperature`, `update_chat_session_reasoning` | Per-session overrides. |
| PUT | `/chat/set-preferred-response` | `set_preferred_response_endpoint` | Picks the winner of a multi-model turn. |
| PUT | `/chat/set-message-as-latest` | `set_message_as_latest` | Branch selection. |
| POST/DELETE | `/chat/create-chat-message-feedback`, `/chat/remove-chat-message-feedback` | `create_chat_feedback`, `remove_chat_feedback` | |
| GET | `/chat/search` | `search_chats` | Search across the user's own chat history. |
| GET | `/chat/file/{file_id:path}` | `fetch_chat_file` | Serves a file attached to a message. |
| GET | `/chat/max-selected-document-tokens`, `/chat/available-context-tokens/{id}` | `get_max_document_tokens`, `get_available_context_tokens_for_session` | Budget introspection for the UI. |
| GET/POST | `/chat/incognito-availability`, `/chat/end-incognito-session/{id}` | `get_incognito_availability`, `end_incognito_session` | See §9. |
| POST | `/chat/seed-chat-session-from-slack` | `seed_chat_from_slack` | Continue a Slack thread in the web UI. See [[slack-bot]]. |

`send-chat-message` layers three dependencies: `require_permission(Permission.WRITE_CHAT, allow_anonymous=True)`,
`check_token_rate_limits`, and `check_api_key_usage`. See [[rate-and-usage-limits]].

### Environment configuration (`backend/onyx/configs/chat_configs.py` unless noted)

| Variable | Default | Effect |
|---|---|---|
| `MAX_LLM_CYCLES` | 6 | Max LLM cycles in one turn. The last cycle turns tools off and forces an answer. |
| `CHAT_HEARTBEAT_INTERVAL_S` | 15 | SSE keepalive cadence, live and resumed. |
| `CHAT_RESUME_POLL_INTERVAL_S` | 0.2 | Poll cadence for `resume_chat_stream`. |
| `CHAT_STREAM_BUFFER_TTL_S` | 3600 | Durable buffer lifetime. |
| `CHAT_STREAM_BUFFER_DONE_TTL_S` | 600 | Buffer lifetime after the turn completes. |
| `CHAT_STREAM_BUFFER_MAX_BYTES` | 16 MiB | Buffer cap. |
| `HARD_DELETE_CHATS` |  | Session delete is a hard delete. |
| `GEN_AI_INPUT_TOKEN_SAFETY_MARGIN` | 0.05 | (`configs/model_configs.py`) Shrinks the usable input window. |
| `GEN_AI_NUM_RESERVED_OUTPUT_TOKENS` | 1024 | (`configs/model_configs.py`) Output allowance. |
| `DEV_MODE` |  | Includes stack traces in `StreamingError`. |

Admin-configured, not env: workspace setting `auto_detect_search_filters`
(`load_settings()`).

---

## 3. Data model

This component writes, but does not own, the chat tables. [[chat-persistence]] owns
them. What matters here:

- `ChatSession`: the conversation.
- `ChatMessage`: one row per user message and one per assistant message **per model**.
  Assistant rows are **reserved before streaming begins** so the frontend has an ID
  immediately.
- `ToolCall`: one row per tool invocation, linkable to a parent `ToolCall` for
  sub-agent nesting.
- `SearchDoc`: the documents a turn surfaced, linked to the tool call that found them.

Redis / cache keys:

| Key | TTL | Owner | Meaning |
|---|---|---|---|
| `chatsessionstop_fence_{session_id}_{stream_id}` | 10 min | `stop_signal_checker.py` | User pressed stop for that stream. A later request in the same session is not affected. |
| `chatprocessing_fence_{session_id}` | 30 min | `chat_processing_checker.py` | A turn is live; holds the stream ID of the active stream buffer (0 means unknown). |

Both are tenant-scoped through `CacheBackend`.

---

## 4. How it works

### 4.1 The call chain

```text
handle_send_chat_message                     server/query_and_chat/chat_backend.py
  -> _stream_chat_turn                      chat/process_message.py
  -> prepare_chat_turn                      chat/prepare.py
  -> ChatTurnExecution                      chat/execution.py
       -> ChatAgent                         chat/agent.py
            -> SDK model/tool steps         agents/runtime.py, agents/tool_execution.py
       -> ResponsePresenter                 chat/presentation.py
            -> browser packets              chat/renderer.py
       -> ChatResponsePersistence           chat/persistence.py
            -> history store                chat/history_store.py
            -> save_chat_turn               db/chat_response.py
```


The application and SDK divide the work as follows:

1. `backend/onyx/chat/prepare.py:prepare_chat_turn` validates requests and resolves
   history, tools, files, and models. `backend/onyx/chat/execution.py:ChatTurnExecution`
   coordinates workers, ownership checks, and stream publication.
2. `backend/onyx/agents/runtime.py` runs model and tool steps. `ChatAgent` supplies
   chat prompts and tool context. Its final step disables further tool calls.
3. `backend/onyx/llm/multi_llm.py` converts provider streams into generation events.
   `backend/onyx/chat/renderer.py` converts recorded events into browser packets.
4. `backend/onyx/chat/persistence.py:ChatResponsePersistence` saves completed responses
   through the configured history store.

### 4.2 Setup: `prepare_chat_turn`

Returns a frozen `ChatTurnSetup` (`backend/onyx/chat/models.py`). It is frozen and detached from
the DB session on purpose: worker threads must not hold ORM objects.

Preparation resolves:
- the session, the persona, and the LLM(s) via `get_llm_for_persona`
- combined project and agent instructions via `get_custom_agent_prompt(persona, chat_session)`;
  agent instructions take precedence on conflicts ([[projects]] §4.5)
- user memories via `get_memories`
- the combined project and agent file selection via `resolve_context_user_files`,
  reused by prompt loading and tools; `extract_context_files` applies the shared budget
- reserved token count via `calculate_reserved_tokens` (`chat/prompt_utils.py`)
- the user message row via `create_new_chat_message`
- assistant message IDs via `reserve_chat_response_ids`

### 4.3 Execution

`ChatTurnExecution` starts one synchronous response worker per selected model with
`start_thread_future`. This utility copies tenant and tracing context into the thread.
Each worker constructs its feature agent and calls `Agent.start(background=False)`.
Child agents and parallel tools use additional workers when needed.

All responses share one `ChatDelivery`. Its event dispatcher renders SDK events,
publishes browser packets, and writes the replay buffer. `Emitter` stamps each
response's model index. Closing the browser reader does not stop execution.

Each worker passes a lazy SEARCH_SELECTION client factory into `construct_tools`.
Search keeps the answer client for rewrites and filters, resolving the separate
client only for section selection and relevance classification after retrieval.
The factory captures the session's pinned incognito policy and request headers.
An unset SEARCH_SELECTION returns that same answer client and never falls back
to the independent CHAT_NAMING designation.

The chat control thread polls Stop and ownership state. It observes response worker
and persistence outcomes, then releases session admission after work and delivery finish.
A failed response reports its error without discarding other models' output.

See [[file-store-and-user-files]] §4.4 for project/persona file-loading
session boundaries.

### 4.4 Context assembly per cycle

`prepare_prompt` (`backend/onyx/chat/prompt_utils.py`) produces this order:

```
[system] [history before last user] [custom agent prompt] [context/project files]
[last user message] [tool calls and responses] [file notices] [reminder]
```

The reasoning behind each position is in `backend/onyx/chat/README.md` and in
[[context-assembly]]. Two rules worth internalising:

- The custom agent prompt is a **user message**, not part of the system prompt, and
  it **moves** to sit just above the newest user message each turn. If
  `persona.replace_base_system_prompt` is set, agent instructions form the system
  prompt; project instructions remain a separate moving user message.
- The reminder is always **last**. Models attend hardest to the final tokens. The
  citation reminder lives here, and it stays until the turn ends.

Token-budget truncation drops the oldest history first and emits a "forgotten files"
notice so the model knows content was removed rather than silently losing it.

Before each inference, `chat/prompt_formatting.py:prepare_model_messages` resolves
image support and the provider image cap. It uses `LLMConfig.supports_images`
when set, otherwise the catalog lookup. Text-only history skips this check.
Prepared messages retain token estimates for `llm/model_request.py:cache_split_stats`,
without repeating image decisions. Non-vision models receive text markers.
Dropped images contribute no prefix tokens. History message counts describe the
prepared request, including image-drop notices.

### 4.5 Persistence

`backend/onyx/chat/persistence.py:ChatResponsePersistence` receives terminal SDK
runs and projects their recorded state into chat responses. It reports save
success or failure to the turn coordinator.

`backend/onyx/chat/history_store.py` selects Postgres or temporary Redis storage
according to the session's content policy. Postgres writes use a fresh session;
content-free incognito saves retain replay data in Redis instead.

Compaction checkpoints are part of SDK execution state. Saving the response
preserves the checkpoint needed to continue the selected message branch.

### 4.6 Stop, resume, heartbeat

- Stop sets a fence for the active stream ID. Later turns use a different fence.
- The chat control thread checks Stop and run ownership every 250 ms between calls.
  Slow cache calls can delay the next check.
- Cancellation signals reach root runs, children, and tool work. Accepted partial
  output is saved; late events cannot append new response output.
- The browser shows cancellation in progress while active work drains. Session
  admission remains held until workers, persistence, and delivery finish.
- Processing status refreshes every 60 seconds. Resume uses the replay buffer and
  processing status to distinguish active streams from completed work.
- Heartbeats go out every `CHAT_HEARTBEAT_INTERVAL_S` on live and resumed streams.

---

## 5. Contracts and invariants

Break one of these and the symptom appears somewhere far away. Check each one
whenever you touch this component.

1. **Persistence belongs to the chat application.**
   `backend/onyx/chat/persistence.py:ChatResponsePersistence` owns response saves.
   The generic SDK and provider adapter do not write chat database rows.
   MemoryTool owns memory side effects, subject to the incognito guard.

2. **`ChatTurnSetup` is frozen and detached.** Preparation captures configuration
   and history before closing its DB session. Workers must not lazy-load that ORM state.
3. **Worker threads get a copied `contextvars.Context`.** Tenant ID and tracing live
   there. A new thread without the copy silently writes to the wrong tenant.
4. **Browser rendering must not drive execution.** SDK state owns model and tool
   progress. The presenter and renderer consume that state to produce packets.
5. **Root finalization uses `ChatResponsePersistence`.** It reports one final
   outcome. Progressive execution saves and checkpoints belong to `ChatRunStore`.
6. **The assistant message row exists before the first token.** IDs are reserved up
   front. Do not move reservation later.
7. **Every packet carries a `Placement`.** `model_index` is stamped by the `Emitter`,
   never by the producer. See [[streaming-protocol]].
8. **Cancelled execution cannot publish late response output.** The runtime
   fences accepted state, and `ChatTurnExecution._publish` checks cancellation.
9. **The reminder message stays last.** Anything appended after it silently degrades
   citation reliability.
10. **Multi-model requires streaming** and is capped at 2-3 models. Deep research
    cannot run multi-model.
11. **Incognito persistence depends on the pinned record mode.**
    `backend/onyx/db/enums.py:record_mode_persists_content` decides. A `FULL_HISTORY`
    session writes conversation content to `chat_message` like an ordinary chat.
    A `USAGE_ONLY` session passes `persist_content=False`, which blanks the row.
    Its content goes to `append_incognito_message`. Any new field written during a
    turn needs a decision for each mode.

---

## 6. Relationships

**Depends on**
- [[context-assembly]]: builds the prompt, the file messages, and the reminder.
- [[tools-framework]]: `construct_tools` supplies the tool set; the loop executes them.
- [[llm-providers]]: `get_llm_for_persona` resolves provider, model, and overrides.
- [[streaming-protocol]]: the packet vocabulary this loop emits.
- [[chat-persistence]]: the tables `save_chat_turn` writes.
- [[citations]]: the citation processor runs inside the loop.
- [[agents-personas]]: persona fields change prompt, tools, and document scope.
- [[rate-and-usage-limits]]: gates the endpoint.
- [[access-control]]: the acting user's ACLs flow into every search tool call.

**Depended on by**
- [[chat-frontend]]: consumes the packet stream.
- [[slack-bot]], [[discord-bot]], [[onyx-api]], [[mcp-server]], [[mobile-app]]: all of
  these drive a turn through this loop. A change here reaches all of them.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds or renames a streaming packet | [[streaming-protocol]] and the frontend parser and renderer in [[chat-frontend]]; then [[mobile-app]], which parses the same stream |
| changes the order or content of assembled context | [[context-assembly]]; re-read the rationale in `chat/README.md` before moving anything; citation quality is the usual casualty |
| changes SDK output or its chat projection | `ChatResponsePersistence`, `save_chat_turn`, non-streaming responses, and incognito storage |
| adds a new way for a turn to end | verify `ChatResponsePersistence` reports a final outcome for stop, startup failure, and runtime failure |
| touches thread creation or the queue | context propagation, cancellation fences, delivery drain, and the control poll |
| changes `save_chat_turn` or the tables | [[chat-persistence]]; the session-replay path `GET /chat/get-chat-session/{id}` must render the same packets the live stream produced |
| changes the tool set or tool results | [[tools-framework]] and every tool implementation; SDK history retains results; legacy history can use placeholders |
| changes prompts | run an eval; see [[observability]] for tracing, and `backend/onyx/evals/` |
| changes anything in this component at all | the Slack and Discord bots, the public API, and MCP all share this loop |

---

## 8. How to verify a change

### Coverage by tier

Choose the lowest tier that can observe the failure. Keep a higher-tier test when
it checks a separate contract between components.

| Contract | Tier and examples | What the test must observe |
| --- | --- | --- |
| Agent state, cancellation, deadlines, compaction budgets | Unit: `backend/tests/unit/onyx/agents`, `backend/tests/unit/onyx/chat`, `backend/tests/unit/onyx/llm` | Actual runtime behavior with controlled providers and failures. |
| Provider request and response compatibility | External dependency: `backend/tests/external_dependency_unit/llm/mock_llm_server` | The real LiteLLM adapter and an HTTP provider, including partial output. |
| Saved response, tools, branches, incognito, restoration | External dependency: `backend/tests/external_dependency_unit/db/test_response_storage.py`, `backend/tests/external_dependency_unit/chat` | Real database writes and fresh reads; expire ORM state before checking reload behavior. |
| Compaction through chat preparation and storage | External dependency: `backend/tests/external_dependency_unit/answer/test_chat_compaction.py` | Summary reuse, unchanged original history, and the selected branch in subsequent model requests. |
| Resume API | Integration: `backend/tests/integration/tests/streaming_endpoints/test_resume_stream.py` | Real sockets; buffered output must arrive before the provider finishes, and match saved output. |
| Reload, network recovery, stop, and rendered history | Playwright: `web/tests/e2e/chat/stream_recovery.spec.ts` | The real chat API and browser, with only the external model scripted. |

`backend/onyx/chat/execution.py` wakes on worker, persistence, idle, and delivery
completion. Its timed wait still polls stop requests and ownership. Completion
tests must hold a save open, verify admission remains held, then finish without
waiting for that poll interval.

`backend/onyx/chat/prepare.py` skips redundant history-store calls for content
already loaded and saved in PostgreSQL. Ownership checks remain before writes
and around slow file loading. An expired lease must prevent the next message write.

Do not use FastAPI TestClient's buffered response to prove a mid-stream disconnect.
Do not use browser packet fixtures to prove backend streaming or persistence.
Packet fixtures remain useful for isolated rendering cases.

Before deleting an older test, compare its inputs, failure cases, and assertions.
A matching name or overlapping code coverage does not establish duplication.
Assert expected content or state, not only equality between two implementation paths.

Scripted model tests establish orchestration behavior, not answer quality. Real
provider tests, including `backend/tests/external_dependency_unit/llm/test_agent_compaction.py`,
check separate contracts and need their declared credentials. Screenshot reports
also need review; default screenshot capture does not fail on visual differences.

### Tests

```bash
# Integration tests are the preferred level for this component.
cd backend && uv run pytest tests/integration -k chat
# Unit tests for the loop internals
cd backend && uv run pytest tests/unit -k "chat or llm_loop or prompt"
# Frontend end-to-end
cd web && bun run playwright chat_message_rendering
```

See `backend/AGENTS.md` for the authoritative commands and required env.

`INTEGRATION_TESTS_MODE=true` makes the loop emit `ToolCallDebug` packets, so a test
can assert which tools ran. The `mock_llm_response` hook no longer exists.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000`, sign in as `admin_user@example.com` / `TestPassword123!`.
3. Send a message that forces a search, for example "what does our onboarding doc say".
4. Watch for, in order: reasoning, a search tool block with queries and documents, the
   streamed answer, and numbered citations that resolve to real documents.
5. Press stop mid-answer. The partial answer must persist after a page reload.
6. Reload the page mid-answer without stopping. The answer must resume, not restart.
7. Reopen the session from the sidebar. The replayed view must match what you saw live.

Drive the browser with `claude-in-chrome` against the user's real Chrome rather than
launching Playwright ad hoc.

### What "working" looks like

- No orphaned assistant message rows with empty content and no error.
- One final outcome per model, with progressive execution saves as needed.
- Stop shows cancellation until active work drains; admission stays held during that wait.
- Replay of a saved session is visually identical to the live stream.

---

## 9. Footguns

- **SDK responses retain completed tool results.** Later requests can use them until
  compaction replaces older context. Legacy responses can use placeholders.

- **Search tool arguments in history are the LLM's original arguments, not the
  expanded queries.** Query expansion happens inside `SearchTool.run`. It emits
  the expanded set in `SearchToolQueriesDelta` and does not change
  `tool_call.tool_args`.
- **`turn_index` is not a backend turn.** It is a frontend rendering block. One LLM
  inference that produces reasoning plus a tool call is one backend step but two
  frontend turns.
- **Message types have different owners.** `ChatMessage` is a database row.
  SDK `Message` holds model conversation content. Provider `ChatCompletionMessage`
  is a wire format; browser `Packet` is a display format.

- **Moving a sentence inside the system prompt changes behaviour a lot.** The team
  measured instruction-follow rates swinging from roughly 30% to 90% by moving the
  same sentence into the right section. Do not reorganise prompt text for tidiness.
- **File extraction uses the smallest selected context window.** Each SDK run
  then fits and compacts its prompt against its own model context budget.
- **Compaction belongs to each SDK run.** The saved summary is tied to its response
  branch. A later turn must use the summary from its selected ancestry.
- **Anonymous access is allowed** on several of these endpoints
  (`allow_anonymous=True`). A change that assumes a logged-in user will break the
  anonymous flow.

# Core Chat Loop

> The turn engine. It takes one user message, runs one LLM loop per selected
> model in worker threads, streams packets through one writer thread, and saves
> each model's result exactly once.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

- **An end user** sends a message. The assistant can think, run tools (search,
  web, code, images, custom tools) for several cycles, and then streams an answer
  with citations. On the last allowed cycle the model must answer without tools.
- **Stop.** The user presses stop. The partial answer stays, with "Generation was
  stopped by the user." after it. A reload shows the same saved text.
- **Leaving is not stopping.** If the user closes the tab, navigates away or loses
  the network, the run continues on the server and is saved. When the user returns
  while the run is live, the client resumes the stream ([[streaming-protocol]]).
  After the run ends, the user sees the saved message.
- **Compare models.** A user can send one message to two or three models. The
  answers stream side by side, and the user marks one as preferred. A failure in
  one model shows an error for that model only. The others finish.
- **Deep research** runs with one model only, and not in a project chat. The
  backend refuses a multi-model deep research request, and a deep research turn
  in a project session ends with an error.
- **When the turn fails** before the run starts (no access to a document set, a
  bad model setting, a Query Processing hook that rejects the message), the user
  sees one error and no answer. When a model fails during the run, its reserved
  message row stores the error text. An incognito session that does not keep
  content stores a generic error text instead, because provider errors can echo
  the prompt.
- **An API caller** gets NDJSON when `stream=true` and one `ChatFullResponse`
  when `stream=false`. A multi-model request without streaming is rejected.
- **Bots.** The Slack bot runs the same turn in-process
  (`onyxbot/slack/handlers/handle_regular_answer.py`). The Discord bot calls the
  HTTP endpoint (`onyxbot/discord/api_client.py`). A change here reaches both.

---

## Scope

This component owns the turn: request validation and setup, row reservation,
the worker and writer threads, the LLM cycle loop and the single inference step,
the stop and processing fences, the turn endpoints, and the one save per model.
It shares the emitter and the stream buffer with [[streaming-protocol]].

Neighbours own the rest:
- [[context-assembly]]: what goes into each prompt, in what order, the token
  budget and compression. This component calls `construct_message_history`
  each cycle and decides when compression runs.
- [[streaming-protocol]]: the packet types, `Placement`, the wire format and the
  resume buffer.
- [[chat-persistence]]: the tables, `chat/save_chat.py:save_chat_turn` and how
  saved history is rebuilt.
- [[tools-framework]]: tool construction and `run_tool_calls`.
- [[citations]]: the citation processor that runs inside each step.
- [[agent-runtime]]: the `onyx/agents` package and the chat modules that are not
  wired into this loop. Read its status table before you edit a chat module that
  this document does not name.

---

## Architecture

```
request thread                 worker thread (one per model)        writer thread
_stream_chat_turn              _run_model                           _drain_to_completion
  build_chat_turn   (DB)         construct_tools                      merged_queue.get(50 ms)
  -> ChatTurnSetup               run_llm_loop                         -> _publish: stream buffer + tee
  _run_models ---- starts ---->    or run_deep_research_llm_loop      on idle: flush buffer, check stop
  _read_stream <-- tee --------    Emitter.emit -> merged_queue       finally: mark_done,
  (yields to HTTP, heartbeats)   finally: _persist_model_outcome        _run_post_steps (fence reset)
```

**Three layers.** `chat/process_message.py` validates, loads history, reserves
rows, starts threads and saves. It never calls an LLM.
`chat/llm_loop.py:run_llm_loop` runs the cycles: build context, call
`run_llm_step`, run tools, repeat until the model answers or `MAX_LLM_CYCLES` is
reached. `chat/llm_step.py:run_llm_step` runs one inference and splits the
provider stream into reasoning, answer and tool-call packets.
`backend/onyx/chat/README.md` gives the design reasons.

**Setup.** `chat/process_message.py:build_chat_turn` is a generator. It yields
the IDs the client needs first (`CreateChatSessionID`, `MessageResponseIDInfo`),
then returns a frozen `ChatTurnSetup`. It runs the Query Processing hook before
it saves the user message, only for a new, non-blank message, and only when the
incognito mode allows hooks (`IncognitoRecordMode.fires_hooks`), because the hook
sends the query out ([[hooks]]). A rejection raises `QUERY_REJECTED`. Then it
saves the user message, loads the branch summary, resolves the custom agent
prompt and memories, reserves tokens, extracts project files, and reserves one
assistant row per model. The stream ID is the reserved assistant message ID, or
the user message ID for a multi-model turn. Then it sets the processing fence and
commits.

**Threads.** `_run_models` starts one worker per model and one writer. The writer
is the run's owner. It consumes the queue to the end, whether or not a client
reads. The reader generator only tails a tee queue. When the HTTP client
disconnects, the reader stops and the writer continues.

**Other turn shapes.** Deep research with one model replaces `run_llm_loop` with
`deep_research/dr_loop.py:run_deep_research_llm_loop` in the same worker. The
research agent (`tools/fake_tools/research_agent.py`, which deep research calls)
and the coding agent tool (`tools/fake_tools/coding_agent.py`) run their own
sub-loops inside a tool call. All of them reuse `construct_message_history` and
the step functions in `chat/llm_step.py`.

**Code interpreter state.** `run_llm_loop` reads the `run_python` result to add
the file reminder, and stages search-hit source files for later Python calls
([[code-execution]]).

**Persistence.** Every exit path calls `_persist_model_outcome`: worker end,
stop, normal drain end and post-steps. A lock and a per-model `persisted` flag
make it run once. It calls `llm_loop_completion_handle` (success or stop) or
`_save_errored_message`. The completion handle snapshots the state container,
opens a short DB session, re-reads the reserved row, and calls `save_chat_turn`.
Then, for the first model to claim it, it checks whether to compress history
([[context-assembly]]).

---

## Contracts and traps

1. `only-process-message-saves` **Only `chat/process_message.py` saves the
   turn.** `chat/llm_loop.py` and `chat/llm_step.py` accumulate state and do not write
   messages, tool calls or search docs. The one exception: `run_llm_loop` writes
   memories through `db/memory.py:add_memory` and `update_memory_at_index` when
   the memory tool runs. In any incognito mode it refuses the write and tells the
   model so.
2. `turn-setup-detached-rows` **`ChatTurnSetup` carries detached ORM rows.**
   `persona` and `reserved_messages` are detached after setup. Workers may read
   eager-loaded columns only. A lazy relationship raises `DetachedInstanceError`
   under load. Closures stored on the setup bind IDs, never rows. See the class
   docstring in `chat/chat_state.py:ChatTurnSetup`.
3. `threads-copy-context` **Each worker and the writer run in a copied
   `contextvars.Context`.** The copy carries the tenant ID, tracing and the
   incognito mode. A thread without it writes to the wrong tenant or loses its
   trace ([[multi-tenancy#threads-copy-context]]).
4. `no-db-session-across-stream` **Workers hold no DB session across the LLM
   stream.** Each step opens short sessions. Cloud infrastructure drops idle
   connections during long runs.
5. `state-container-accumulates` **The state container and the emitter
   accumulate. They never drive logic.** Do not branch on their contents in
   `llm_loop` or `llm_step` (`chat/README.md`). The research agent is an
   exception: it reads the search docs of earlier tool calls through
   `get_tool_calls` to build its URL snippet map
   (`tools/fake_tools/research_agent.py`). Read the container through its locked
   getters, because the stop path reads it while a worker still writes.
6. `persist-once-per-model` **One save attempt per model.** A new way to end a
   turn must call `chat/process_message.py:_persist_model_outcome`. The
   `persisted` flag is set before the save runs. If the save raises, later paths do nothing and the reserved row
   keeps its placeholder.
7. `reserve-before-first-token` **The assistant row exists before the first
   token.** IDs are reserved and yielded in setup. The stop endpoint, the resume
   buffer and the client all key on them. Do not move reservation later.
8. `disconnect-is-not-stop` **Disconnect is not stop.** Only the stop fence
   (`chat/stop_signal_checker.py:request_stop`) makes the writer save partial
   output, publish `OverallStop(stop_reason="user_cancelled")` and set
   `drain_done`. `drain_done` turns `chat/emitter.py:Emitter.emit` into a
   no-op. It does not interrupt a worker, which runs until its LLM or tool call returns. Do not
   add a path that puts packets on `merged_queue` without `Emitter.emit`: after
   a stop or a writer crash nothing consumes the queue, so it grows. The stop
   fence is per stream ID, so a late stop cannot cancel the next message. The
   saved partial text ends with the stop sentence from
   `chat/process_message.py:llm_loop_completion_handle`, which replay matches
   by text ([[chat-persistence]]).
9. `processing-fence` **The processing fence is a status marker that the writer
   owns, not a lock.** Once the run starts, the writer re-arms the fence every
   60 s, because a run can outlive the 30-minute TTL and a lapsed fence reads as
   a dead writer to resume readers. It clears the fence in
   `chat/process_message.py:_run_post_steps`. Before the run starts,
   `chat/process_message.py:_stream_chat_turn` clears it on failure. The backend
   does not refuse a second send on the same session while one runs, so code
   that assumes one live turn per session is wrong (`chat/incognito_context.py` uses a
   compare-and-set for this reason).
10. `stream-closes-after-compression` **The HTTP stream closes after
    compression.** The worker saves and may compress history before it posts
    `_MODEL_DONE`, so the summary LLM call keeps the stream open after the
    answer's `OverallStop`. Only one model claims compression, measured against
    the smallest context window of the turn's models.
11. `shared-loop-pieces` **Shared loop pieces have several callers.** A change to
    the step functions in `chat/llm_step.py` or to `Placement` handling also
    reaches deep research, the research agent and the coding agent.
    `chat/llm_loop.py:construct_message_history` has the same callers
    ([[context-assembly#history-builder-callers]]).
12. `three-message-types` **Three message types exist.** `ChatMessage` is the DB
    row: convert it early. `chat/models.py:ChatMessageSimple` is the in-loop
    model and the one to extend. `llm/model_request.py:ChatCompletionMessage` is
    the minimal LLM-facing form.
13. `anonymous-send` **Anonymous users can send.**
    `server/query_and_chat/chat_backend.py:handle_send_chat_message` uses
    `require_permission(Permission.WRITE_CHAT, allow_anonymous=True)`. Code that
    assumes a real user breaks public agents.
14. `stopping-tools` **Some tools end the tool phase.** After a tool in
    `tools/built_in_tools.py:STOPPING_TOOLS_NAMES` (image generation) runs, the
    next cycle has no tools, the same as the last cycle.

---

## Decisions

- **A writer thread separate from the reader.** The run must not depend on the
  HTTP connection. The writer always reaches the end, so the answer is saved and
  the resume buffer is complete after a dropped connection.
- **Single-model and multi-model share one path.** A single-model turn is the
  `N=1` case of `_run_models`. Every packet from a worker carries a
  `model_index`, `0` for one model.

---

## Known issues

- **A forced tool that construction did not build fails the whole message.**
  `chat/process_message.py:build_chat_turn` clears `forced_tool_id` only when it
  names the search tool and search is disabled, or when
  `is_tool_available_for_persona` excludes the tool. A tool that `is_available`
  or `allowed_tool_ids` hides still fails the message with "Forced tool ... not
  found in tools" (`_run_models`). See the "Force a tool call" recipe in [[tools-framework]].
- **Stop latency depends on idle time.** The writer checks the stop fence only
  when `merged_queue.get` times out after 50 ms with no packet. A steady packet
  stream can delay the stop.
- **`chat/README.md` describes a disconnect as a stop** in its "Stopping
  Generation" section. The code does not ([[#disconnect-is-not-stop]]).
- **The chat turn repeats a document-set access check** that the search tool
  also makes ([[internal-search#document-set-access-checks]]).

---

## Dependencies

- [[context-assembly]]: prompt content, message order, token budget, compression.
- [[tools-framework]]: `construct_tools` and `run_tool_calls`.
- [[llm-providers]]: `get_llm_for_persona` resolves provider, model and overrides.
- [[streaming-protocol]]: the packet vocabulary and the resume buffer.
- [[chat-persistence]]: the tables `save_chat_turn` writes and history loading.
- [[citations]]: one `DynamicCitationProcessor` per loop.
- [[agents-personas]]: agent fields change the prompt and the tools.
- [[projects]]: project fields change the prompt and the file scope.
- [[hooks]]: the Query Processing hook in setup.
- [[rate-and-usage-limits]]: `check_token_rate_limits` and `check_api_key_usage`
  at the endpoint, and the LLM cost check in setup.
- [[multi-tenancy]]: tenant context in threads.

---

## Recipes

- `new-turn-exit` **A new way for a turn to end.** Copy the stop path in `_drain_to_completion`,
  which calls `_persist_model_outcome` with `_PersistContext.STOP_BUTTON`. List
  the current exit paths with
  `git grep -n "_PersistContext\." backend/onyx/chat/process_message.py`. Check
  that the stop path and the error path still save once.
- `turn-state-field` **A field on the turn state.** Copy a locked getter such as
  `ChatStateContainer.get_answer_tokens` (list them with
  `git grep -n "def get_" backend/onyx/chat/chat_state.py`). Read the field in
  `llm_loop_completion_handle`, `_save_errored_message` and `gather_stream_full`
  (non-streaming API). Decide what each incognito mode stores
  ([[chat-persistence#incognito-decision-per-field]]).
- `in-process-caller` **A new in-process caller.** Copy the Slack bot: it calls
  `handle_stream_message_objects` and consumes it with `gather_stream`. List the
  callers with `git grep -n "handle_stream_message_objects(" backend`. Do not
  call `run_llm_loop` directly: setup, fences and saving live above it.
- `investigate-stuck-turn` **Investigate a turn that does not end, or a stop
  that does nothing.** In
  `backend/log/api_server_debug.log`, find "chat stream reader detached; writer
  continues" (a disconnect, not a stop), "chat stream writer crashed", and
  "completion failed for model". The processing fence key is
  `chatprocessing_fence_<session_id>` and the stop key is
  `chatsessionstop_fence_<session_id>_<stream_id>`, both in the tenant's cache.
  A stop key for an older stream ID does nothing ([[#disconnect-is-not-stop]]).

---

## Verification

- Unit: `backend/tests/unit/onyx/chat/` covers the loop, the step, cancellation,
  multi-model streaming and `gather_stream`.
- Integration: `backend/tests/integration/tests/streaming_endpoints/`.
  `INTEGRATION_TESTS_MODE=true` makes the loop emit `ToolCallDebug` packets, so a
  test can assert which tools ran.
- By hand: send a message that forces a search. Press stop during the answer and
  reload: the partial answer must stay. Send again, close the tab during the
  answer, and reopen the session: the answer must resume or show as saved. Run a
  multi-model turn and confirm that each column ends with its own answer or error.

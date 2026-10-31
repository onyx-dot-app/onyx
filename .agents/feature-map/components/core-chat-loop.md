# Core Chat Loop

> The turn engine. It takes one user message, claims the session, runs one
> shared-runtime agent per selected model in its own thread, delivers packets
> through one turn-level delivery path, and reports one final save outcome per
> model.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## User experience

- **An end user** sends a message. The assistant can think, run tools (search,
  web, code, images, custom tools) for several steps, and then streams an answer
  with citations. On the last allowed step (`MAX_LLM_CYCLES`, default 6) the
  model must answer without tools.
- **One message at a time.** While a turn runs, the session is busy. The client
  waits until the session is idle before it sends again. The backend refuses a
  second streaming send on the same session with a `StreamingError` packet whose
  `error_code` is `CONFLICT`, not with an HTTP status. A `stream=false` send
  fails with "Message ID is required" ([[#session-admission]]).
- **Stop.** The user presses stop. The input shows that the turn is stopping
  until active model, tool and save work drains. The partial answer stays, with
  "Generation was stopped by the user." after it. A reload shows the same saved
  text. Anonymous users cannot stop ([[#anonymous-send]]).
- **Leaving is not stopping.** If the user closes the tab, navigates away or loses
  the network, the run continues on the server and is saved. When the user returns
  while the run is live, the client resumes the stream ([[streaming-protocol]]).
  After the run ends, the user sees the saved message.
- **Compare models.** A user can send one message to two or three models. The
  answers stream side by side, and the user marks one as preferred. A model
  error shows for that model only, and the others finish. A response worker that
  crashes or ends without an outcome cancels all models
  ([[#persist-once-per-model]]).
- **Deep research** runs with one model only, not in a project chat, and only
  with a model that accepts at least 50,000 input tokens. The backend refuses a
  multi-model deep research request. The other cases end the turn with an error.
- **When the turn fails** in setup (no access to a document set, a bad model
  setting, a Query Processing hook that rejects the message), the user sees one
  error, and no response row is reserved. A failure after reservation is saved
  per model: a launch failure adds one `CHAT_STARTUP_ERROR` packet, then each
  model streams and saves its own error. Agent construction errors (forced tool
  missing, deep research in a project or with a small model) and failures during
  the run are also saved on that model's reserved row. An incognito session
  that does not keep content stores a generic error text instead, because
  provider errors can echo the prompt. When a save fails or takes longer than
  its wait bound, the stream shows a separate `RESPONSE_SAVE_ERROR`.
- **An API caller** gets NDJSON when `stream=true` and one `ChatFullResponse`
  when `stream=false`. A multi-model request without streaming is rejected.
- **Bots.** The Slack bot runs the same turn in-process
  (`onyxbot/slack/handlers/handle_regular_answer.py`). The Discord bot calls the
  HTTP endpoint (`onyxbot/discord/api_client.py`). A change here reaches both.

---

## Scope

This component owns the turn: request validation and setup, session admission,
row reservation, the control and response threads, the chat agent's step
policy, Stop, the turn endpoints, and the hand-off of each finished run to
persistence. It shares the emitter and the stream buffer with
[[streaming-protocol]].

Neighbours own the rest:
- [[agent-runtime]]: the step loop, tool scheduling, child agents, compaction
  and the coordination interfaces that this component's adapters implement.
- [[context-assembly]]: what goes into each prompt, in what order, and the token
  budget. This component's agent calls the prompt builders on each step.
- [[streaming-protocol]]: the packet types, `Placement`, the wire format and the
  resume buffer.
- [[chat-persistence]]: the tables, the history stores, the response writer and
  how saved history is rebuilt.
- [[tools-framework]]: tool construction and the chat `Tool` interface.
- [[citations]]: the citation processor that each chat agent owns.

---

## Architecture

```
request thread                  control thread (one per turn)        response thread (one per model)
_stream_chat_turn               ChatTurnExecution.run                ChatTurnExecution._run_response
  prepare_chat_turn (DB, files)   starts one response thread           create_chat_agent: construct_tools,
  -> ChatTurnSetup                  per model                            ChatAgent or DeepResearchAgent
  start_chat_turn                 wake >= every 250 ms: Stop;          load_chat_branch (session check)
    clear_stop, admission.publish   admission every 5 s; owner         ChatRunStore (content kept) or
    publish IDs to ChatDelivery     leases every 10 s (content kept)     persistence view; register saved agents
    start control thread          _poll_responses: outcomes, idle      Agent.start(background=False)
  yield from ChatStream (reader)  all drained: OverallStop (user Stop)   ResponsePresenter -> Emitter -> ChatDelivery
                                    delivery.finish, admission.release RunStore.save -> ChatResponsePersistence
```

**Layers.** `chat/process_message.py` validates the request, loads history and
files, saves the user message and reserves the response rows. It never calls an
LLM. `chat/execution.py` launches and controls the turn. `chat/agent.py:ChatAgent`
is the chat feature on the shared runtime: it picks the tools and tool choice
for each step, builds the prompt, and folds tool results into its citation and
search state. `agents/runtime.py` runs the model and tool steps
([[agent-runtime]]). `chat/README.md` gives the design reasons.

**Setup.** `chat/process_message.py:prepare_chat_turn` claims the session
([[#session-admission]]) before it changes the message tree. It runs the Query
Processing hook before it saves the user message, only for a new, non-blank
message, and only when the incognito mode allows hooks
(`IncognitoRecordMode.fires_hooks`), because the hook sends the query out
([[hooks]]). A rejection raises `QUERY_REJECTED`. A regeneration reuses the saved
user message. Then setup resolves the custom agent prompt, memories, the
reserved tokens, the tool configuration and the branch summary, and copies the
history out of the ORM rows. It closes the DB session before slow file loading,
renews the admission between stages, and reserves one assistant row per model.
The stream ID is the reserved assistant message ID, or the user message ID for a
multi-model turn.

**Launch.** `chat/execution.py:start_chat_turn` clears any stop key for this
stream ID, then publishes the stream ID to the processing fence before the
client receives any ID, so Stop can target the turn. If either step fails, the
error becomes the startup error. Then it queues `CreateChatSessionID` (new
session only) and the message-ID packet on `ChatDelivery` and starts the
non-daemon control thread. The reader only tails `ChatDelivery.reader`. When the
HTTP client disconnects, the reader closes and the turn continues.

**Response threads.** Each response thread builds its tools and agent through
`chat/execution.py:create_chat_agent` and checks that the reserved row belongs
to this session's branch. When the session keeps content, it binds a
`chat/run_store.py:ChatRunStore` for run ownership, checkpoints and restoration.
A content-free session uses a coordinator view over `ChatResponsePersistence`
only, so it has no owner leases, and its run IDs are random. The thread
registers each saved child agent and the root, then runs
`Agent.start(background=False)` until the root completes or suspends. A
suspended root resumes later on a runtime thread, so the control loop waits for
a terminal, idle run, not for the response thread. Child agents and
parallel tools use more threads ([[agent-runtime]]). Deep research
(`deep_research/agent.py:DeepResearchAgent`) replaces `ChatAgent` for a
single-model deep research request. The research step and the coding agent tool
start child agents (`deep_research/research_agent.py:ResearchAgent`,
`coding_agent/agent.py:CodingAgent`) through the runtime's child API.

**Delivery.** All responses share one `chat/stream_buffer.py:ChatDelivery`. One
event-dispatch thread renders runtime events into packets
(`chat/presentation.py:ResponsePresenter`), and each response's `Emitter`
stamps its `model_index`. `ChatDelivery.publish` writes each packet to the live
reader and the replay buffer in the same order.

**Persistence.** When a run ends, the coordinator calls `RunStore.save`
([[agent-runtime]] lists the adapters). `chat/persistence.py:ChatResponsePersistence`
projects the root run snapshot into a response and saves it through the history
store ([[chat-persistence]]). Its `outcome` future resolves once: with a
`ChatResponseOutcome` whose status is `SAVED`, `FAILED` or `UNCONFIRMED`, or
with an exception for a worker or projection failure. For model 0 it is the
caller's `response_future`; `gather_stream_full` waits at most
`CHAT_RESPONSE_WAIT_TIMEOUT_S` and raises on an exception. That wait does not
cancel the turn. A normal end sends one `OverallStop(finished)` per model from
`ResponsePresenter`.

**Control.** `ChatTurnExecution.run` wakes on worker, save, idle and delivery
events, and at least every 250 ms. It checks Stop on each wake while the turn is
not cancelled, refreshes the admission lease every 5 s, and lets each
`ChatRunStore` renew its owner leases every 10 s. After
`CHAT_EXECUTION_TIMEOUT_S` it cancels the turn. When no response worker and no
owned run remains, it finishes delivery and then releases the admission. A child
run's owner lease also keeps the turn and its admission alive. API shutdown
waits up to `CHAT_EXECUTION_TIMEOUT_S` for `chat/execution.py:chat_turn_work`,
then closes database and tracing services; it does not cancel turns. The pod's
termination grace period is much shorter, so it ends running turns first
([[#crashed-turn]]).

---

## Contracts and traps

1. `only-chat-persistence-saves` **Only the chat persistence adapters write
   response rows.** `chat/persistence.py:ChatResponsePersistence` saves the root
   response through the history store. `chat/run_store.py:ChatRunStore` checks
   checkpoint ownership before that root save. It writes child-run rows and
   checkpoints directly through `db/chat_response.py` and `db/chat_checkpoint.py`,
   and reserves one response row for each child agent before it starts. The
   runtime, `ChatAgent` and the LLM adapter do not write chat rows. The memory
   tool writes memories as its own side effect and refuses in any incognito mode
   (`tools/tool_implementations/memory/memory_tool.py`).
2. `turn-setup-detached-rows` **`ChatTurnSetup` carries no ORM rows.**
   `chat/process_message.py:prepare_chat_turn` copies the persona into
   `PersonaPromptConfig` and saved responses into SDK messages
   (`chat/chat_utils.py:capture_chat_history`) while its DB session is open. A
   new setup field that holds a row raises `DetachedInstanceError` in a
   response thread under load.
3. `threads-copy-context` **Each response, control and child thread runs in a
   copied `contextvars.Context`.** `utils/threadpool_concurrency.py:start_thread_future`
   and `agents/runtime.py:Run._start` copy it. `start_chat_turn` sets the
   incognito mode and the content-free session ID before it starts threads, and
   restores the caller's values after. A thread without the copy writes to the
   wrong tenant or loses its trace ([[multi-tenancy#threads-copy-context]]).
4. `no-db-session-across-stream` **No thread holds a DB session across the LLM
   stream.** Tools open short sessions when they need one. Setup closes its
   session before file loading. Cloud infrastructure drops idle connections
   during long runs.
5. `presentation-does-not-drive-execution` **Rendering never drives execution.**
   Runtime state owns model and tool progress. `ResponsePresenter` and
   `chat/renderer.py:MessageRenderer` only read events and saved steps to make
   packets. Feature state that a later step needs lives on the agent, such as
   `ChatAgent.search_context` and its citation mapping, and is captured in
   `ChatFeatureState` for restoration. All tools in one step read the same
   `ChatAgent._tool_context`; citation and search state advance only in
   `ChatAgent._after_step`, after every call in the step finishes.
6. `persist-once-per-model` **One final outcome per model.** A new way to end a
   response must resolve `ChatResponsePersistence.outcome` through `save`,
   `save_failure`, `report_save_failure`, `report_worker_failure` or
   `expire_save` (`UNCONFIRMED` after 30 s). When a worker raises or ends
   without an outcome, `_poll_responses` reports that model's error and cancels
   the whole turn. The control loop does not finish until each outcome is set.
7. `reserve-before-first-token` **The assistant row exists before the first
   token.** `db/chat.py:reserve_chat_response_ids` runs in setup. The stop key,
   the resume buffer and the client key on it, and so does the root run ID when
   the session keeps content. Do not move reservation later.
8. `disconnect-is-not-stop` **Disconnect is not stop.** A disconnect never
   cancels. The turn's `CancellationSignal` is cancelled by the user's stop key
   (`chat/stop_signal_checker.py:request_stop`), the execution deadline, a lost
   admission, a control or response-polling failure, or a failed worker.
   `ChatRunStore.poll_control` cancels one run when its owner lease is lost or
   its `chat_response_stop:<id>` key is set. Cancellation reaches every run,
   child and tool, and `ChatTurnExecution._publish` drops packets after it. It
   does not interrupt a blocked provider read or a running tool; the turn keeps
   its admission until they return. The stop key is per stream ID, so a late
   stop cannot cancel the next message when the caller passes `stream_id`, as
   the web client does. Without `stream_id`, Stop targets the stream in flight
   at request time. Replay shows `user_cancelled` from the saved
   `RunStatus.CANCELLED`; only legacy rows match the stop sentence by text
   ([[chat-persistence]]).
9. `non-user-cancel` **Only a user Stop sends a final stop packet.** The control
   thread publishes `OverallStop(stop_reason="user_cancelled")` after all work
   drains only when the user's stop key cancelled the turn. The presenter's own
   `OverallStop` is dropped after any cancel, and `AgentCancelled` publishes no
   error. So a deadline, a lost admission or a control failure ends the live
   stream with no stop packet and no error, but the saved row still ends with
   "Generation was stopped by the user." and replays as `user_cancelled`. A new
   cancellation cause must decide what the user sees.
10. `stop-before-launch` **Stop does nothing before launch.** During setup the
    fence holds no stream ID, and launch clears any earlier stop key for the
    stream ID. A client must wait for the message-ID packet before it sends
    Stop, or abort the request itself, as `web/src/lib/chat/stopChatSession.ts`
    does.
11. `session-admission` **One turn owns a session at a time.**
    `chat/chat_processing_checker.py:ChatTurnAdmission` sets an owner key with a
    120 s lease during preparation and a 60 s lease after launch. The control
    thread renews it every 5 s and releases it only after workers, saves and
    delivery drain. A second send fails with `CONFLICT`. A process crash blocks
    new sends until the lease expires. A lost lease cancels the turn. The
    processing fence holds the stream ID for Stop and resume; "is processing"
    reads the owner key. Session details report `is_processing=True` when the
    cache lookup fails, so a cache outage never enables a second send
    (`server/query_and_chat/chat_backend.py:get_chat_session`). A pod on an older
    image does not check the owner key, so drain old generation owners, including
    in-process bots, before this runtime takes traffic (`chat/README.md`,
    "Deploying the shared runtime").
12. `crashed-turn` **A crashed turn is not recomputed.** `ChatRunStore.register`
    marks each run's row `RUNNING` and sets `chat_response_owner:<response_id>`
    (60 s TTL, renewed every 10 s). After a crash a root response stays `RUNNING`,
    and a reload replays it as is. Only a sub-agent response gets marked `ERROR`,
    when a later parent run reads it as a child through
    `ChatRunStore._load_status` ([[chat-persistence#save-chat-turn-one-commit]]). A row that was
    reserved but never registered keeps the placeholder text from
    `db/chat.py:reserve_chat_response_ids`. Stream resume does not restart work;
    only a suspended checkpoint (`ChatRunStore.handoff` and `resume`) restores it.
13. `shared-loop-pieces` **Shared runtime pieces have several callers.** A change
    to `agents/runtime.py`, to `chat/prompt_utils.py:prepare_prompt` or to
    `Placement` handling also reaches deep research, the research agent and the
    coding agent ([[context-assembly#history-builder-callers]]).
14. `three-message-types` **Three message types exist.** `ChatMessage` is the DB
    row; `ChatResponseItem` holds the steps of a saved response.
    `llm/models.py:Message` is the SDK conversation type that agents and
    history loading use, and the one to extend.
    `llm/model_request.py:ChatCompletionMessage` is the provider wire form.
15. `anonymous-send` **Anonymous users can send.**
    `server/query_and_chat/chat_backend.py:handle_send_chat_message` uses
    `require_permission(Permission.WRITE_CHAT, allow_anonymous=True)`, and so
    does stream resume. Code that assumes a real user breaks public agents.
    `stop_chat_session` does not allow anonymous users, so their Stop fails
    authentication (see Known issues).
16. `stopping-tools` **Some tools end the tool phase.** After a tool in
    `tools/built_in_tools.py:STOPPING_TOOLS_NAMES` (image generation) runs,
    `chat/agent.py:ChatAgent._prepare_step` offers no tools for the rest of the
    turn, the same as the last step.

---

## Decisions

- **A control thread separate from the reader.** The run must not depend on the
  HTTP connection. The control thread always reaches the end, so the answer is
  saved and the resume buffer is complete after a dropped connection, though a
  turn-level cancel can omit the stop packet ([[#non-user-cancel]]).
- **Single-model and multi-model share one path.** A single-model turn is the
  `N=1` case of `ChatTurnExecution`. Every packet from a response carries a
  `model_index`, `0` for one model.

---

## Known issues

- **A forced tool that construction did not build fails the whole message.**
  `chat/process_message.py:prepare_chat_turn` clears `forced_tool_id` only when
  it names the search tool and search is disabled, or when
  `is_tool_available_for_persona` excludes the tool. A tool that `is_available`
  or `allowed_tool_ids` hides fails every model with "Forced tool ... not found
  in tools" (`chat/execution.py:create_chat_agent`). See the "Force a tool call"
  recipe in [[tools-framework]].
- **Stop waits for blocked work.** Cancellation takes effect when a provider
  read returns or times out, and a running tool keeps going until it returns.
  Slow cache calls on the control thread also delay the next Stop check.
- **Anonymous users cannot stop.** `stop_chat_session` uses
  `require_permission(Permission.WRITE_CHAT)` without `allow_anonymous`, so an
  anonymous user can send and resume but not stop ([[#anonymous-send]]).
- **Deleting a session or ending an incognito session does not cancel a running
  turn.** The model runs to its end. The save then fails ("Chat response is
  unavailable" after a hard delete, "Incognito session ended" for incognito) or
  succeeds (soft delete).
- **The chat turn repeats a document-set access check** that the search tool
  also makes ([[internal-search#document-set-access-checks]]).

---

## Dependencies

- [[agent-runtime]]: `Agent`, `Run`, the coordinator and compaction.
- [[context-assembly]]: prompt content, message order, token budget.
- [[tools-framework]]: `construct_tools` and the chat `Tool` binding.
- [[llm-providers]]: `get_llm_for_persona` resolves provider, model and overrides.
- [[streaming-protocol]]: the packet vocabulary and the resume buffer.
- [[chat-persistence]]: the history stores and the response writer.
- [[citations]]: one `DynamicCitationProcessor` per chat agent.
- [[agents-personas]]: agent fields change the prompt and the tools.
- [[projects]]: project fields change the prompt and the file scope.
- [[hooks]]: the Query Processing hook in setup.
- [[rate-and-usage-limits]]: `check_token_rate_limits` and `check_api_key_usage`
  at the endpoint, and the LLM cost check in setup.
- [[multi-tenancy]]: tenant context in threads.

---

## Recipes

- `new-turn-exit` **A new way for a response to end.** Copy the startup failure
  path in `ChatTurnExecution._run_response`, which calls
  `ChatResponsePersistence.save_failure`. List the outcome paths with
  `git grep -n "def save\|def report_\|def expire_save" backend/onyx/chat/persistence.py`.
  Check that Stop, a startup failure and a runtime failure each still report one
  outcome ([[#persist-once-per-model]]).
- `turn-state-field` **A field saved with each response.** Add it to
  `ChatResponseSnapshot` in `chat/models.py`, fill it in
  `chat/presentation.py:project_response`, and write it in
  `db/chat_response.py:save_chat_response_to_db`. Read it in
  `gather_stream_full` (non-streaming API) if API callers need it. If the value
  is agent state that a later step reads, also add it to `ChatFeatureState` and
  to `ChatAgent.capture_state` and `restore_state`. Decide what each incognito
  mode stores ([[chat-persistence#incognito-decision-per-field]]).
- `in-process-caller` **A new in-process caller.** Copy the Slack bot: it calls
  `handle_stream_message_objects` and consumes it with `gather_stream`. List the
  callers with `git grep -n "handle_stream_message_objects(" backend`. Do not
  start a `ChatAgent` directly: admission, delivery and saving live in
  `start_chat_turn`.
- `investigate-stuck-turn` **Investigate a turn that does not end, a stop that
  does nothing, or a send refused as busy.** In `backend/log/api_server_debug.log`,
  find "Chat turn control failed", "Chat response polling failed", "Chat response
  completion failed", "Chat session admission was lost", "Chat ownership control
  failed", "Response ownership renewal failed", "Failed to read agent Stop
  request", "Response persistence exceeded its wait bound" and "Chat turn
  exceeded its execution deadline". A deadline or a lost admission ends the
  stream with no stop packet ([[#non-user-cancel]]). In the tenant's cache, the
  session owner key is `chatprocessing_owner_<session_id>`, the processing fence
  is `chatprocessing_fence_<session_id>` (it holds the stream ID), and the stop
  key is `chatsessionstop_fence_<session_id>_<stream_id>`. Each owned run also
  has `chat_response_owner:<response_id>`, `chat_response_stop:<response_id>`
  and `chat_response_lock:<response_id>`; a child run's owner lease keeps the
  turn and its admission alive. An owner key with no live turn blocks sends
  until its lease expires. A stop key for an older stream ID does nothing
  ([[#disconnect-is-not-stop]]).

---

## Verification

- Unit: `backend/tests/unit/onyx/chat/` covers the chat agent, preparation,
  cancellation, multi-model streaming, the stream buffer and `gather_stream`.
- External dependency: `backend/tests/external_dependency_unit/answer/` runs
  turns through preparation and storage, including compaction.
  `backend/tests/external_dependency_unit/chat/` covers the run store and
  incognito storage.
- Integration: `backend/tests/integration/tests/streaming_endpoints/`.
  `INTEGRATION_TESTS_MODE=true` makes the renderer emit `ToolCallDebug` packets,
  so a test can assert which tools ran. `TestClient` buffers the stream, so a
  disconnect test needs a real socket, as
  `backend/tests/integration/tests/streaming_endpoints/test_resume_stream.py`
  does. A completion test holds a save open and asserts that admission stays
  held.
- Playwright: `web/tests/e2e/chat/stream_recovery.spec.ts` covers reload, network
  recovery and stop against the real API with a scripted model.
- By hand: send a message that forces a search. Press stop during the answer and
  reload: the partial answer must stay. Send again, close the tab during the
  answer, and reopen the session: the answer must resume or show as saved. Run a
  multi-model turn and confirm that each column ends with its own answer or error.

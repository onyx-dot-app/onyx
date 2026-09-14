# Python agent runtime

The API process runs the internal chat, coding, research, and deep-research agents.
They share `Agent.run()`.

| File | Responsibility |
| --- | --- |
| `runtime.py` | Canonical history, turns, hooks, tool scheduling, and snapshots. |
| `events.py` | Discriminated event types with required payloads. |
| `tools.py` | Executable tools and progress callbacks. |
| `transcript.py` | Versioned storage schema. |

Canonical messages, model requests, and cancellation live in the [model API](../llm/README.md).

## Execution

An agent owns messages, executable tools, and hooks. `run()` continues its history and returns an isolated `AgentResult`.
`run(messages=[UserMessage(content="...")], max_turns=10)` adds input before execution.
`steer(message, expected_execution_id=...)` queues input before the next model call, after current tools finish.
`follow_up(message)` delivers one queued message when the active execution would otherwise finish.
Both require active execution and return an input ID. Steering takes priority over follow-ups.

`pending_inputs` returns copies of unconsumed input. `remove_pending_input(id)` returns whether removal succeeded.
The `input_consumed` event identifies input added to history. Removal cannot withdraw consumed input.
Unconsumed input remains available after completion, cancellation, errors, or turn limits.
Each input belongs to one execution and cannot enter a later execution automatically.

The frontend owns queued chat requests and submits each through the normal chat endpoint.
`abort()` cancels the active execution; `wait_for_idle()` waits for the execution loop to exit.

A turn contains one model response and its tool results. Events carry a run ID and turn index.
Child executions also carry their parent run and tool-call IDs. These IDs are separate from chat session and display IDs.

Tools execute with bounded concurrency. Results enter history in call order, regardless of completion order.
A sequential tool makes its batch execute in order. Unknown tools and malformed or truncated arguments produce paired error results.
Tool-argument schema validation remains deferred.

## State and hooks

The agent owns canonical history. `agent.context` returns an isolated copy.
`transform_context` edits a request copy before generation. It can change instructions, messages, tools, and model options.
`AgentContext` contains messages, executable tools, generation options, and execution policy.
Before generation, the runtime converts this context to `GenerationRequest` with tool schemas.
The model receives a detached request; the agent retains execution ownership.

`before_tool_call` can return a result instead of executing the tool.
`after_tool_call` returns the accepted tool result. Both receive detached call context.
`after_turn` can transform detached tool results. It cannot edit the published assistant message.
The runtime validates identities and commits accepted changes before the next request.
Executed calls cannot change, and each must retain exactly one result. `should_stop_after_turn` reads a detached committed turn.

`after_turn` and event delivery run under `agent.state_lock`, a reentrant lock.
Keep these callbacks short. Perform model calls, tool I/O, and memory writes outside this boundary.
Applications can acquire the same lock to snapshot display state and runtime output together.

## Observation

Events are discriminated unions. Tool-end events require a call and result; message updates require model output.
Use `event.type` to identify the event and its payload.
Use concrete agent event classes or `agent_event` to construct events.
Generation events and their factory live in `llm/models.py`.

Each subscriber receives its own payload copy. Changing it cannot change runtime history or another subscriber's input.
Subscribers run synchronously under the state lock. Ordinary observer exceptions are logged and do not change execution outcomes.
Cancellation exceptions still propagate.
The agent consumes the model client stream and commits each update before notifying subscribers.
A successful model stream must end with a completed assistant message.
Applications can subscribe a renderer to produce UI output.

## Model requests and resources

`LLM` accepts `GenerationRequest` and `GenerationContext`.
Direct calls use `invoke`; the agent consumes `stream` for every generation.
Provider adapters serialize shared messages and preserve signed thinking blocks for replay.

Onyx context hooks use `context/messages.py` to prepare attachments, reminders, and cache hints as shared messages.
History selection lives in `context/prompt.py`.
Optional `PromptMetadata` supplies file references and token estimates.

Message snapshots copy editable data. Lazy file descriptors share one resource that owns the loader, lock, and cached bytes.
Copying or serializing messages does not read attachments. Concurrent descriptor copies load a resource only once.
Custom metadata must contain copyable values or explicitly shared resources with defined copy behavior.

## Persistence

`agent.snapshot()` returns the current execution’s output as a versioned `AgentTranscript`.
It returns `None` before execution starts.
The snapshot contains current-run output and queued follow-up input; it excludes initial history and input passed to `run(messages=...)`.
Each new `run()` starts a new output snapshot while retaining conversation history.

`agent.output_messages` includes application details for building file and tool records.
Storage snapshots exclude request metadata and application artifacts. Missing tool results receive error placeholders for valid replay.
`snapshot(cancelled=True)` marks the active assistant response as aborted without changing live execution.
Cancellation and failure also repair unfinished result pairs in runtime history.

Onyx saves snapshots in the chat message row at completion, failure, or Stop.
Output since the last save can be lost if the process exits unexpectedly.

## Cancellation

Requests share a cancellation signal across model workers and child agents.
An explicit run signal takes precedence, followed by the active parent signal, then the configured execution signal.
A tool result becomes accepted when the runtime commits it under `state_lock`.
Cancellation closes execution under that same lock. A commit in progress finishes event delivery before closure.
Stop preserves accepted results and rejects later callbacks, including callbacks received after the Agent starts another execution.
It interrupts owned provider I/O and waits for transport cleanup.
Running synchronous tools must cooperate through the signal or `check_cancelled()`.
An uncooperative tool thread or remote operation can continue after the execution loop exits.
An unresolved tool result therefore cannot establish whether an external side effect occurred.

Browser disconnection detaches a stream reader. Explicit Stop cancels execution.
Timeouts apply to provider requests, commands, and sandbox operations.

## Scope

Craft interactive, scheduled, and subagent work uses external OpenCode.
One-shot tasks, including chat naming, use `client.invoke(GenerationRequest(...), GenerationContext(...))`.
The provider adapter recovers compatible tool calls emitted as text; native calls take precedence.

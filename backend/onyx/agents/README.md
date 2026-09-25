# Agent runtime

`onyx/agents` runs tool-using LLM agents. Chat, deep research, and the coding agent are all
built on it. A feature brings a system prompt, a set of tools, and an optional next-step decision. The runtime
handles the rest: the generation loop, tool execution, subagents, context compaction,
streaming events, cancellation, and record-keeping.

| File | Contents |
| --- | --- |
| `runtime.py` | Agent configuration and history, run lifecycle, and model-step execution functions. |
| `models.py` | Conversation context, step decisions, and run records. |
| `concurrency.py` | Tracked threads, update acceptance, and event delivery. |
| `agent_coordination.py` | Optional child discovery, execution control, and archive access. |
| `tool_execution.py` | Parallel tool execution, pending input, and ordered result completion. |
| `tools.py` | `AgentTool`, `ToolInvocation`, and the `AgentControl` interface. |
| `events.py` | Typed execution events. |
| `compaction.py` | Token budgets, checkpoints, and history summarization. |
| `execution_records.py` | Run outcomes, compaction checkpoints, and model-history replay. |

Message and request types, and `CancellationSignal`, come from [`onyx/llm`](../llm/README.md).

## The model

Three ideas cover most of the runtime.

An **agent** holds the configuration and conversation state used to execute a run.
Chat creates a fresh `Agent` for each request from saved history.
`AgentState` holds the in-memory messages and compaction checkpoint.
SDK callers can also reuse an `Agent` across runs; each run appends to its history.
Instructions, tools, and generation settings are Agent defaults or choices captured for a step in `PreparedStep`.

A **run** is one execution of an agent, with a step budget. It drives the agent until the
model produces a final answer (`COMPLETE`), the budget runs out (`LIMIT`), someone cancels it
(`CANCELLED`), or something breaks (`ERROR`).
It can also suspend (`SUSPENDED`) while awaiting input, then continue with the same identity and remaining budget.

`Run` owns its live state, thread startup, cancellation, suspension, resumption, and completion.
The agent and coordinator retain references to that execution. `RunState` holds its current data.
`run.snapshot()` returns an independent `RunState` copy for inspection and storage.
Execution functions prepare model calls, compact history, and advance steps using the run's state.
`ToolBatch` owns parallel tool work for a step and records its results in the run.
Execution returns when it reaches a suspension or completion boundary.
`Agent` combines preceding history with its latest run when starting another execution.
A new run can start only after the previous run finishes and its workers become idle.

A **step** is one model generation together with the results of any tool calls it made. A run
is a loop over steps: generate, execute tools, decide whether to continue.

During a run, the agent emits typed `AgentEvent` values to `on_event`:

| Event types | What they report |
| --- | --- |
| `agent_start`, `agent_end` | The run starts or ends. The end event includes its outcome. |
| `input_required`, `agent_suspended` | A call awaits identified input, or execution releases its workers at a supported boundary. |
| `message_start`, `message_update`, `message_end` | A model generation starts, produces updates, or finishes with an assistant message. |
| `tool_start`, `tool_update`, `tool_end` | A tool call starts, reports progress, or returns a result. |

Each event carries a run ID so consumers can distinguish concurrent executions.
The run applies generation updates under its state lock before notifying listeners.
Cancellation preserves accepted partial output; `snapshot()` copies that state for independent inspection.
`message_start` and `message_end` own the agent's message lifecycle. Updates do not repeat generation start or done events.
Chat converts these events into frontend packets for text, reasoning, tool activity, and run status.
It saves the response under a chat message ID. Generation and content item IDs connect streamed output to saved response data.

## Quick start

```python
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.models import ToolResult, UserMessage


def get_weather(invocation: ToolInvocation) -> ToolResult:
    return ToolResult(content=f"Sunny in {invocation.arguments['city']}")


agent = Agent(
    llm,  # any LLM, e.g. onyx.llm.factory.get_default_llm()
    system_prompt="You are a weather assistant.",
    tools=[
        AgentTool(
            name="get_weather",
            description="Get the weather for a city.",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
            execute=get_weather,
        )
    ],
)
run = agent.start(
    background=False, messages=[UserMessage(content="Weather in Oslo?")], max_steps=5
)
result = run.result()
print(result.output.text)
```

`start(background=False)` runs on the calling thread until execution suspends or finishes.
Call `run.result()` to wait for the final result; it also waits through suspension.
An application can attach a `RunStore` through the coordinator to save terminal output on the execution thread.
`start()` defaults to `background=True`: it starts a worker thread and returns immediately. Register event delivery when starting:

```python
run = agent.start(
    messages=[UserMessage(content="Weather in Oslo?")],
    max_steps=5,
    on_event=render_event,
)
result = run.result(timeout=60)
```

`on_event` receives events from the first step. A later `subscribe()` receives subsequent events.
`run.result(timeout=60)` returns `RunResult`,
containing the final assistant message, step count, and stop reason.
`agent.state` returns an isolated view of conversation history and its compaction checkpoint.
An Agent accepts another run after its previous run finishes and becomes idle.
A suspended run keeps its conversation reserved, even after its workers become idle.

Run lifecycle notifications have distinct meanings:

| Notification | Meaning |
| --- | --- |
| Result ready | The final output and outcome are available. Saving and cleanup can still be running. |
| Saved completion | The coordinator has saved terminal output, or reports a storage failure. |
| Settled | The current execution has suspended or produced a final result. |
| Idle | Tool work and event delivery have drained. A suspended run can resume or transfer ownership. |

Initial execution and resumption use the same thread-launch path. `Run` owns startup rollback,
terminal output, and cleanup. The coordinator resolves child results by run ID; a `Run` represents local execution.
The coordinator calls its `RunStore` to save output after the result becomes available.

## Preparing and completing steps

`prepare_step(StepInput)` returns a `PreparedStep` for an allowed model call.
It receives conversation history, this run's input and output, the step budget, and the previous completed step.
Without this callback, the agent uses its configured instructions, tools, and model options.

`after_step(StepResult)` processes each completed step, including the last allowed step.
Return `True` to continue or `False` to finish. Without this callback, the agent continues after tool calls
unless all results request termination. It stops after a final answer.
A continuation request at the step limit produces `LIMIT`; it does not prepare or execute another step.
Raise from `after_step` when output validation fails. The run retains the completed output and records the failure.

Both callbacks run on tracked threads. Compaction does not repeat either callback.
`PreparedStep.assemble_messages` must be pure and repeatable: compaction can call it again with shorter history.

`Agent.generation_context` supplies tracing identity, content policy, and execution timeouts for every step.
`PreparedStep.stall_timeout_s` overrides the stream's idle timeout; `None` uses the agent's setting.
Generation options remain part of `PreparedStep`, since tool choice and token limits can change between steps.

Two optional tool callbacks cover interception and enrichment:

| Callback | Contract |
| --- | --- |
| `before_tool_call` | Return a `ToolResult` to skip execution, `PendingToolInput` to await approval, or `None` to proceed. |
| `after_tool_call` | Enrich an already accepted result. Failure preserves that result and fails the run. |

Callbacks receive copies. Required transformations belong inside the tool, before it returns a valid result.
For example, deep research normalizes a child report's citations before returning the parent tool result.

The runtime records a tool's raw result before calling `after_tool_call`.
That callback can replace the result; its failure preserves the raw result and fails the run.
A tool's operation status describes its recorded result, not whether its callback has finished.
The runtime waits for tool callbacks, then `after_step`, before preparing another model call.

## Tools

An `AgentTool` is a name, a description, a JSON-schema `parameters` dict, and a synchronous
`execute` function. Each tool call runs on its own tracked thread.
The `ToolInvocation` argument provides everything the tool needs:

- `arguments` — the parsed JSON arguments.
- `call_id`, `call_index`, `messages` — the call's identity and logical working history.
- `cancellation` — a `CancellationSignal`; long-running tools should call `check()` often.
- `update(ToolProgress(...))` — the current partial output and typed result details.
  Each update replaces the previous partial value. Return the complete value in `ToolResult`.
- `agents` — the subagent coordinator (next section).

When a step makes several tool calls, they run in parallel, unless any called tool is marked
`SEQUENTIAL` — then the whole batch runs one call at a time. Results are accepted in
whatever order tools finish, but the model history keeps the original call order.
Result enrichment and final tool events follow model-call order.

Application tools use `Tool.for_agent()` when binding to a conversation. Stateful tools must
return an isolated instance. SearchTool does this and declares sequential execution; its
internal retrieval work still runs in parallel.

Retrieval tools combine compatible query or URL lists before execution. One worker runs
that batch; each original call retains its ID and receives the pooled result and progress.
Other arguments must match. Sequential steps combine only adjacent calls, preserving order
relative to other tools. Shared retrieval uses the tool's existing combined-result limits.

`tool_runner.py` selects mergeable tools through `MERGEABLE_TOOL_FIELDS` and binds
`merge_arguments`. The SDK does not inspect search fields.
Steps with a `before_tool_call` hook and calls waiting for input execute individually.
Batch results are recorded together before checkpoint capture; resumed runs skip completed calls.
Prompt assembly replaces exact repeated passages within a step with references to earlier results.


The most important rule: a tool that fails should return `ToolResult(is_error=True)` so the
model can react. A raised exception is treated as a runtime bug and fails the whole run. The
runtime produces error results on its own for unknown tool names, malformed arguments, and
arguments the model truncated. The default loop stops when all results in a step set `terminate=True`.
A custom `after_step` function chooses whether to continue.

## Subagents

Pass an application-owned `AgentCoordinator` to `Agent.start` when tools need delegation.
The coordinator retains execution handles independently of the parent. Tools use `invocation.agents` to control authorized children.

```python
def delegate(invocation: ToolInvocation) -> ChildRunWait:
    child = invocation.agents.spawn_agent(
        child_agent,
        name="research",
        description="Investigate sources",
        max_steps=10,
        messages=task_messages,
    )
    return ChildRunWait(run_ids=[child.run_id])
```

Set `AgentTool.complete_children` to convert the terminal child snapshots into a `ToolResult`.
The runtime suspends the parent while it waits, then calls this function without repeating `delegate`.
The function receives failed and cancelled snapshots too, so the feature can choose how to report them.
A successful completion callback marks those child failures as handled.

Spawning returns both an `agent_id` and a `run_id`. Use `agent_id` to start another run on that child.
Use `run_id` to inspect, wait for, or cancel one execution. Paths are readable labels and may repeat.
`wait_run` remains available for bounded synchronous waits; it returns `None` on timeout without cancelling the child.
Live and archived failures raise `RunFailed`; cancelled results raise `AgentCancelled`.

Foreground children are the default. The parent waits for their terminal results and cancels them on failure or cancellation.
A suspended foreground child releases the parent's worker without cancelling its siblings.
Pass `lifetime=AgentLifetime.BACKGROUND` to let a child continue after its parent finishes.
Background children do not hold the parent's cleanup open. The application must retain their coordinator.

Use `add_completion_cleanup(run_id, callback)` for resources that must survive suspension, such as a coding workspace.
Register cleanup immediately after spawning the child. It runs after local execution finishes or releases ownership, once its workers drain.
Its returned future reports cleanup failures. Foreground parent cleanup and coordinator shutdown both retain this work.
Application integration uses `Run.add_idle_callback` and `Run.wait_for_idle` to observe when local work has drained.
A suspended run can be idle without being complete. Tool authors use `add_completion_cleanup` for resource cleanup.

Subscribe to a run for progress. Foreground child events also reach its ancestors; background runs require their own subscription.
`completion(run_id)` returns a future for terminal handling and preserves storage failures.
Resource cleanup has its own future and can finish later. `run(run_id)` retains the logical control handle after execution ends.
These interfaces work even when the spawning parent no longer observes the child.

Reuse a coordinator to retain children across root runs. Create a fresh `view` when parent resources or branch bindings change.
Each view uses an `AgentDirectory` to authorize lookups and restore saved agents while sharing local execution ownership.
Views authorize each archived run against their selected history, including runs already cached by another view.
The application can grant a new view access to live background runs with `visible_run_ids`.
A view without a new directory retains its source view’s access scope.
A different branch must supply its own directory before starting further work on a saved child.
The view reconstructs inactive children with current bindings and checks branch visibility before exposing their results.
It cannot replace a running or suspended child with another owner.

Call `Run.handoff` after suspension to release local execution. Resume the saved state with a new `Agent`.
Resumption creates a new `Run` object with the same ID, accepted input, and remaining step budget.
Parent dependencies use run IDs and completion records. Local resource cleanup finishes when execution is released.
A coordinator rejects competing local owners. The application uses an atomic storage claim to exclude other API pods.
A new coordinator can load terminal child states through `read_run`.
Foreground children must finish before the parent can transfer. Rejected transfers leave the local owner intact.

`close()` cancels all owned runs and waits for execution, terminal handling, and resource cleanup.
A timeout leaves unfinished work owned. The coordinator is process-local; storage and cross-pod control belong to the application.

Chat still creates coordination per response. Its factory can use an existing owner to build fresh parent bindings.
That factory lives in `onyx/chat/subagents.py`; generic background chat integration remains separate.

## Watching a run

Pass `on_event=listener` to `Agent.start()` to receive events from the start.
Later subscriptions receive future events. Each subscription returns an idempotent unsubscribe function.
Events describe run boundaries, steps, model output, and tool activity.
Execution and parent IDs connect child events to the root stream; readable labels belong to coordination metadata.

Unsubscription excludes future dispatches. A callback already selected for dispatch may still run.
Subscriptions end when delivery drains or is discarded.
Observers must not wait for their own run to become idle.

Delivery is best-effort. Chat shares one dispatcher across a turn. Each event enters its queue once.
Foreground child events reach both child and ancestor listeners. Background runs have separate delivery.
Each run tracks its accepted events until delivery finishes. Listener failures affect that subscription channel, not execution or storage.
A slow listener does not block execution. If a listener throws, or events back up past the queue bound, the runtime rejects new observer events and sets the run's
`delivery_failed` flag; the recorded state stays correct, and the consumer rebuilds its view
from the snapshot. Already queued callbacks may still drain.

## Chat stream

Model events describe one LLM request. Agent events add tool execution and run boundaries.
`ResponsePresenter` converts these events into the public chat stream.
It attaches message and parent identities, validates tool metadata, and formats citations.
The frontend chooses cards, tabs, and grouping from these identities and content.
The envelope’s `model_index` routes responses to the correct model panel. Layout coordinates exist only in the frontend.

The public content types are text, reasoning, and tool items:

| Item | Contents |
| --- | --- |
| Text | Text, purpose, citations, source documents, and status. |
| Reasoning | Reasoning text and status. |
| Tool | Name, arguments, status, output, and typed result metadata. |

`item_update` supplies the complete current item and replaces its previous value.
`item_delta` appends text or string argument fragments, or replaces partial tool output and metadata.
Tool items progress from `pending` arguments to `running` execution, then a terminal status.
`run_update` closes unfinished items when a run ends, including cancellation and failure.
A root `stop` packet closes the response. `chat_heartbeat` keeps the connection active during quiet work.

Tools supply partial and final results using the same metadata model.
For example, search metadata contains queries, filters, and documents.
Python metadata contains stdout, stderr, generated files, and execution errors.
Tools with plain text results use the tool item's `output` field.

Live streams send deltas followed by a complete item.
History loading builds complete items directly from accepted content and saved tool metadata.
Both paths use the same citation formatter and frontend item reducer.
Partial tool updates are transient. History retains accepted tool results; cancellation before a result can leave live-only tool output.
Provider-only fields, such as reasoning signatures, remain outside the public stream.

## Saving and restoring

A `RunState` is available at any moment — mid-run, after failure, after cancellation.
`run.snapshot()` returns an isolated record for that execution.
It holds the run's input messages, everything produced since (including partial assistant
output), and per-operation status records that index into those messages.
Message and operation changes are recorded together. Event listeners cannot change recorded data.
Child records are collected when the parent finishes; a parent snapshot is not a live view of every child.

Chat converts run messages and operation outcomes into response items with stable identities.
It captures these items in a detached `ResponseRecord`, removing application metadata
and tool details before persistence. Saved rendering reads items directly. Model-context
loading converts items into messages and excludes unfinished tool calls.

Archived child restoration rebuilds a conversation from messages, a compaction checkpoint, and the previous run identity.
Resuming a suspended execution instead requires its saved execution position and feature state.
`RunState.progress` retains the step budget, pending calls, completed callbacks, accepted input, generation options, and selected tool declarations.
A compaction checkpoint still describes summarized history; it does not replace execution progress.

### Suspend and accept input

`run.suspend()` requests suspension at a supported boundary.
The runtime finishes in-flight tools and callbacks before releasing its workers.
It can suspend during the tool phase with unanswered calls, or before the next step after its feature hooks finish.
Snapshots taken during provider I/O or arbitrary callbacks support inspection only.

`before_tool_call` can return `PendingToolInput(mode=InputMode.EXECUTE)` to gate an action.
A question tool returns `PendingToolInput(mode=InputMode.RESULT)` to request its result from the caller.
Each request has a unique `request_id` within its run.
Submit a matching `HumanToolAnswer` through `run.submit()`; answers can arrive while sibling tools are still running.
Approval executes the exact pending call. A result answer completes the question without repeating its tool code.
Repeated identical answers do not repeat actions; conflicting answers fail.

`run.wait_until_settled(timeout=...)` waits for suspension or terminal output.
`run.result()` remains terminal-only, so use the settled wait when the run can request input.
`run.resume()` continues a resident suspended run. Accepted input also wakes execution when work can proceed.

### Infrastructure: capture and restore execution

Tool authors do not manage checkpoints. Onyx binds response ownership through `ChatRunStore.bind()`.
The following operations support storage integrations and runtime tests.

Use `run.capture()` to copy the active run and its preceding `AgentState` together.
`ExecutionCheckpoint` names these values `run_state` and `agent_state`.
`agent.state` includes active output, so using it as the resume prefix would duplicate that output.
Only a suspended snapshot can resume. Wait for its workers to become idle before transferring execution ownership.

Chat stores accepted output as response items. `chat/checkpoint.py` serializes the extra data needed to resume:
step progress, application state, message metadata, and cache flags.
`serialize_checkpoint()` builds this data. `deserialize_checkpoint()` validates it against the selected history and reconstructs `ExecutionCheckpoint`.
The module registers the application models that can be restored. Each saved model includes a stable type tag and its fields.
Unknown tags are rejected. `chat/restoration.py` constructs agents and persists the file resources needed for resumption.

`ChatRunStore.handoff()` saves this data in `ChatResponseCheckpoint.state` (JSONB) before releasing ownership.
`ChatRunStore.resume()` loads it, rebuilds the feature, and resumes the saved run.

`Run.handoff()` releases suspended execution. Discard the original Agent and Run afterward.
`run.result()` raises `RunReleased` after release; input must target a resumed execution.
The storage adapter uses `save` and `expected_revision` to save matching state before ownership is released.
If saving fails, the local execution remains owned and can accept input or retry the save.
Features with private state supply `FeatureRestoration` from `runtime.py` for typed state capture and restoration.
This state lets a suspended run continue with its accumulated feature data.

`spawn_agent(restoration_config=...)` accepts application-owned settings for rebuilding a saved child
for another run. Chat stores `ResearchConfiguration` directly; the SDK passes these settings to the application.
Register executable tools on `Agent.tools`; the runtime restores the saved step's selection.
Onyx tools receive application context when invoked. Chat and research derive it from feature state,
which changes after the tool phase.
Rebuild the feature and its live resources, then create an agent with `restored.agent_state` and the saved `agent_id`.
Call `Agent.resume(restored.run_state)` on that new agent.
Resumption restores feature state and tools without repeating completed generation, tool actions, or feature hooks.
The application must prevent the old owner and restored owner from executing concurrently.

Bindings identify the tenant, selected branch, and context version; comparing them does not authorize access.
The application validates the selected history and supplies authorized clients and resources.

The shared Onyx factory reconstructs feature configuration from these saved values:

| Feature | State needed beyond plain message text |
| --- | --- |
| Chat | Citation/artifact data, staged files, search-tool state, and current-run flags. |
| Deep research | Selected configuration, elapsed time, and citation mappings. |
| Research child | Selected configuration, citation mappings, and search-tool decisions. |

Keep callbacks, credentials, and clients out of feature payload schemas. Application code reconstructs live resources.
Coding runs use temporary sandboxes and do not support checkpoint reconstruction.
The live coding task owns its sandbox until completion or cancellation.

### Chat archive

Chat saves response items at execution boundaries and adds display data when the response finishes.
Tool-call row identities remain stable, including links from child responses.
A safely paused response also needs supplemental execution progress in `ChatResponseCheckpoint`.

If child cancellation cannot settle within its bound, the parent records an execution failure
and retains captured partial child content. Thread cleanup continues under the existing idle boundary.

Chat stores root and child conversations in `chat_session`. A child has its own history
and references the parent response that created it. The root controls access, sharing, and retention.
The runtime agent ID identifies this session.

An assistant `chat_message` owns one complete or partial response, its outcome, and feedback.
Its user-message parent owns the input. Ordered `chat_response_item` rows preserve narration,
reasoning, tool references, and final text. `tool_call` owns arguments and results.
Generation boundary items retain status and provider metadata, including empty generations.

The runtime selects final-answer content when its completion decision finishes execution.
The application derives formatted answer text for existing clients from those items.
Chat rendering settings belong to generation items and do not affect model input.

A child instruction references its parent tool invocation and the child response it continues.
Restoring a child follows the selected root branch. Separate root branches can continue the
same child without combining their histories. Predecessor links must form one chain within
the selected branch; restoration selects its final response. Stored child instructions support text.
Root attachments use the existing user-message file associations.

## Compaction

Features never manage the context window; the runtime compacts on its own. The working
budget is 90% of the model's `max_input_tokens`, and compaction triggers when a request
reaches 85% of that. The runtime summarizes the oldest completed history into a
`CompactionCheckpoint` and keeps a recent tail of roughly 20% of the budget. Recorded
messages never change — a checkpoint only changes what the model sees: the retained system
messages, the summary, the latest user message, and the tail.

Each checkpoint carries a digest of the messages it covers, so a checkpoint from a different
history branch is detected and discarded. Chat stores each new checkpoint as a summary message row.
History loading selects summaries from the chosen branch. Exact covered-count and digest
fields identify the model-history prefix, including attachment expansion. Reusing a checkpoint
does not create another summary row. Historical summaries retain their message-ID cutoff.
If a provider still rejects a request for size,
the runtime compacts and retries the generation once, provided no partial output has
streamed. Instructions that cannot fit after compaction fail the run. Public waits raise `RunFailed` with safe failure data.

## Application integration

The SDK owns synchronous execution, typed events, safe suspension, and resumption.
Tools return a result or a pending request. They do not manage checkpoint storage or ownership.
Approval policies, question forms, and their HTTP endpoints are future product work.
The SDK does not accept new user messages during a run. Steering remains future work.

A chat request follows this path:

1. The API checks the request and selects streaming or complete output.
2. `prepare_chat_turn` loads authorized history, selects models, and creates response records.
3. `ChatTurnExecution` starts a response worker for each selected model.
4. Each worker builds chat or research behavior and calls `Agent.start(background=False)`.
5. `Run` advances model and tool steps. The model step calls `LLM.stream`.
6. The LLM adapter calls the configured provider and returns typed generation updates.

`ChatTurnExecution` owns one user request, which can produce several model responses.
It keeps Stop polling and delivery active while responses execute or save.
`Agent` supplies configuration and history. `Run` owns each execution's state and controls.
The response worker executes the run directly; these objects do not each create a thread.

Chat and research features supply prompts, tools, and step decisions to the SDK.
Chat persistence receives the tool IDs and citation metadata needed to save their output.

Chat keeps accepted output in `ChatMessage`, `ChatResponseItem`, and `ToolCall`.
A response's `run_id` connects live SDK handles to that same history.
Chat uses one execution worker per active agent, one turn control worker, and one event-delivery worker.
The event worker also writes replay batches to the configured cache. Slow cache writes delay later events, but control polling remains independent.
The execution worker saves terminal output. Suspension releases the worker; new input can start another worker to resume execution.
The control worker checks ownership deadlines while cache operations run separately.
Only lease renewal uses short cache timeouts. Stop checks and stream-status updates use the ordinary cache client.
Transient renewal failures retry within the last confirmed lease. Owner mismatch cancels immediately.
Without confirmation, cancellation starts five seconds before the 60-second lease expires.
Renewal timing starts before the cache request, so response latency does not extend local ownership.
Stream-status failures log and retry. The processing marker uses its 30-minute expiry, as on main.
It remains active while background children or unfinished finalization retain ownership.

`AgentDirectory` resolves agents and saved runs within an authorized conversation branch.
`RunStore` saves terminal output. `RunOwnership` reserves execution and releases it after workers drain.
Chat binds ownership when durable checkpoints are enabled. Saving output does not require ownership support.

`ChatRunStore` uses the tenant-scoped cache for live ownership and Stop delivery.
It allocates child responses before execution so another API pod can discover their history.
Database sessions and cache locks cover short state updates, never model or tool execution.

### Explicit checkpoint transfer

Bind authorized history lookup and the feature factory with
`ChatRunStore.bind(coordinator, directory=..., build_agent=...)`.
Application control calls `poll_control()` while `has_owned_work` is true, including during reconstruction.
`handoff()` requires a suspended, idle run and saves a `ChatResponseCheckpoint` beside its response history.
Its foreground children must have terminal results before transfer.
The checkpoint contains execution progress and callback payloads omitted from normal conversation history.
It contains no repeated response text, full model requests, history prefix, or nested child transcripts.
The original step budget and applied-callback boundary survive transfer.
Before handoff, the adapter verifies that saved history can reconstruct the captured input and output.
Unsupported input representations fail while the original run still owns execution.

`resume(run_id, context=...)` requires authorized history reconstructed by the application.
The adapter validates its digest and compaction boundary, then reconstructs the snapshot from saved response items.
Only one process can claim a checkpoint. Conditional revision checks reject stale writers.
Reconstruction failure before execution releases the claim for retry.
Completion removes the checkpoint while preserving chat history.

Live inspection snapshots are not transferable checkpoints. An in-flight tool must finish before ownership transfers.
The application must supply matching input history and supported feature reconstruction; snapshotting a Python client is not supported.
Coding's temporary sandbox has no cross-process reconstruction factory.

### Delivery and failure boundaries

There is no durable generic control ledger. The store does not accept approval answers or steering messages.
SDK tests exercise pending requests and early answers directly. Future product adapters must persist decisions before acknowledging them.
The existing chat Stop route keeps its cache signal; child Stop requests also use tenant-scoped cache state.
An expired owner is reported as interrupted when its response is inspected. Uncertain external work is never automatically replayed.

Released runs have no local execution owner. Stop requests use the application’s run-ID route.
Closing the old coordinator does not cancel execution claimed by another pod.
Incognito runs keep local ownership and do not write checkpoints or child conversations.
`ENABLE_CHAT_CHECKPOINTS` controls the persistent chat integration and defaults to true.

Checkpoint file data uses existing file-store references. Generated files are stored under the chat session before transfer.
Deleting the chat removes those files. Tool execution loads file contents when needed.

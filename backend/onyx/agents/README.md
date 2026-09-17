# Agent runtime

`onyx/agents` runs tool-using LLM agents. Chat, deep research, and the coding agent are all
built on it. A feature brings a system prompt, a set of tools, and an optional next-step decision. The runtime
handles the rest: the generation loop, tool execution, subagents, context compaction,
streaming events, cancellation, and record-keeping.

| File | Contents |
| --- | --- |
| `runtime.py` | `Agent`, the `Run` control handle, and the shared execution loop. |
| `models.py` | Conversation context, step decisions, and run records. |
| `concurrency.py` | Tracked threads, update acceptance, and event delivery. |
| `coordination.py` | Optional child discovery, execution control, and archive access. |
| `tools.py` | `AgentTool`, `ToolInvocation`, and the `AgentControl` interface. |
| `events.py` | Typed execution events. |
| `items.py` | Ordered response content and generation boundaries. |
| `compaction.py` | Token budgets, checkpoints, and history summarization. |
| `transcript.py` | Run outcomes, compaction checkpoints, and model-history replay. |

Message and request types, and `CancellationSignal`, come from [`onyx/llm`](../llm/README.md).

## The model

Three ideas cover most of the runtime.

An **agent** is a conversation. It holds the message history, the tools, and the decisions that
shape its behavior. An agent lives across executions: every run appends to the same history.
`AgentContext` contains retained messages and the compaction checkpoint. Instructions, tools,
and generation settings are Agent defaults or choices captured for a step in `PreparedStep`.

A **run** is one execution of an agent, with a step budget. It drives the agent until the
model produces a final answer (`COMPLETE`), the budget runs out (`LIMIT`), someone cancels it
(`CANCELLED`), or something breaks (`ERROR`).

A **step** is one model generation together with the results of any tool calls it made. A run
is a loop over steps: generate, execute tools, decide whether to continue.

Run IDs identify live execution. Stored responses use the existing chat message ID.
Generation and content item IDs remain stable across streaming and storage.

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
result = agent.run(messages=[UserMessage(content="Weather in Oslo?")], max_steps=5)
print(result.output.text)
```

`run()` starts a run thread and blocks for its result.
`start()` starts a run thread and returns its handle. Register event delivery when starting:

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
`agent.context` returns an isolated view of conversation history and its compaction checkpoint.
An Agent accepts another run only after its previous run becomes idle.

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

`Agent.execution` supplies tracing identity, content policy, and execution timeouts for every step.
`PreparedStep.timeout` overrides the request timeout; `None` uses the agent's timeout.
Generation options remain part of `PreparedStep`, since tool choice and token limits can change between steps.

Two optional tool callbacks cover interception and enrichment:

| Callback | Contract |
| --- | --- |
| `before_tool_call` | Return a `ToolResult` to skip execution, or `None` to proceed. |
| `after_tool_call` | Enrich an already accepted result. Failure preserves that result and fails the run. |

Callbacks receive copies. Required transformations belong inside the tool, before it returns a valid result.
For example, deep research normalizes a child report's citations before returning the parent tool result.

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

The most important rule: a tool that fails should return `ToolResult(is_error=True)` so the
model can react. A raised exception is treated as a runtime bug and fails the whole run. The
runtime produces error results on its own for unknown tool names, malformed arguments, and
arguments the model truncated. The default loop stops when all results in a step set `terminate=True`.
A custom `after_step` function chooses whether to continue.

## Subagents

Pass a caller-owned `AgentCoordinator` to `Agent.start` when tools need delegation.
A standalone Agent does not create coordination. A tool then controls children through `invocation.agents`:

```python
submission = invocation.agents.spawn_agent(
    child_agent,
    name="research-abc",          # lowercase letters, digits, hyphens
    description="Investigate sources",
    max_steps=10,
    messages=task_messages,
)
while (result := invocation.agents.wait_run(submission.run_id)) is None:
    invocation.cancellation.check()
```

`spawn_agent` registers the child under the parent's path — here `/root/research-abc` — and
starts its first run. Paths are readable labels and may repeat. Use the returned `agent_id`
for further calls; each execution gets a separate `run_id`.
`start_run` starts another run on a child that already exists, `wait_run` waits for a result
(returning `None` on timeout), and
`cancel_run` signals a run and its descendants to stop.
Live and restored failures both raise `RunFailed` with the same safe classification.
Cancelled runs raise `AgentCancelled`. A wait timeout returns `None` without cancelling the run.
`wait_for_idle(run_id)` waits for owned child cleanup, including after invocation cancellation.
Use it before deleting resources that child operations can still access.
`add_idle_callback(run_id, callback)` schedules cleanup after a child drains; the callback must not block.

Spawning returns before the child finishes, so a child can outlive the tool that created it.
The parent run stays responsible either way: on success it waits for its active children, and
on failure or cancellation it cancels them.
A waiting parent retains its thread. Each child starts an independent thread.

Reuse the same coordinator to reuse children across root runs.
The application can supply `lookup_agent`, `resolve_agent`, and `read_run` callbacks for saved conversation branches.
Archive reads run on tracked threads; discovery can list saved metadata without constructing Agents.
Chat's binding lives in `onyx/chat/subagents.py`; the research tool lives in `onyx/deep_research/agent.py`.

Coordination retains current child runs and the latest completed run per loaded child.
Older run IDs require archive access. Caller-held Run handles keep their own independent records.
The coordinator bounds loaded child Agents. Its `close()` cancels active work and waits for cleanup.
A close timeout leaves pending work owned.

Onyx creates coordination per request and restores children in later requests.
Active tasks stay on one API pod; the SDK does not provide remote cancellation or cross-pod exclusive execution.

## Watching a run

Pass `on_event=listener` to `Agent.start()` to receive events from the start.
Later subscriptions receive future events. Each subscription returns an idempotent unsubscribe function.
Events describe run boundaries, steps, model output, and tool activity.
Execution and parent IDs connect child events to the root stream; readable labels belong to coordination metadata.

Unsubscription excludes future dispatches. A callback already selected for dispatch may still run.
Subscriptions end when delivery drains or is discarded.
Observers must not wait for their own run to become idle.

Delivery is best-effort by design. Listeners get deep copies, in order, through a run-owned delivery thread.
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

A `RunSnapshot` is available at any moment — mid-run, after failure, after cancellation.
`run.snapshot()` returns an isolated record for that execution.
It holds the run's input messages, everything produced since (including partial assistant
output), per-operation status records that index into those messages, and nested snapshots
of every child run.

`snapshot.items` exposes accepted content with stable generation identities and outcomes.
Chat captures these items in a detached `ResponseRecord`, removing application metadata
and tool details before persistence. Saved rendering reads items directly. Model-context
loading converts items into messages and excludes unfinished tool calls.

Agent restoration receives conversation messages, a compaction checkpoint, and the previous
run identity. Archived child inspection reconstructs a `RunSnapshot` at the SDK boundary.

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

## Future requirement: human input and tool approval

Human input and approval require extending `RunSnapshot` with waiting requests, the step limit, and saved inputs for the unfinished step.
These features are not implemented yet. Current tool calls must return a result within execution timeouts.
Use the existing snapshot and response storage mapping; no separate run continuation model is needed.

The proposed first delivery supports root-agent interaction only. Children that need new approval return a tool error before execution.
Independent child suspension is a later extension, not a prerequisite for root questions and approvals.

If child interaction is enabled, a parent that starts agents A and B in parallel must support this sequence:

1. A requests approval before executing a tool. A pauses and exposes the approval request to the user.
2. B continues. The parent can process B's result while A waits.
3. The user approves A's pending tool call. A resumes without restarting B or repeating completed work.
4. If the parent needs both results, it continues past that dependency after both become available.

The SDK must own one pause-and-resume mechanism for tools that ask questions and hooks that request approval.
Feature authors should return a typed input request, without implementing persistence, polling, or worker coordination themselves.

The complete design, including the optional child extension, must satisfy these requirements:

- Save the waiting snapshot before reporting that an agent is waiting.
  Reuse its tool calls, accepted results, and operation indices. Preserve the original step limit across resume.
- Release execution resources held solely for waiting, including worker capacity and database connections.
  Human waiting has no execution timeout and consumes no step budget. Explicit cancellation still applies.
- Keep independent agents and tool calls running. Pause the parent only where it requires an unavailable result.
  A waiting child must not trigger tree cleanup, sibling cancellation, or a successful parent completion.
- Resume the affected execution after a response, including after reload or on another API pod.
  Restore data and rebuild executable tools; do not rely on a surviving Python stack or callback closure.
- Turn an answer into the pending question tool's result. Approval permits the exact pending tool call to execute.
  Rejection produces a denial result without executing that call. Resume must preserve already accepted tool results.
- Let the application own storage, authorization, and atomic acceptance of human responses.
  Bind each response to its pending request and conversation branch. Duplicate submissions must not start duplicate continuations.
- Emit explicit waiting and resumed states, scoped to the affected agent and tool call.
  The frontend must show the pending request while continuing to render active siblings.

The required extension belongs at tool outcomes, run continuation, and dependency coordination.
It must not require each harness to implement a separate approval loop. No speculative approval API is required before this feature is built.

## Cancellation

`run.cancel()` signals providers, tools, callbacks, and owned child executions.
Cancellation preserves accepted partial output and rejects updates after the record becomes terminal.
It cannot stop arbitrary Python threads or reverse remote writes.

Terminal output and idle are separate states. `run.result()` can finish while owned work still drains.
`run.wait_for_idle(timeout=...)` returns whether execution and cleanup have finished.
That includes tool threads, descendants, and dispatched observers.
A wait timeout does not cancel execution. Use `run.cancel()` explicitly.

The Agent stays unavailable for reuse until idle.
Chat retains execution and storage ownership across browser disconnects.
`run.add_idle_callback()` reports actual cleanup completion without occupying a waiting thread.
A timeout ends waiting; it does not stop or release an operation that is still running.
Coding tools wait briefly for child cleanup before deleting the child's sandbox.
If that wait expires, a child idle callback starts tracked sandbox cleanup. Parent idle still waits for that cleanup.

## Limits

| Bound | Value |
| --- | --- |
| Tool calls per step | 64 |
| Subagent nesting depth | 8 |
| Loaded child Agents per coordinator | 64 |
| Single operation timeout | 30 minutes |
| Event queue capacity | 1024 |
| Pending serialized observer payload | 4 MiB (`AGENT_EVENT_BUFFER_MAX_BYTES`) |

The byte bound includes queued events and the active callback payload; it does not bound total process memory.

The operation timeout bounds waiting for one operation, such as a hook, tool call, or child run.
Thread count follows concurrent requests and tool or child fan-out. There is no fixed SDK worker pool.
The remaining product limits and delivery buffers still apply.

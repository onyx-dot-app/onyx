# Shared agent runtime

`onyx.agents` executes a conversation through model calls and tools. It handles
parallel tool calls, child agents, cancellation, events, context compaction, and
suspension. Applications supply the model, instructions, tools, and storage adapters.

This package is available for integration. Production chat, research, and coding
still use their existing execution paths.

## Agent, run, and step

An **Agent** holds conversation history and execution defaults. A **Run** is one
execution with a step budget. A **step** contains one model generation and the
results of its tool calls.

```text
Agent: conversation history and defaults
  Run: one request, with a maximum number of steps
    Step 0: model message → tool calls → tool results
    Step 1: model message → final answer
```

A run ends with `COMPLETE`, `LIMIT`, `CANCELLED`, or `ERROR`. It can also become
`SUSPENDED` while waiting for input or child results. Suspension keeps the same run
identity and remaining step budget.

`Agent.state` and `Run.snapshot()` return independent copies. Recorded steps retain
accepted output, including partial output after cancellation. Model-history replay
omits incomplete tool exchanges; it does not remove them from the recorded output.

## Start a run

An application supplies an `LLM` and a tracing context for its operation:

```python
from onyx.agents.runtime import Agent
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import UserMessage
from onyx.tracing.flows import LLMFlow

agent = Agent(
    llm,
    system_prompt="Answer the user's question.",
    generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
)
run = agent.start(
    messages=[UserMessage(content="Explain this error.")],
    max_steps=5,
)
result = run.result(timeout=60)
print(result.output.text)
```

`start()` uses a background thread by default. `background=False` executes on the
calling thread until the run suspends or finishes. Register `on_event` during
startup to observe the first event; later subscriptions receive subsequent events.

A terminal result does not mean all work has finished:

| Observation | Meaning |
| --- | --- |
| `run.result()` | Terminal output is available. Saving and cleanup can still run. |
| `coordinator.completion(run_id)` | Terminal handling finished, including storage; the future reports storage failures. |
| `run.wait_until_settled()` | The run suspended or reached a terminal outcome. |
| `run.wait_for_idle()` | Owned workers and event delivery drained. A suspended run can still resume. |

An Agent accepts another run only after terminal handling and owned work permit
reuse. A suspended run reserves its Agent until it resumes or transfers ownership.

## Tools and step callbacks

`AgentTool` pairs a `ToolDefinition` with an execution function. The function
receives `ToolInvocation`, which contains arguments, call identity, working
messages, cancellation, progress delivery, and optional child controls.

Tools return `ToolResult`. Ordinary tool exceptions become error results that the
model can inspect. Cancellation propagates. Errors in coordination or tool hooks
can fail the run.

Tools run in parallel unless a called tool declares `SEQUENTIAL`; then the entire
step runs sequentially. Results and final callbacks follow model-call order,
regardless of worker completion order. A tool can provide `merge_arguments` to
combine compatible calls. Each original call retains its identity and result.

| Callback | Responsibility |
| --- | --- |
| `prepare_step` | Return the complete model configuration for the next step. |
| `after_step` | Validate the completed step and choose whether execution should continue. |
| `before_tool_call` | Permit execution, return a result directly, or request identified input. |
| `after_tool_call` | Enrich an accepted result. Failure retains the original result and fails the run. |

Callback inputs are detached from recorded state. `prepare_step` replaces the
Agent defaults for that step. Its message assembler must be pure and repeatable:
compaction can call it again with shorter history. Capture configuration during
preparation rather than fetching it inside the assembler.

Callbacks run synchronously and must bound their I/O. Cancellation cannot interrupt
a callback or blocked provider read until that operation returns.

## Cancellation and event delivery

Long-running tools must check `invocation.cancellation`. Cancellation rejects late
output but retains worker ownership until work returns. It does not undo external
side effects.

Typed events describe run boundaries, messages, tool progress, and suspension.
Message updates use the shared LLM content-delta types. Each event identifies its
run; message events also identify their model message and step.

Event delivery uses a bounded queue. Slow or failed listeners do not fail execution
or storage, but delivery can fail. Inspect `run.delivery_failed` when delivery
matters. Listeners must not wait for their own run to become idle.

## Child agents

Supply an `AgentCoordinator` when tools need child execution. A tool calls
`invocation.agents.spawn_agent()` and can return `ChildRunWait`. Its
`result_from_children` callback converts terminal child snapshots into a tool
result. The parent suspends while waiting; resumption does not repeat the spawn.

Foreground children hold parent completion open. Parent cancellation reaches them.
Background children can outlive the parent; the application must retain their
coordinator. Register `add_completion_cleanup` for resources that must survive
suspension and remain available until local work drains.

The coordinator shares local ownership across views. Each view uses its directory
to authorize access to saved agents and runs. It rejects competing local owners.
Closing the coordinator cancels owned runs and waits for execution, saving, and
cleanup. A timeout leaves unfinished work owned.

## Compaction

Compaction reduces working model context while preserving recorded history. A
checkpoint stores a summary and the last covered message ID. The runtime keeps
recent context and only summarizes eligible history boundaries.

Summary calls use `LLMFlow.CHAT_HISTORY_SUMMARIZATION`, bounded output, and a
bounded timeout. Invalid checkpoints or summaries that do not reduce context fail
explicitly. Compaction does not rerun step-preparation or completion callbacks.

## Suspension and restoration

`run.suspend()` requests a safe boundary. A pending tool-input request also permits
suspension. `run.submit()` validates an identified answer and wakes execution.
`run.resume()` continues a resident run.

For transfer to another owner:

1. Wait for the run to suspend and become idle.
2. Save through `run.handoff(save=...)` before it releases local ownership.
3. Construct an Agent with the captured history, original agent ID, and matching execution bindings.
4. Call `agent.resume(checkpoint.run_state)` to continue the same run.

`handoff()` requires terminal foreground children. A failed save leaves the current
owner intact. Restored progress retains completed tool results and callback
boundaries, so execution can avoid repeating completed work.

`ExecutionCheckpoint` contains history and execution state. It does not serialize
Python clients, callbacks, or external resources. Applications must reconstruct
those bindings and enforce exclusive ownership across processes. Stateful callbacks
can implement `RestorableFeature` to capture and restore their own state at safe
execution boundaries.

The coordinator defines three application interfaces:

| Interface | Responsibility |
| --- | --- |
| `AgentDirectory` | Authorize lookups, restore agents, and read or cancel saved runs. |
| `RunStore` | Save terminal output before dependent runs receive completion. |
| `RunOwnership` | Reserve execution, undo failed startup, and release ownership after work drains. |

This package supplies no database adapter, durable input-decision ledger, or
cross-process ownership service. Storage integration must preserve the same
lifecycle guarantees.

## Source map

| File | Responsibility |
| --- | --- |
| `execution_records.py` | Outcomes, compaction checkpoints, and model-history replay. |
| `models.py`, `tools.py`, `events.py` | Execution state, tool contracts, and events. |
| `concurrency.py` | Worker tracking, cancellation waits, and event delivery. |
| `compaction.py` | Context budgets and history summarization. |
| `runtime.py` | Agent state, run lifecycle, model steps, and restoration. |
| `tool_execution.py` | Tool scheduling, pending input, and ordered completion. |
| `agent_coordination.py` | Child execution, application adapters, and ownership. |

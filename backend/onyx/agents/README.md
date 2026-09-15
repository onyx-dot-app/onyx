# Python agent runtime

The API process runs chat, coding, research, and deep research through `Agent.run()`.
Feature code supplies instructions, tools, and hooks. Agent owns execution, history, child lifetime, compaction, and cancellation.

| File | Responsibility |
| --- | --- |
| `runtime.py` | Execution, hooks, child scheduling, and snapshots. |
| `events.py` | Typed execution updates. |
| `tools.py` | Executable tools and invocation services. |
| `compaction.py` | Bounded context summaries and checkpoints. |
| `transcript.py` | Stored execution data and model-history selection. |

Messages, generation requests, and cancellation signals live in [llm](../llm/README.md).

## Execution scopes

A chat turn is one submitted user request and its responses. The application owns that interaction.
A run is one Agent execution. It contains steps and can start child runs.
Model comparison creates several root runs within one chat turn. Child runs belong to their parent tool calls.
SDK run IDs are separate from saved message IDs and processing keys used for Stop and stream replay.

## Execution and input

`run(messages=[UserMessage(content="...")], max_steps=10)` adds input and continues the agent's history.
A step contains one logical model generation and its tool results. `RunResult` contains the run ID, final assistant output, step count, and stop reason.
Read full conversation history through `agent.context.messages`.

`steer(message, expected_run_id=...)` queues input before the next generation, after current tools finish.
`follow_up(message)` queues input for when the current task would otherwise finish. Steering takes priority.
Both require active execution and return an input ID.

`pending_inputs` returns copies. `remove_pending_input(id)` removes input that has not been consumed.
The `input_consumed` event identifies input added to history. Unconsumed input cannot enter a later execution automatically.
The frontend owns queued chat requests and submits them through the chat endpoint.

## Feature hooks

`prepare_step` selects instructions, tools, and options once per step.
`build_request` assembles the generation request. It must remain pure because compaction can cause another assembly.
`after_step` observes the accepted step and decides whether feature work continues.

`before_tool_call` can supply a result without executing the tool.
`after_tool_call` finalizes results on the parent path, in call order, before acceptance and the final event.
Completed results cannot change afterward.

`agent.context` returns an isolated copy. The request builder returns a detached `GenerationRequest`. Tool execution uses the prepared agent context.

## Tools and children

`AgentTool` has one synchronous or asynchronous implementation.
`ToolInvocation` supplies arguments, identity, cancellation, progress, and child execution.
Tools emit domain progress. Application presentation maps it to packets. Child events carry their ancestry directly.
Tools preserve typed result details for application artifacts.

Child-launching tools pass task input through `invocation.run_child(child, messages=[...], max_steps=...)`.
Waiting parents consume no blocking-worker capacity.
`invocation.run_blocking(...)` runs blocking work in the shared context-propagating executor.
The root bounds leaf work, submissions, child count, and depth. Successful execution joins its children.

Parallel results enter history in call order. Sequential tools make their batch execute in order.
Unknown tools and malformed arguments produce paired error results. Existing tool-specific validation remains in place.

## Compaction

Every Agent compacts older completed history when its model context approaches the input limit.
It retains the current user instruction and a bounded recent tail. Summary inputs and work are bounded.
Compaction creates a checkpoint; recorded messages remain intact.

A provider context rejection can trigger one compacted generation retry. Tools do not execute again for that retry.
Oversized required instructions fail explicitly when they cannot fit.

## Events and snapshots

Events carry run, message, tool-call, and parent identity. Each Agent preserves event order.
Subscribers receive copies through bounded delivery outside the state lock.
Observer failure or overflow marks delivery as failed; execution retains its accepted state.

`agent.snapshot()` returns `RunSnapshot`, or `None` before execution starts.
`input_messages` contains the messages supplied to `run()`. `messages` contains subsequent output and consumed steering or follow-up input.
Prior history and unconsumed queued input are excluded. Operation indices address `messages`.
Each new run replaces the current snapshot while retaining conversation history in `agent.context`.
Snapshots also contain typed details, operation status, checkpoint, and child snapshots.
Child snapshots do not form an atomic whole-tree transaction.

Features attach typed output metadata to their steps. Applications project display and artifacts from the snapshot, independently of streaming. `snapshot.transcript()` copies run input and output into storage-safe execution data, removing application metadata and tool details.
Chat omits root input from that record because its user message is stored separately. Child records retain their task input.
Incomplete calls remain recorded but are excluded from model requests until matching results exist.

Onyx saves terminal snapshots at completion, failure, or Stop. Application records own presentation and artifact references.
A process exit before saving can lose recent output. Stream cache gaps use persisted-history fallback.

## Cancellation and resources

`abort()` cancels active execution. `wait_for_idle()` waits for the execution loop to exit.
Stop targets the active request, cancels descendants, and closes result acceptance. Late callbacks cannot alter a later run.
Owned provider I/O is interrupted, with bounded cleanup.

Synchronous tools must cooperate through cancellation signals. Uncooperative threads or remote operations can outlive execution.
Cancellation does not reverse completed writes. An unresolved result cannot prove whether a remote side effect occurred.
Browser disconnection detaches delivery; explicit Stop cancels execution.

Message copies share lazy file resources. Copying messages does not read attachments; concurrent copies load each resource once.

## Other callers

Single-request tasks, including chat naming, use `LLM.invoke` with `GenerationRequest` and `GenerationContext`.
Craft interactive, scheduled, and subagent work uses external OpenCode.

# Shared Agent Runtime

> Executes model and tool steps with explicit cancellation, ownership, and restoration boundaries.

**Verified against:** `55a8f75b65` (2026-10-26)
**Domain:** core-loop
**Edition:** CE
**Owns:** `backend/onyx/agents/`

## 1. What the user experiences

This package has no production caller yet. Chat, coding, and research keep their
existing execution paths. The runtime provides a common engine for later
integration without changing their current user behavior.

## 2. Surfaces

Python callers create `Agent` and start a `Run`. Tools use `ToolInvocation` and
optional child controls. Applications can implement storage and access interfaces
on `AgentCoordinator`. The package adds no HTTP endpoint or configuration setting.

## 3. Data model

`AgentState` stores conversation history and a compaction checkpoint. `RunState`
stores accepted input, ordered steps, outcomes, and resumable progress. Each step
contains a model message and its tool execution records.

`ExecutionCheckpoint` combines preceding history with run state. These are Python
models; this package adds no database writes or schema changes.

## 4. How it works

`Agent.start` reserves conversation ownership and starts a `Run`. The run prepares
model requests, accepts streaming output, executes tools, and decides whether to
continue. `ToolBatch` schedules the selected tools and identifies completed calls.
`Run` reads their recorded results, invokes finalization hooks, and emits completion
events. Recorded results retain model-call order while tools complete concurrently.

`ToolExecutionMode.SEQUENTIAL` orders calls to the same registered tool name within a step.
An earlier call holds that place until finalization, including waits for input or children.
Unrelated tools can run concurrently. This mode does not coordinate separate runs.

`AgentCoordinator` controls children and application storage callbacks. Foreground
children delay parent completion. A parent can suspend while waiting for input or
child results, then resume with its original identity and budget.

See `backend/onyx/agents/README.md` for the public contracts and usage.

### Child completion and generation retries

These rules apply to the shared runtime, which has no production chat caller yet.
`backend/onyx/agents/agent_coordination.py:AgentCoordinator.restore_completed`
resolves the existing completion future so waiting parents resume. It updates
latest-run discovery only for that run and rejects conflicting terminal records.
A later dependency lookup can retry a failed remote observation or load its saved
terminal result. Local execution and persistence failures remain authoritative.

Cancelling a suspended child can start another worker.
`backend/onyx/agents/agent_coordination.py:RunCoordination.finish` tracks its new
cleanup work so the parent waits for ownership release.

`backend/onyx/agents/runtime.py:_advance_step` retries context-limit failures only
before model content arrives. Partial thinking, text, and calls remain in the
failed generation.

### Ownership and restoration

Each run owns its cancellation signal. Caller cancellation reaches the run;
run cancellation does not cancel the caller's signal.

`Agent.tools` registers executable tools. `PreparedStep.tools` selects those same
instances. Invalid selections fail before generation. Restored selections must
match the saved declarations.

Waiting for a cancelled child raises `ChildRunCancelled`. A tool can handle this
exception; otherwise, it becomes a tool error. Parent cancellation still interrupts
the wait with `AgentCancelled`.

Handoff saves suspended state and releases the ownership adapter's reservation
once. Local execution stays reserved until release finishes. Release failure
reports the cleanup error to local waiters and pending parent dependencies.
Saved state remains available for another resume. Completion publication uses
the existing observer reservation, so a late remote read cannot replace the error.

Tool progress omits failed results' model-facing text. Structured result details
carry explicit public errors. Recorded results retain the model-facing text.

Compaction validates its source message ID before it calls the summary model.

### Model-history replay

`backend/onyx/agents/execution_records.py` supplies stable input-message IDs and model-history replay.
Its `messages_for_model` function creates model context from recorded messages.
It retains partial text and signed thinking, but omits tool calls without adjacent results.
Thinking without provider blocks and unsigned provider thinking blocks cannot be replayed.
Signed and redacted blocks remain intact.
It also removes orphaned or duplicate tool results and copies messages by default.
Calls with duplicate IDs in one assistant message are ambiguous; replay omits them and their results.
This helper prepares history without deleting the recorded output.
Production chat does not call this module yet.

## 5. Contracts and invariants

- Cancellation rejects late updates but retains ownership until workers drain.
- Child cancellation failures do not skip siblings, retained local work, or parent completion.
- Model events recheck cancellation under the execution lock before changing recorded state.
- Result readiness, saved completion, suspension, and idle state have distinct meanings.
- Recorded partial output survives even when replay excludes incomplete exchanges or thinking without replayable provider blocks.
- Model history retains original tool-call order. Completion callbacks and events follow result readiness.
  A slow call does not delay another call's completion. Callbacks remain serial on the execution thread.
  Saved progress identifies finalized callbacks by call ID and rejects old counter-based snapshots.
- Run owns recorded mutations; tool scheduling receives explicit borrowed step data.
- Collaborators lock borrowed step data with execution_lock and use recording methods for changes.
- Step callback inputs and public snapshots do not share mutable recorded state.
- Message assembly borrows history and must not mutate its messages or nested data.
- Compaction changes working context, not recorded conversation history.
- Summary batches share one operation deadline.
- Every Agent requires an explicit tracing flow.
- Feature state is stored as JSON; restoration validates it into a feature model.
- Tool-facing child waits observe saved completion; parent records are detached.
- Restored parents can wait for authorized remote children without treating them as completed.
- A retried remote-completion observation gets a new wake-up subscription; subscriptions follow futures, not only run IDs.
  Healthy subscriptions are reused without loading saved run content again.
- Completing an older remote run does not replace a newer latest run for that agent.
- Handoff requires suspended, idle execution and terminal foreground children.
- A failed handoff save leaves the existing local owner intact.
- Each tracked run retains completion and cleanup work when handoff releases its local execution.
- Application directories authorize saved-run access, including cached results across views.
- Listener and output-flush failures mark affected deliveries failed without failing execution or storage.
- Closing delivery rejects new events; accepted events remain pending through buffered-output flushes.
  A worker startup failure still closes admission; the caller handles final output cleanup.
- Immutable deltas can be shared; mutable event payloads remain isolated between listeners.
- Token-count caches belong to one run and retain only the current request text.

## 6. Dependencies

- [[llm-providers]] supplies messages, generation events, cancellation, and the shared LLM client.
- `backend/onyx/utils/threadpool_concurrency.py` starts workers with saved context.
- `backend/onyx/prompts/compression_prompts.py` supplies the compaction instruction.

Production [[core-chat-loop]], [[tools-framework]], and [[chat-persistence]] do not
use this runtime yet.

## 7. Blast radius

| Change | Review |
| --- | --- |
| Run lifecycle | Tool workers, child completion, saving, idle notifications, and Agent reuse. |
| Tool scheduling | Call order, pending input, merged calls, and resumed steps. |
| Snapshot or checkpoint models | History replay, callback boundaries, and restoration. |
| Event delivery | Pending delivery, ancestor listeners, context propagation, and worker cleanup. |
| Application adapters | Authorization and ownership across coordinator views. |

## 8. How to verify

Run the isolated runtime scenarios under `backend/tests/unit/onyx/agents/`.
Cover parallel tools, cancellation, child lifetimes, suspension, restoration,
compaction, and storage failure. Check typing and existing LLM tests as well.

These tests use controlled model and tool implementations. They verify SDK
behavior, not database durability or production chat adoption.

## 9. Footguns

- `run.result()` can return before storage and cleanup finish.
- Cancellation cannot undo tool side effects or interrupt arbitrary blocking I/O.
- Event listeners must not wait for their own run to become idle.
- Event queues are unbounded; slow listeners can increase retained memory.
- Message assembly receives a tuple, but its nested objects remain mutable.
- A checkpoint cannot serialize Python callbacks or external resources.
- Local ownership does not exclude another process; the application must supply that guarantee.
- A suspended run can be idle while still reserving its Agent.

Compaction preserves the current run's unanswered input as one group, including attachment text and request context.
The boundary comes from the run's history and input lists. Earlier failed input remains recorded but can be compacted for a new request.
Oversized current input fails instead of silently removing its contents. Without an explicit run input, compaction preserves the entire trailing unanswered group.

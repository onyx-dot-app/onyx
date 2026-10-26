# Shared Agent Runtime

> Executes model and tool steps with explicit cancellation, ownership, and restoration boundaries.

**Verified against:** `8af1ae5828` (2026-10-26)
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
continue. `ToolBatch` preserves model-call order while tools complete concurrently.

`AgentCoordinator` controls children and application storage callbacks. Foreground
children delay parent completion. A parent can suspend while waiting for input or
child results, then resume with its original identity and budget.

See `backend/onyx/agents/README.md` for the public contracts and usage.

## 5. Contracts and invariants

- Cancellation rejects late updates but retains ownership until workers drain.
- Result readiness, saved completion, suspension, and idle state have distinct meanings.
- Recorded partial output survives even when model-history replay excludes incomplete tool exchanges.
- Tool results and completion callbacks follow the original model-call order.
- Step callback inputs and public snapshots do not share mutable recorded state.
- Message assembly borrows history and must not mutate its messages or nested data.
- Compaction changes working context, not recorded conversation history.
- Handoff requires suspended, idle execution and terminal foreground children.
- A failed handoff save leaves the existing local owner intact.
- Application directories authorize saved-run access, including cached results across views.
- Listener failure does not fail execution or storage; event delivery can fail independently.
- Closing delivery rejects new events and drains accepted events before releasing listeners.
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

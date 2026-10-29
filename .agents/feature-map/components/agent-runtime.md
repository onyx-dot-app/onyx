# Shared Agent Runtime

> A Python engine that runs an agent through model steps and parallel tools, with
> child agents, cancellation, compaction and suspension, which no production path
> runs. This document is the one record of which runtime, chat and database
> modules around it are live, shared or not wired.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## Callers

**Interface.** A caller creates an `Agent` with an `LLM` and a
`GenerationContext` that names an `LLMFlow`, starts a `Run`, and reads typed
events and a `RunResult`. Tools receive a `ToolInvocation` and can start child
agents through an `AgentCoordinator`. The application supplies storage and
ownership through the `RunStore`, `RunOwnership` and `AgentDirectory`
interfaces. `backend/onyx/agents/README.md` is the full contract: cancellation,
event delivery, pure message assemblers, child agents, compaction and handoff.
This document does not repeat it.

**Who calls it.**
- **A backend developer who builds a feature on the runtime.** Start from the
  package README and [[#run-by-hand]].
- **No product component.** Chat, deep research and the coding agent run
  through [[core-chat-loop]], and [[chat-persistence]] owns the live history and
  display writes. Only the not-wired chat and database modules in the status
  table call the runtime, and only tests call them.
- **A reviewer** uses the status table to tell whether a change to a module can
  reach users.

**What a caller must keep:** [[#result-before-storage]],
[[#restored-tools-must-match]], [[#context-captured-at-start]] and, to make a
module live, [[#no-side-effect-wiring]].

---

## Scope

This component owns the runtime package and the status of the modules that
were built to connect it to chat. It owns no endpoint, table or worker.

Neighbours: [[core-chat-loop]] owns the live turn. [[chat-persistence]] owns the
tables, including the columns that only not-wired writers fill. [[llm-providers]]
owns the `LLM` interface that the runtime calls. [[context-assembly]] owns the
compaction prompt text.

---

## Architecture

```
Agent (history, defaults, registered tools)
  start() -> Run (one request, step budget, own cancellation signal)
    step: prepare_step -> model generation -> ToolBatch (parallel, ordered results)
          -> after_step decides: continue, finish, or suspend
  AgentCoordinator: children, RunStore / RunOwnership / AgentDirectory adapters
  handoff(save=...) -> ExecutionCheckpoint -> Agent.resume(snapshot) elsewhere
```

- `backend/onyx/agents/runtime.py` holds `Agent`, `Run` and the step loop
  (`_advance_step`).
- `backend/onyx/agents/tool_execution.py:ToolBatch` schedules a step's tools and
  records results in model-call order.
- `backend/onyx/agents/agent_coordination.py:AgentCoordinator` runs children and
  calls the application's storage and ownership adapters.
- `backend/onyx/agents/compaction.py` summarizes working context. Recorded
  history stays intact.
- `backend/onyx/agents/execution_records.py:messages_for_model` filters history
  for the model. It drops incomplete tool exchanges and thinking that cannot be
  replayed.

The package has no database adapter, no cross-process ownership service and no
HTTP surface.

**Module status.** This table is the one record. Other documents link here
instead of repeating a status.

| Module | Status | Evidence |
|---|---|---|
| `agents/runtime.py`, `agents/agent_coordination.py`, `agents/tool_execution.py`, `agents/concurrency.py`, `agents/tools.py` | not wired | No import outside the package. |
| `backend/onyx/agents/events.py` | not wired | Imported outside the package only by `chat/presentation.py`. |
| `backend/onyx/agents/compaction.py`, `backend/onyx/agents/execution_records.py` | not wired | Outside the package, `chat/prompt_formatting.py` and `db/chat_response.py` import `agents/compaction.py`; `db/chat_response.py` and `db/chat_subagents.py` import `agents/execution_records.py`. |
| `backend/onyx/agents/models.py` | shared | `db/models.py:ChatMessage.response_status` maps to `RunStatus`. `db/chat.py` and `chat/models.py` import its types. |
| `chat/response_models.py` | shared | `CitationMode` drives the live citation processor and the research agent. `db/chat.py` uses `HistoryLink` and `SessionAncestor`. |
| `chat/presentation.py`, `chat/renderer.py`, `chat/response.py` | not wired | Only each other and tests import them. |
| `chat/prompt_formatting.py` | not wired | No importer outside tests. The live loop formats history in `chat/llm_step.py:translate_history_to_llm_format`. |
| `db/chat_response.py`, `db/chat_subagents.py` | not wired | Only each other and tests import them. |
| `ChatResponseItem`, `ChatResponseCheckpoint`, `ChatMessage.response_failure`, `ChatMessage.invoking_tool_call_id` | not wired | Mapped in the ORM (`db/models.py:ChatResponseItem`, `db/models.py:ChatResponseCheckpoint`, `db/models.py:ChatMessage.response_failure`, `db/models.py:ChatMessage.invoking_tool_call_id`), not database-only. Only `db/chat_response.py` and `db/chat_subagents.py` write them. |
| `db/chat_display.py` | live | `chat/save_chat.py:save_chat_turn` calls `save_chat_display__no_commit`. |
| `ChatSession.spawned_by_message_id` | shared | Live queries in `db/chat.py`, `db/chat_search.py`, `db/incognito.py` and `backend/ee/onyx/db/query_history.py` exclude or refuse child sessions. Deletion and retention walk them through `db/chat.py:session_descendants`. Only `db/chat_response.py` creates them. |

To check a row again, run
`git grep -n "onyx.<module path>" -- backend ':!backend/tests'` and confirm that
every importer is itself not wired.

---

## Contracts and traps

1. `result-before-storage` **`run.result()` can return before storage and
   cleanup finish.** Wait on
   `backend/onyx/agents/agent_coordination.py:AgentCoordinator.completion` for
   saved completion; a storage or cleanup failure shows there, not in
   `run.result()`. Wait on `backend/onyx/agents/runtime.py:Run.wait_for_idle`
   before reuse or handoff. The table in the package README lists what each wait means.
2. `two-save-chat-turn` **Two functions named `save_chat_turn` exist.** The live
   one is `chat/save_chat.py:save_chat_turn`. `db/chat_response.py:save_chat_turn`
   is not wired. Check the import before you edit one.
3. `no-side-effect-wiring` **Do not add a production import of a not-wired
   module as a side effect.** That makes it live without review of its
   persistence and display paths. Update the status table in the same change.
4. `shared-modules-reach-live-chat` **A shared module serves both sides.** A
   change to `backend/onyx/agents/models.py` or `chat/response_models.py`
   reaches the live citation processor, the ORM mapping and `db/chat.py`. Run the
   chat tests, not only the runtime tests.
5. `restored-tools-must-match` **A restored run needs the same tools.** A
   checkpoint holds data only. It does not serialize clients, callbacks or other
   resources, so the new owner rebuilds them, possibly in another process or
   after a deploy. Each tool's definition must equal the saved step's
   declaration, or `backend/onyx/agents/runtime.py:_execute_tools` raises
   `ValueError`. Keep a tool's definition stable while saved checkpoints can
   still resume.
6. `context-captured-at-start` **A run copies the caller's context when it
   starts.** `backend/onyx/agents/runtime.py:Run._start` calls `copy_context()`,
   and the run's worker threads use that copy. So set the tenant and open the
   root trace before `Agent.start` or `Agent.resume`. A trace that opens later,
   or a tenant that a tool sets, does not reach the run. A Celery task or a
   process that resumes a checkpoint ([[#restored-tools-must-match]]) must do
   both first ([[multi-tenancy#threads-copy-context]],
   [[observability#root-trace-required]]).

---

## Decisions

- **The runtime holds no chat code.** Applications supply the model,
  instructions, tools and storage adapters (package README). The chat display,
  citation and persistence adapters live in the chat and database modules.
- **Storage and ownership are interfaces** (`RunStore`, `RunOwnership`,
  `AgentDirectory`), so each application chooses its durability and
  authorization.

---

## Known issues

- No integration test runs a real chat turn through the not-wired modules, and
  nothing compares their packets with the live stream.
- The package README source map lists the runtime files only. The status table
  is the record for the chat and database modules.

---

## Dependencies

- [[llm-providers]]: messages, generation events and the shared `LLM` client.
- [[observability]]: every `Agent` needs an explicit `LLMFlow` tag, and the
  run needs a root trace from its caller.
- [[multi-tenancy]]: the run copies the caller's tenant context.
- [[context-assembly]]: the compaction instruction in
  `prompts/compression_prompts.py`.

---

## Recipes

- `run-by-hand` **Run the runtime by hand.** Copy the "Start a run" example in
  `backend/onyx/agents/README.md`. For a run against a fake model and fake tools,
  copy `backend/tests/unit/onyx/agents/fakes.py`. For real LiteLLM requests to a
  mock HTTP provider, copy
  `backend/tests/external_dependency_unit/llm/test_agent_runtime_http.py`.
- `new-feature` **Build a new feature on the runtime.** Start from
  [[#run-by-hand]], then settle these:
  - Runtime tools are `agents/tools.py:AgentTool`, not the chat `Tool` of
    [[tools-framework]], and no adapter exists. The built-in search, web and
    image tools do not plug in as they are.
  - Only tests implement `agents/agent_coordination.py:RunStore`, `RunOwnership`
    and `AgentDirectory` (`backend/tests/unit/onyx/agents/fakes.py`). Children,
    handoff and durable completion need adapters of your own.
  - A run that a user starts is an LLM entry point and needs the budget checks.
  - The first production import makes the runtime live. Update the status table
    ([[#no-side-effect-wiring]]).
- `wire-module` **Wire a not-wired module into a product path.** Add an integration test that
  runs a real turn through it, compare its packets with the live stream
  ([[streaming-protocol]]), update the status table, and update the
  [[core-chat-loop]] and [[chat-persistence]] documents in the same change.

---

## Verification

- Unit: `backend/tests/unit/onyx/agents/` covers lifecycle, child coordination,
  compaction, concurrency and execution records with fake models and tools.
- The not-wired chat modules have tests in `backend/tests/unit/onyx/chat/`. The
  storage modules have tests and migration tests in
  `backend/tests/external_dependency_unit/db/`. The runtime HTTP test in
  `backend/tests/external_dependency_unit/llm/` runs the runtime through real
  LiteLLM requests to a mock HTTP provider.

# Shared Agent Runtime

> A Python engine that runs chat, deep research, research and coding agents
> through model steps and parallel tools, with child agents, cancellation,
> compaction and suspension. This document is the one record of which chat
> adapters implement its interfaces, and which runtime features no product path
> reaches.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## Callers

**Interface.** A caller creates an `Agent` with an `LLM` and a
`GenerationContext` that names an `LLMFlow`, starts a `Run`, and reads typed
events and a `RunResult`. Tools receive a `ToolInvocation` and can start child
agents through it. The application supplies storage and ownership through the
`RunStore`, `RunOwnership` and `AgentDirectory` interfaces.
`backend/onyx/agents/README.md` is the full contract: run lifecycle, events,
child agents, compaction, saving and restoring, and the chat integration. This
document does not repeat it.

**Who calls it.**
- [[core-chat-loop]]: `chat/execution.py:create_chat_agent` builds a
  `ChatAgent` or a `DeepResearchAgent` for each response, and the response
  thread starts it.
- **Child agents.** The deep research step starts
  `deep_research/research_agent.py:ResearchAgent`, and the coding agent tool
  starts `coding_agent/agent.py:CodingAgent`, through
  `ToolInvocation.agents.spawn_agent`.
- [[tools-framework]]: `tools/interface.py:Tool.bind` turns each chat `Tool`
  into an `AgentTool`.
- **A backend developer who builds a feature on the runtime.** Start from the
  package README and [[#run-by-hand]].

**What a caller must keep:** [[#result-before-storage]],
[[#restored-tools-must-match]], [[#context-captured-at-start]],
[[#run-input-protected]] and [[#stable-message-ids]].

---

## Scope

This component owns the runtime package: agents, runs, steps, tool scheduling,
child coordination, compaction, events and execution records. It also owns the
record of how chat implements the runtime's interfaces and which runtime
features are not wired.

Neighbours: [[core-chat-loop]] owns the turn, the chat agent's step policy and
the chat adapters' use in a turn. [[chat-persistence]] owns the tables and the
history stores that the adapters write. [[llm-providers]] owns the `LLM`
interface that the runtime calls. [[context-assembly]] owns what each chat
prompt holds and the compaction prompt text.

---

## Architecture

```
Agent (history, checkpoint, registered tools, prepare_step / after_step hooks)
  start() -> Run (one request, step budget, own cancellation signal)
    step: prepare_step -> _compact_context -> model generation
          -> ToolBatch (parallel, ordered results) -> after_step: continue or finish
  AgentCoordinator: children, RunStore / RunOwnership / AgentDirectory adapters
  handoff(save=...) -> ExecutionCheckpoint -> Agent.resume(snapshot) elsewhere
```

- `backend/onyx/agents/runtime.py` holds `Agent`, `Run` and the step loop
  (`_advance_step`).
- `backend/onyx/agents/runtime.py:_compact_context` fits each request before the
  model call: it applies the saved checkpoint, summarizes through
  `agents/compaction.py:compact_history` above the trigger, and falls back to
  `_truncate_context`. It runs for every agent, child and model of a turn. A
  provider context-limit error before any output streams compacts and retries
  once.
- `backend/onyx/agents/tool_execution.py:ToolBatch` schedules a step's tools and
  records results in model-call order.
- `backend/onyx/agents/agent_coordination.py:AgentCoordinator` runs children and
  calls the application's storage and ownership adapters.
- `backend/onyx/agents/execution_records.py:messages_for_model` filters history
  for the model. It drops incomplete tool exchanges and thinking that cannot be
  replayed. Recorded output stays intact.

**Chat adapters.** This table is the one record of how chat plugs in.

| Runtime interface | Chat implementation |
|---|---|
| `RunStore` | `chat/persistence.py:ChatResponsePersistence` saves the root response. In a session that keeps content, `chat/run_store.py:ChatRunStore` wraps it and also saves child runs. |
| `RunOwnership` | `ChatRunStore`, with cache leases that the turn's control thread renews. A content-free incognito run keeps local ownership only. |
| `AgentDirectory` | `chat/subagents.py:ChatAgentDirectory`, limited to the selected branch. |
| Event listener | `chat/presentation.py:ResponsePresenter`. |
| `RestorableFeature` | `ChatAgent`, `DeepResearchAgent` and `ResearchAgent`. `chat/restoration.py:restore_chat_agent` rebuilds them. |
| `AgentTool` | `tools/interface.py:Tool.bind`. |

**Not wired.** No product code calls `Run.suspend`, returns a pending input
request from a tool, or calls `ChatRunStore.handoff` or `ChatRunStore.resume`.
Only tests do. So `chat/checkpoint.py`, the publish and claim functions in
`db/chat_checkpoint.py`, and `ChatResponseCheckpoint` rows are reached only by
tests. A saved run still checks the checkpoint owner on every save. To check
again, run `git grep -n "\.handoff(\|\.suspend()\|PendingToolInput" -- backend/onyx ':!backend/onyx/agents'`.

---

## Contracts and traps

1. `result-before-storage` **`run.result()` can return before storage and
   cleanup finish.** Wait on
   `backend/onyx/agents/agent_coordination.py:AgentCoordinator.completion` for
   saved completion; a storage or cleanup failure shows there, not in
   `run.result()`. Wait on `backend/onyx/agents/runtime.py:Run.wait_for_idle`
   before reuse or handoff. The table in the package README lists what each
   wait means.
2. `no-side-effect-wiring` **Do not reach suspension or checkpoint transfer from
   a product path as a side effect.** A tool that returns a pending input
   request, or a caller of `Run.suspend` or `ChatRunStore.handoff`, makes that
   path live without review of its storage, ownership and display. Update the
   Not wired paragraph in the same change ([[#wire-module]]).
3. `restored-tools-must-match` **A restored run needs the same tools and
   configuration.** A checkpoint holds data only. It does not serialize clients,
   callbacks or other resources, so the new owner rebuilds them, possibly in
   another process or after a deploy. Each tool's definition must equal the
   saved step's declaration, or `backend/onyx/agents/runtime.py:_execute_tools`
   raises `ValueError`. `chat/agent.py:ChatAgent.restore_state` also raises when
   the saved prompt, files, memory or settings differ. Keep a tool's definition
   stable while saved checkpoints can still resume.
4. `context-captured-at-start` **A run copies the caller's context when it
   starts.** `backend/onyx/agents/runtime.py:Run._start` calls `copy_context()`,
   and the run's worker threads use that copy. So set the tenant and open the
   root trace before `Agent.start` or `Agent.resume`. A trace that opens later,
   or a tenant that a tool sets, does not reach the run. A Celery task or a
   process that resumes a checkpoint ([[#restored-tools-must-match]]) must do
   both first ([[multi-tenancy#threads-copy-context]],
   [[observability#root-trace-required]]).
5. `run-input-protected` **Pass the whole current input in one `start` call.**
   The question, its attachment text and request context go in
   `start(messages=...)`. Compaction and truncation never cut that group, and
   input that cannot fit fails the run with
   `agents/compaction.py:ContextLimitError` instead of losing an attachment. Text
   put in the agent's history instead can be summarized away. Chat splits the
   two in `chat/process_message.py:prepare_chat_turn` (`input_messages`).
6. `stable-message-ids` **Message IDs must be stable across reloads.** A
   compaction checkpoint names its cutoff by message ID
   (`covered_through_message_id`). When the cutoff is absent from reloaded
   history, or splits a tool call from its result,
   `agents/compaction.py:checkpoint_boundary` rejects it and the runtime
   silently drops the summary. Chat builds IDs such as `chat:<message id>` in
   `chat/chat_utils.py`; a change to that scheme discards every saved summary.
   Mark request-only messages with `allow_compaction_cutoff=False`.
7. `run-id-is-message-id` **A durable chat run ID is the assistant message ID.**
   The run ID is the reserved `ChatMessage.id` as a string, and child responses
   are reserved before their runs start. `ChatRunStore` and the Postgres history
   store refuse IDs that are not decimal. Standalone and content-free incognito
   runs use generated IDs.

---

## Decisions

- **The runtime holds no chat code.** Applications supply the model,
  instructions, tools and storage adapters (package README). The chat display,
  citation and persistence adapters live in the chat and database modules.
- **Storage and ownership are interfaces** (`RunStore`, `RunOwnership`,
  `AgentDirectory`), so each application chooses its durability and
  authorization.
- **Compaction belongs to each run, not to the turn.** Each agent fits its own
  request against its own model, so a comparison turn and child agents need no
  shared compaction step.

---

## Known issues

- **Total generation deadlines are checked between stream events.** They do not
  interrupt a blocked synchronous provider read, so cancellation and timeouts
  wait for the read to return or time out.

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

- `run-by-hand` **Run the runtime by hand.** Copy the "Quick start" example in
  `backend/onyx/agents/README.md`. For a run against a fake model and fake tools,
  copy `backend/tests/unit/onyx/agents/fakes.py`. For real LiteLLM requests to a
  mock HTTP provider, copy
  `backend/tests/external_dependency_unit/llm/test_agent_runtime_http.py`.
- `new-feature` **Build a new feature on the runtime.** Start from
  [[#run-by-hand]], then settle these:
  - Inside chat, copy `coding_agent/agent.py:CodingAgent` and the tool that
    starts it as a child (`tools/tool_implementations/coding_agent/coding_agent_tool.py`).
    The chat adapters then save it and own it.
  - Outside chat, only tests implement `RunStore`, `RunOwnership` and
    `AgentDirectory` without chat storage
    (`backend/tests/unit/onyx/agents/fakes.py`). Children and durable completion
    need adapters of your own.
  - Chat tools reach the runtime through `Tool.bind`. A plain `AgentTool` is
    enough for a feature-only tool.
  - A run that a user starts is an LLM entry point and needs the budget checks.
- `wire-module` **Wire suspension or checkpoint transfer into a product path.**
  Add an integration test that suspends, hands off and resumes a real turn on
  another process, compare its packets with the live stream
  ([[streaming-protocol]]), update the Not wired paragraph, and update the
  [[core-chat-loop]] and [[chat-persistence]] documents in the same change.

---

## Verification

- Unit: `backend/tests/unit/onyx/agents/` covers lifecycle, child coordination,
  compaction, checkpoints, restoration and execution records with fake models
  and tools. `backend/tests/unit/onyx/chat/` covers the chat agent and adapters.
- External dependency: `backend/tests/external_dependency_unit/chat/test_run_store.py`
  covers ownership, handoff and resume against the real cache and database.
  `backend/tests/external_dependency_unit/db/` covers response storage and
  checkpoint rows. `backend/tests/external_dependency_unit/llm/` runs the runtime
  through real LiteLLM requests to a mock HTTP provider, and
  `backend/tests/external_dependency_unit/llm/test_agent_compaction.py` calls a
  real provider.

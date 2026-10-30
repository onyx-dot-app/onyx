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
  thread starts it with `background=False` ([[#context-captured-at-start]]).
- **Child agents.** The deep research step starts
  `deep_research/research_agent.py:ResearchAgent`, and the coding agent tool
  starts `coding_agent/agent.py:CodingAgent`, through
  `ToolInvocation.agents.spawn_agent`. The tool returns a `ChildRunWait` and
  sets `result_from_children` instead of blocking, and the parent run suspends
  until the child ends.
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
Agent (history, checkpoint, tools, prepare_step / after_step,
       before_tool_call / after_tool_call hooks)
  start() -> Run (one request, step budget, own cancellation signal)
    step: prepare_step -> _compact_context -> model generation
          -> ToolBatch -> after_step: continue or finish
          ToolBatch only waits on ChildRunWait -> _suspend (capture_state)
            -> child ends -> _wake_execution on a new "agent-run" thread
  AgentCoordinator: children, RunStore / RunOwnership / AgentDirectory adapters
  handoff(save=...) -> ExecutionCheckpoint -> Agent.resume(snapshot) elsewhere
```

- `backend/onyx/agents/runtime.py` holds `Agent`, `Run` and the step loop
  (`_advance_step`).
- `backend/onyx/agents/runtime.py:_compact_context` fits each request before the
  model call: it applies the saved checkpoint and summarizes through
  `agents/compaction.py:compact_history` above the trigger. If the summary
  fails while the request still fits the input limit, it sends the request
  unchanged. `_truncate_context` runs only when the request, or the summarized
  request, does not fit. It runs for every agent, child and model of a turn. A
  provider context-limit error before any output streams compacts and retries
  once.
- `backend/onyx/agents/tool_execution.py:ToolBatch` runs a step's calls in
  parallel. `ToolExecutionMode.SEQUENTIAL` serializes calls to one tool name,
  and `merge_arguments` merges compatible calls into one worker. It records
  results as they complete. Each pass of `ToolBatch.execute` then ends the
  completed calls in call order, and model history replays them in call order. A step with more than `MAX_TOOL_CALLS_PER_STEP` (64) calls or a
  repeated call ID fails the whole run.
- `backend/onyx/agents/agent_coordination.py:AgentCoordinator` runs children and
  calls the application's storage and ownership adapters.
- `backend/onyx/agents/execution_records.py:messages_for_model` filters history
  for the model. It drops incomplete tool exchanges, orphaned results, calls
  that repeat an ID in one message (with their results) and thinking that
  cannot be replayed. Recorded output stays intact.

**Chat adapters.** This table is the one record of how chat plugs in.

| Runtime interface | Chat implementation |
|---|---|
| `RunStore` | `chat/persistence.py:ChatResponsePersistence` saves the root response at the end and skips child runs. In a session that keeps content, `chat/run_store.py:ChatRunStore` wraps it: it saves the parent's partial record before each child reservation and saves each child when it ends. In a content-free incognito session no adapter saves children. |
| `RunOwnership` | `ChatRunStore`, with cache leases that the turn's control thread renews. A content-free incognito run keeps local ownership only. |
| `AgentDirectory` | `chat/subagents.py:ChatAgentDirectory`, limited to the selected branch. |
| Event listener | `chat/presentation.py:ResponsePresenter`. |
| `RestorableFeature` | `ChatAgent`, `DeepResearchAgent` and `ResearchAgent`. Product calls only `capture_state`, at each suspension. `chat/restoration.py:restore_chat_agent` rebuilds them for `ChatRunStore.resume`. |
| `AgentTool` | `tools/interface.py:Tool.bind`. |

**Live and not wired.** In-process suspension is live: deep research and the
coding agent suspend the parent on `ChildRunWait`, and it continues in the same
process. No product code calls `Run.suspend`, `Run.submit` or
`ToolInvocation.agents.start_run`, returns a `PendingToolInput`, or calls
`ChatRunStore.handoff` or `ChatRunStore.resume`. Only tests do.
`chat/execution.py` binds `restore_chat_agent` into `ChatRunStore` on every
content-persisting turn, but only the unwired `ChatRunStore.resume` calls it. So
`chat/checkpoint.py`, `chat/restoration.py`, `RestorableFeature.restore_state`,
`chat/subagents.py:ChatAgentDirectory.restore_agent`, and the publish and claim
functions in `db/chat_checkpoint.py` run only in tests, and no product
path creates a `ChatResponseCheckpoint` row. Product saves still lock the
response, check the checkpoint owner and delete any row at a terminal status.
To check again, run
`git grep -n "\.handoff(\|\.suspend()\|\.resume(\|\.submit(\|start_run(\|PendingToolInput" -- backend/onyx ':!backend/onyx/agents' ':!backend/onyx/chat/run_store.py'`
and ignore thread-pool `submit` calls; expect no runtime matches.

---

## Contracts and traps

1. `result-before-storage` **`run.result()` can return before storage and
   cleanup finish.** Wait on
   `backend/onyx/agents/agent_coordination.py:AgentCoordinator.completion` for
   saved completion; only a storage failure shows there. Wait on
   `backend/onyx/agents/runtime.py:Run.wait_for_idle` before reuse or handoff;
   it raises when ownership release fails, and returns `False` on timeout.
   Neither failure shows in `run.result()`. The table in the package README lists what each
   wait means.
2. `no-side-effect-wiring` **Do not reach human input or checkpoint transfer
   from a product path as a side effect.** A tool that returns a
   `PendingToolInput`, or a caller of `Run.suspend`, `ChatRunStore.handoff` or
   `ChatRunStore.resume`, makes that path live without review of its storage, ownership and display. Update the
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
   or a tenant that a tool sets, does not reach the run. `start(background=False)`
   returns at the first suspension, not at completion: in a deep research or
   coding-agent turn, chat's `with trace(...)` block in
   `chat/execution.py:ChatTurnExecution._run_response` closes while children
   and later parent steps still run on copied context. A Celery task or a
   process that resumes a checkpoint ([[#restored-tools-must-match]]) must do
   both first ([[multi-tenancy#threads-copy-context]],
   [[observability#root-trace-required]]).
5. `run-input-protected` **Pass the whole current input in one `start` call.**
   The question, its attachment text and request context go in
   `start(messages=...)`. Compaction and truncation keep that group until the
   model's first step in the run answers it, and input that cannot fit fails the
   run with `agents/compaction.py:ContextLimitError` instead of losing an
   attachment. Later steps can summarize or cut the attachment text; only the
   latest user message stays verbatim. Text put in the agent's history can be
   summarized away at any step. Chat splits the
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
   store refuse IDs that are not decimal. A root run needs the chat session ID
   as its agent ID and an assistant response with no status, so each response
   starts one run. A saved child needs exactly one `UserMessage` as input. Standalone and content-free incognito
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
    Return `ChildRunWait`, set `result_from_children`, and release held
    resources through `agents.add_completion_cleanup`. The chat adapters then
    save and own the child for one run, except in content-free incognito. To
    restore or rerun it, add a `restoration_config`, a `RestorableFeature` and a
    branch in `ChatAgentDirectory.restore_agent` and `restore_chat_agent`.
    `restore_agent` rebuilds only `ResearchAgent`; `restore_chat_agent` rebuilds
    `ChatAgent`, `ResearchAgent` and `DeepResearchAgent`. Neither rebuilds
    `CodingAgent`.
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
  `ChatRunStore.handoff` accepts only a `SUSPENDED`, idle run whose child runs
  are all terminal (else `RunNotTransferable`), and it needs the live owner, so
  hand off before the process exits, for example on graceful shutdown. A crash
  in the middle of a tool call leaves no checkpoint, so it cannot resume and
  needs a rerun policy. The new trigger (startup recovery or the next request)
  must call `ChatRunStore.resume` with a bound coordinator and the rebuilt agent
  state; nothing claims checkpoints on its own.

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

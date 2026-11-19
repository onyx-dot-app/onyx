# Shared Agent Runtime

> A Python engine that runs chat and research agents
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
  `deep_research/research_agent.py:ResearchAgent` through
  `ToolInvocation.agents.spawn_agent`. The tool returns a `ChildRunWait` and
  sets `result_from_children` instead of blocking, and the parent run suspends
  until the child ends.
- **Independent children.** ChatAgent and its children expose controls from
  `tools/tool_implementations/subagents/subagent_tools.py` to spawn, list, message, and interrupt children. Incognito chats have no child agents: they omit these controls,
  and deep research. Children survive
  the root response. A subagent must incorporate the results of children it spawns before
  completing; `RunOwnership.delegated_runs` lists the unread ones. `WAIT_CHILDREN` releases its execution thread while results are pending and reserves
  the last model step for synthesis. Dependencies belong to the current run, not the
  agent's entire history. Failure and cancellation remain terminal outcomes.
  Later turns use the branch-scoped directory and run store to access children. Before a model
  call the runtime reads submitted messages and finished child results through
  `RunOwnership.receive_inputs`; chat reads both with one query and formats results with
  `chat/run_store.py:agent_result_message`. `RunOwnership.accept_inputs` marks them read. Results reach only the
  spawner; any agent in the visible tree can message another, and messages to the root never
  start a root run. Chat can remap citations through `PreparedStep.input_messages`.
  Each input message between steps must carry `InputMessageMetadata` or be input
  context (`agents/compaction.py:is_input_context`), such as the `<skill>`
  message after a send that picked a skill (`chat/models.py:accepted_input_messages`);
  the runtime rejects other messages. Accepted inputs retain their identity and source in saved history.
  `MessageStartEvent.input_messages` contains the inputs durably accepted by
  that step; it excludes instructions still queued or withdrawn before acceptance.
  `send_message` stores the instruction through `RunOwnership.submit_message`; it targets the next step or starts
  an idle child with fresh limits. Messaging requires run ownership.
  `send_message(delivery="queue")` waits for normal completion or the step limit; Stop and failure
  pause queued work. `interrupt_agent` cancels one agent's active run, including its in-flight
  tool calls and foreground children; agents it started in the background keep running. The run
  reports no result (`RunOwnership.withdraw_result`), and its conversation remains. The caller
  and the root cannot be interrupted. `list_agents` shows unfinished agents and agents of the
  current user turn, and marks the caller; `include_finished` lists the whole branch tree.
  Chat starts a follow-up response when an idle parent has unread child results; a root
  `wait_agents` call batches them ([[chat-persistence]], `db/chat_inputs.py:wakes_for_results`).
  Queued messages and follow-ups start through one entry,
  `AgentCoordinator.start_message_run`, which restores the agent through its
  spawner whoever sent the work.
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
       before_tool_call / after_tool_call / on_finish / on_suspend /
       on_drained hooks)
  start() -> Run (one request, step budget, own cancellation signal)
    step: prepare_step -> _compact_context -> model generation
          -> ToolBatch -> after_step: continue or finish
          ToolBatch waits on ChildRunWait, PendingToolInput and NestedInputWait
            -> _suspend (on_suspend amendments, capture_state)
            -> child ends -> _wake_execution on a new "agent-run" thread
  AgentCoordinator: children, RunStore / RunOwnership / AgentDirectory adapters
  handoff(save=...) -> ExecutionCheckpoint -> Agent.resume(snapshot) elsewhere
  end of run: on_finish(results) -> ToolResultAmendment list
            -> recorded results replaced, ToolResultAmendedEvent each
            -> AgentEndEvent -> save
```

- `backend/onyx/agents/runtime.py` holds `Agent`, `Run` and the step loop
  (`_advance_step`). `Agent.start(max_steps=...)` sets the step budget; chat
  passes `ChatAgent.max_steps`: `MAX_LLM_CYCLES`, or `CODE_MODE_MAX_LLM_CYCLES`
  when code mode applies (`ChatAgent.code_cells` is set).
- `Agent.on_finish` runs once at the end of every run, without the execution
  lock, with the run's recorded tool results.
  `backend/onyx/agents/runtime.py:Run._release_amendments` collects its
  `agents/models.py:ToolResultAmendment` list, and `Run._apply_amendments`
  sets those results and publishes `ToolResultAmendedEvent` for each,
  after the partial messages end and before `AgentEndEvent` and the save. An
  amendment can also give a call that Stop interrupted its result. An
  amendment that names no started call is logged and skipped. An amendment
  inside the span of the compaction checkpoint drops the checkpoint, so the
  next request builds its context from the amended result, and compacts only
  when that context is over budget. A hook that fails or stops for
  cancellation sets no results; the run still ends.
  The tool phase suspends only when the run is idle; the rule is at
  `ToolInvocation.run_work` (`agents/tools.py`), and
  `agents/tool_execution.py:ToolBatch.execute` waits on
  `ExecutionWork.held`.
  Open requests of calls that tools made for the model stay open while the
  run suspends (`RunProgress.open_inputs`); `ToolBatch._continue_open_inputs`
  gives their answers to `AgentTool.continue_open_input`.
  `Agent.on_suspend` runs before each suspension; `Run._suspend` applies its
  amendments before it captures state. A suspend hook that fails sets no
  results and the run still suspends. A suspend hook that stops for
  cancellation finishes the run as cancelled. Chat uses both hooks to close
  code mode cells ([[code-execution#code-mode-interrupted-run]]).
  `Agent.on_drained` runs after each finish or suspension once the run's work
  drains (`Run._work_drained`, from `_drain_workers` and `_suspend`): its tool
  threads, work that a tool added through `ToolInvocation.run_work` (a code
  mode cell's driver, and its tool call threads through `track_detached`), and its foreground
  children's work (`Run.track_child_work`), not background children. A suspension calls it only when no foreground child
  waits or works (`RunCoordination.pending_children`,
  `AgentCoordinator.children_idle`, read only); otherwise the run's later end does.
  A run that hands off in that state calls no hook; the restoring owner's
  run end does. It cannot change results. Errors, `AgentCancelled`
  included, are logged and the run still becomes idle and reusable. Only the
  root `chat/agent.py:ChatAgent` installs it, to end per-run tool state
  (`create_chat_agent` passes it to the root only), such as the sandbox turn
  ([[code-execution]]); subagents share the root's tools and install none.
  `chat/presentation.py:ResponsePresenter` renders each amendment with
  `chat/renderer.py:ToolRenderer.amend`. A call without an ended card
  completes with the amended result. An ended card renders only what the
  amendment added (`_amendment_packets`), after its section end; the generic
  display adds nothing. `ToolRenderer.complete` renders that part after the
  section end too. Live, the closing record follows the answer; replay places
  it before the answer's `message_start`. Both orders give the same groups.
- `backend/onyx/agents/runtime.py:_compact_context` fits each request before the
  model call: it applies the saved checkpoint and summarizes through
  `agents/compaction.py:compact_history` above the trigger. If the summary
  fails while the request still fits the input limit, it sends the request
  unchanged. `_truncate_context` runs only when the request, or the summarized
  request, does not fit. It runs for every agent, child and model of a turn. A
  provider context-limit error before any output streams compacts and retries
  once.
- `backend/onyx/agents/tool_execution.py:ToolBatch` runs a step's calls in
  parallel. `ToolExecutionMode.SEQUENTIAL` serializes calls to one tool name, or
  to the tools of one `sequence_group`, and `merge_arguments` merges compatible calls into one worker. It records
  results as they complete. Each pass of `ToolBatch.execute` then ends the
  completed calls in call order, and model history replays them in call order. A step with more than `MAX_TOOL_CALLS_PER_STEP` (64) calls or a
  repeated call ID fails the whole run.
- `backend/onyx/agents/agent_coordination.py:AgentCoordinator` runs children and
  calls the application's storage and ownership adapters. Explicit discovery
  refreshes directory metadata so later turns can find newly spawned children.
- `backend/onyx/agents/execution_records.py:messages_for_model` filters history
  for the model. It drops incomplete tool exchanges, orphaned results, calls
  that repeat an ID in one message (with their results) and thinking that
  cannot be replayed. Recorded output stays intact.

**Chat adapters.** This table is the one record of how chat plugs in.

| Runtime interface | Chat implementation |
|---|---|
| `RunStore` | `chat/persistence.py:ChatResponsePersistence` saves the root response at the end and skips child runs. In a session that keeps content, `chat/run_store.py:ChatRunStore` wraps it: it saves the parent's partial record before each child reservation and saves each child when it ends. Incognito sessions have no children. |
| `RunOwnership` | `ChatRunStore`, with cache leases that the turn's control thread renews. It also owns the inbox: received inputs, unread results, withdrawn results and submitted messages. A `FULL_HISTORY` incognito run also has it; a `USAGE_ONLY` incognito run has no run ownership. |
| `AgentDirectory` | `chat/run_store.py:ChatRunStore`, limited to the selected branch of a chat that keeps content, including a `FULL_HISTORY` incognito chat. It lists the branch's agent tree and accepts messages for any agent in it; lookup, restore, and run reads go through each agent's spawner. A `USAGE_ONLY` incognito run has no directory. |
| Event listener | `chat/presentation.py:ResponsePresenter`. |
| `RestorableFeature` | `ChatAgent`, `DeepResearchAgent` and `ResearchAgent`. Product calls only `capture_state`, at each suspension. `chat/restoration.py:restore_chat_agent` rebuilds them for `ChatRunStore.resume`. |
| `AgentTool` | `tools/interface.py:Tool.bind`. |

**Live paths.** Deep research suspends the parent on `ChildRunWait`. The parent continues in the same
process. Checkpoint transfer is live for chat tool approvals and the root's
questions: the runtime gates calls of `AgentTool.approval_required` through
the coordinator's `ToolApprovals`
(`chat/run_store.py:ChatRunStore.request_approval`), the question tool returns
a `RESULT` request (`chat/tool_questions.py:open_tool_question`), and any run
whose waits are all on people hands off in one park pass of
`ChatRunStore.poll_control` after `ChatRunStore.may_park`, the root included;
the root reports its park to its turn through the store's `on_root_parked`
callback. A parent
hands off after its waiting foreground children hand off
(`agents/agent_coordination.py:RunCoordination.validate_handoff`). Decisions
resume each run on any pod through chat dispatch (`ChatRunStore.resume` with
the saved answers), the leaf first
([[mcp-and-custom-tools#chat-approval-durable-wait]]). A code mode program's
call waits in a saved `NestedInputWait`
([[mcp-and-custom-tools#program-call-waits-in-cell]]). No product code calls
`Run.suspend`. Only a user Stop calls `Run.submit`:
`ChatRunStore.reject_waiting_inputs` gives each live run that the Stop
cancels its saved rejections and question cancellations, then cancels it,
under the run's execution lock. `chat/run_store.py:ChatRunStore.restore_agent`
loads a saved child for a new run, and `chat/restoration.py:restore_subagent`
rebuilds it with the current request's tools and settings. Product saves lock
the response, check the checkpoint owner and delete any row at a terminal
status.
To check again, run
`git grep -n "\.handoff(\|\.suspend()\|\.resume(\|\.submit(\|PendingToolInput" -- backend/onyx ':!backend/onyx/agents' ':!backend/onyx/chat/run_store.py'`
and ignore thread-pool and job `submit` calls and the code mode `resume`
calls (`state.resume`, `CodeCells.resume`). Expect only `chat/execution.py`
(`resume`), `chat/tool_approvals.py:open_tool_approval` and
`chat/tool_questions.py:open_tool_question`.

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
   from a product path as a side effect.** A new tool, hook or `ToolApprovals`
   that returns a `PendingToolInput`, or a caller of `Run.suspend`, `ChatRunStore.handoff` or
   `ChatRunStore.resume`, makes that path live without review of its storage, ownership and display.
   Chat tool approvals and the root's question tool are the reviewed sources
   of `PendingToolInput`; a new source needs its own saved requests and
   resume trigger, as
   [[mcp-and-custom-tools#chat-approval-durable-wait]] has. Update the
   Live paths paragraph in the same change ([[#wire-module]]).
3. `restored-tools-must-match` **A restored run needs the same tools and
   configuration.** A checkpoint holds data only. It does not serialize clients,
   callbacks or other resources, so the new owner rebuilds them, possibly in
   another process or after a deploy. A saved call runs only when the agent
   still has its tool with the same `parameters` schema
   (`backend/onyx/agents/runtime.py:_execute_tools`); an approved call whose
   tool is gone or changed gets `agents/tool_execution.py:UNAVAILABLE_CALL_MESSAGE`,
   and later steps use the current tools. Descriptions, other tools, their
   order and phases can differ. Saved execution permissions are separate from
   advertised definitions; restoration must not enable a tool merely because it
   was advertised, and it drops permitted names that the agent lacks.
   `chat/agent.py:ChatAgent.restore_state` also raises when
   the saved prompt, files, memory or settings differ.
4. `context-captured-at-start` **A run copies the caller's context when it
   starts.** `backend/onyx/agents/runtime.py:Run._start` calls `copy_context()`,
   and the run's worker threads use that copy. So set the tenant and open the
   root trace before `Agent.start` or `Agent.resume`. A trace that opens later,
   or a tenant that a tool sets, does not reach the run. `start(background=False)`
   returns at the first suspension. In a deep research turn, chat's `with trace(...)` block in
   `chat/execution.py:ChatTurnExecution._run_response` closes while children
   and later parent steps still run on copied context. A Celery task or a
   process that resumes a checkpoint ([[#restored-tools-must-match]]) must do
   both first ([[multi-tenancy#threads-copy-context]],
   [[observability#root-trace-required]]).
5. `run-input-protected` **Pass the whole current input in one `start` call.**
   The question and its attachment text go in
   `start(messages=...)`, with the question after its attachments. The
   `<skill>` messages of the question's picked skills follow it: they are
   recorded input context (`CompactionMetadata.is_input_context`), not a
   user turn, so compaction never takes one as the task.
   Chat supplies request-only context through prompt assembly, outside compacted history.
   Compaction and truncation keep the input group until the
   model's first step in the run answers it, and input that cannot fit fails the
   run with `agents/compaction.py:ContextLimitError` instead of losing an
   attachment. Later steps can summarize or cut the attachment text;
   only the latest user message, the question, stays verbatim. Text put in the agent's history can be
   summarized away at any step. Chat splits the
   two in `chat/process_message.py:prepare_chat_turn` (`input_messages`).
6. `stable-message-ids` **Message IDs must be stable across reloads.** A
   compaction checkpoint names its cutoff by message ID
   (`covered_through_message_id`). When the cutoff is absent from reloaded
   history, or splits a tool call from its result,
   `agents/compaction.py:checkpoint_boundary` rejects it and the runtime
   silently drops the summary. Chat builds IDs such as `chat:<message id>` in
   `chat/chat_utils.py`; a change to that scheme discards every saved summary.
   Keep transient request context outside recorded history. [[context-assembly]]
   owns its placement in the uncached suffix, separate from summary input.
7. `run-id-is-message-id` **A durable chat run ID is the assistant message ID.**
   The run ID is the reserved `ChatMessage.id` as a string, and child responses
   are reserved before their runs start. `ChatRunStore` and the Postgres history
   store refuse IDs that are not decimal. A root run needs the chat session ID
   as its agent ID and an assistant response with no status, so each response
   starts one run. A saved child needs exactly one `UserMessage` as input. Standalone and content-free incognito
   runs use generated IDs.
8. `deadline-cause` **Run deadlines preserve cancellation cause.**
   `Agent.start(deadline_at=...)` saves the deadline in `RunProgress`. A deadline
   cancellation records `RunFailureKind.DEADLINE` and publishes it on
   `AgentEndEvent`. The first cancellation signal wins, so a later deadline
   cannot relabel a user Stop.

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
  - For a child inside chat, see `deep_research/agent.py:DeepResearchAgent` and
    the `ResearchAgent` it starts.
    Return `ChildRunWait` and set `result_from_children`. The chat adapters then
    save and own the child for one run. Incognito chats have no children. To
    rerun it, add a `restoration_config` and a branch in
    `chat/restoration.py:restore_subagent`. `ChatRunStore` authorizes and
    loads saved history; this factory rebuilds Chat and Research children with
    the current request's authorized resources. For suspended execution, add
    a `RestorableFeature` and a branch in `restore_chat_agent`, which rebuilds
    Chat, Research and DeepResearch agents.
  - Outside chat, only tests implement `RunStore`, `RunOwnership` and
    `AgentDirectory` without chat storage
    (`backend/tests/unit/onyx/agents/fakes.py`). Children and durable completion
    need adapters of your own.
  - Chat tools reach the runtime through `Tool.bind`. A plain `AgentTool` is
    enough for a feature-only tool.
  - A run that a user starts is an LLM entry point and needs the budget checks.
- `wire-module` **Wire suspension or checkpoint transfer into another product path.**
  Add an integration test that suspends, hands off and resumes a real turn on
  another process, compare its packets with the live stream
  ([[streaming-protocol]]), update the Live paths paragraph, and update the
  [[core-chat-loop]] and [[chat-persistence]] documents in the same change.
  `ChatRunStore.handoff` accepts only a `SUSPENDED`, idle run whose child runs
  have ended or parked (else `RunNotTransferable`), and it needs the live owner, so
  hand off as soon as the run suspends, as chat approvals do. A crash in the
  middle of a tool call leaves no checkpoint, so it cannot resume and needs a
  rerun policy. The trigger must call `ChatRunStore.resume` with a bound
  coordinator and the rebuilt agent state, as chat dispatch does for
  approvals; nothing claims checkpoints on its own.

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

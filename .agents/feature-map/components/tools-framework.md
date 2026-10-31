# Tools Framework

> The shared machinery for every tool the chat model can call: the `Tool`
> interface, the built-in tool registry, per-model tool construction and gating,
> and the research and coding sub-agents. Concrete tools live in their own
> components; this one owns the rules that they all depend on.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## Callers

The interface is `tools/interface.py:Tool`, which returns
`llm/models.py:ToolResult`, and `tools/tool_constructor.py:construct_tools`.
`Tool.bind` adapts a tool to the runtime's `agents/tools.py:AgentTool`, and
`agents/tool_execution.py:ToolBatch` ([[agent-runtime]]) runs it.

- **A developer who adds a tool** subclasses `Tool`, registers it, and attaches
  it to an agent. Keep [[#built-in-needs-constructor-branch]],
  [[#is-available-cheap-and-silent]], [[#run-errors-become-results]],
  [[#renderer-dispatches-by-name]], [[#durable-details-registered]],
  [[#parallel-by-default]], [[#tool-name-is-lookup-key]] and
  [[#child-wait-cleanup]]. Checkpoint resume is not wired ([[agent-runtime]]).
  When it is, a change to `tool_definition()` stops saved checkpoints from
  resuming ([[agent-runtime#restored-tools-must-match]]). The concrete tools are
  [[internal-search]], [[web-search]], [[image-generation]],
  [[code-execution]], [[mcp-and-custom-tools]], [[chat-preferences]]
  (`MemoryTool`) and [[file-store-and-user-files]] (`read_file`).
- **[[core-chat-loop]]** calls `construct_tools` once per model response and
  gives the tools to `chat/agent.py:ChatAgent` or
  `deep_research/agent.py:DeepResearchAgent`. `ChatAgent` binds them with its
  own `ToolContext`.
- **The sub-agents** run on the same runtime. `DeepResearchAgent` does not bind
  the tools. It passes them to each
  `deep_research/research_agent.py:ResearchAgent` child, which binds them with
  its own `ToolContext`. `coding_agent/agent.py:CodingAgent` calls `BashTool.run` from its own
  `AgentTool`, so `Tool.run` error handling applies but no construction gate
  does ([[code-execution#errors-are-results]]).
- **[[citations]]** gets a block of citation numbers per search-like call.

---

## Scope

This component owns the `Tool` interface and `ToolContext`, tool construction
and its gates, the built-in tool registry, the research-agent and coding-agent
features, and the `CodingAgentTool` wrapper.

Neighbours own the rest:
- Each concrete tool belongs to the component listed in Callers.
- [[agent-runtime]] owns tool scheduling, argument merging, execution modes,
  child-run waits and the chat renderers that turn tool events into packets.
- [[mcp-and-custom-tools]] owns the tool HTTP API, the `Tool` table helpers,
  the OpenAPI and MCP tool classes, and MCP credential resolution.
- [[plugins]] owns Default Chat tool selection and the per-user tool
  preferences that construction reads.
- [[core-chat-loop]] owns the turn, the stopping-tool rule, and how the
  sub-agents enter a turn.
- [[citations]] owns the meaning of the citation number blocks.
- [[chat-persistence]] owns how tool calls are saved and replayed, and which
  tool results reach later turns.
- [[web-search]] owns the rule that turning web search off for one message makes
  `open_url` index-only (`tools/tool_constructor.py:should_disable_open_url_web_fetch`).

---

## Architecture

```
chat/process_message.py:prepare_chat_turn    capture_persona_tool_configuration
                                             (db/tools.py) -> PersonaToolConfiguration
chat/execution.py:create_chat_agent          per model response
  construct_tools                            -> {Tool row id: [Tool instances]}
  ChatAgent / ResearchAgent                  Tool.bind(_tool_context) -> AgentTool
agents/runtime.py                            a model step returns tool calls
  agents/tool_execution.py:ToolBatch         merge -> run in parallel -> finalize
    Tool.run -> _invoke_tool -> Tool._run    trace, convert errors, check cancel
  ChatAgent._finalize_tool, ChatAgent._after_step
chat/presentation.py:ResponsePresenter       tool events -> chat/renderer.py:ToolRenderer
```

**Captured configuration.** `db/tools.py:capture_persona_tool_configuration`
copies the agent's `Tool` rows into frozen `ToolConfiguration` models before the
run starts. `construct_tools` opens its own short DB session, so no session
stays open for a turn that can last minutes. MCP tool schemas come from the
captured `mcp_input_schema`, not from a live MCP call.

**Construction per model.** `chat/execution.py:create_chat_agent` calls
`construct_tools` for each model response, so a multi-model turn has separate
tool instances. `tools/tool_constructor.py:_construct_tools_impl` walks the
captured tools in order and applies these gates:

1. `server/features/tool/tool_visibility.py:is_tool_available_for_persona`. An
   MCP or built-in tool with `enabled=False` is skipped for every agent. An
   OpenAPI tool with `enabled=False` is skipped only in Default Chat.
2. `allowed_tool_ids`, the per-message list that the web client sends.
3. For a built-in tool, `is_available(db_session)`. An exception counts as "not
   available" and is logged.
4. A class-specific branch builds the instance, and some branches skip the
   tool with no error:
   - `SearchTool` is skipped when the search usage setting from
     `chat/files.py:determine_search_params` is `DISABLED`.
   - `OpenURLTool` is skipped when web search is off for the message and
     `DISABLE_VECTOR_DB` is set ([[web-search]]).
   - An OpenAPI tool with `oauth_config_id` or `passthrough_auth` is skipped
     for an anonymous user, with only a warning in the log.
   - OpenAPI and MCP rows go through their own branches
     ([[mcp-and-custom-tools]]). Both first apply the user's plugin
     preferences ([[plugins]]), which exist only for Default Chat
     (`DEFAULT_PERSONA_ID`). The MCP branch then applies
     `user_can_access_mcp_server` in Default Chat only
     ([[mcp-and-custom-tools#access-grants-default-chat-only]]), resolves
     credentials once per server, and builds every `MCPTool` of that server
     from the captured rows.

Two tools are added outside this loop. `SearchTool` is added when the request
forces search on (`SearchToolUsage.ENABLED`), `DISABLE_VECTOR_DB` is off, and
the loop did not build it. `MemoryTool` is added when `user.enable_memory_tool`
is set ([[#memory-tool-bypasses-filters]]). Last, `_disambiguate_mcp_tool_names`
renames MCP tools whose names collide.

**Execution.** A tool implements `_run(invocation, context)` and returns a
`ToolResult`, or a `ChildRunWait` when it delegates to a sub-agent. Call data,
such as arguments, `call_index`, the cancellation signal and the progress
callback, comes in `agents/tools.py:ToolInvocation`. `invocation.update` can
raise `AgentCancelled`; do not catch it. An update sent after `_run` returns is
dropped, and a result that arrives after the run closes is discarded.
Per-request data, such as chat files, memory and the next citation number,
comes in `tools/models.py:ToolContext`. `ChatAgent._tool_context` and
`ResearchAgent._tool_context` build it when the call starts.

When the run completes normally, every call gets a result: `ToolBatch` answers
an unknown tool name, malformed arguments or truncated arguments with an error
result. On Stop or a run failure, a running call ends with no result (status
`CANCELLED` or `ERROR`) and renders with no details. `_invoke_tool` discards a
result that finishes after cancellation. Side effects that the tool already
made are not undone, so check `invocation.cancellation` before irreversible
work.

**Sub-agents.** `DeepResearchAgent`, `ResearchAgent` and `CodingAgent` are
runtime agents. `DeepResearchAgent` and `CodingAgentTool` spawn a child run and
return `ChildRunWait`; the runtime calls `result_from_children` when the child
ends ([[#child-wait-cleanup]]). A step count bounds the coding agent, not time:
`CodingAgentTool` gives it `MAX_CODING_AGENT_CYCLES + 1` steps.
`coding_agent/agent.py:CodingAgent._prepare_step` forces a final answer step
with no tools on the last step, after a `generate_answer` call, or after a step
with no tool calls. Their control functions, such as `think_tool`, `generate_report` and
`generate_answer`, are plain `AgentTool` objects with no `Tool` row, and
`chat/renderer.py:HIDDEN_TOOLS` keeps them out of the stream.

---

## Contracts and traps

1. `memory-tool-bypasses-filters` **`MemoryTool` bypasses `allowed_tool_ids`
   and the agent's tools.** `tools/tool_constructor.py:_construct_tools_impl`
   adds it after the agent tool loop whenever `user.enable_memory_tool` is set.
   A user who turns every tool off for a message can still get a memory write.
   A change to per-message filtering must decide whether memory follows it.
   In an incognito turn the tool is still offered, but `MemoryTool._run`
   refuses the write when `get_current_incognito_record_mode()` is set. A new
   tool with durable side effects outside the file store must make the same
   check. File-store writes get the incognito cleanup stamp automatically
   ([[file-store-and-user-files]]).
2. `built-in-needs-constructor-branch` **A built-in tool without a constructor
   branch is silently dropped.** The `if/elif` chain in
   `tools/tool_constructor.py:_construct_tools_impl`
   has no `else`. A tool in `tools/built_in_tools.py:BUILT_IN_TOOL_MAP` with no
   branch passes `is_available` and then is never added. `KnowledgeGraphTool` is
   in this state on purpose (Known issues). The reverse also holds: an exception
   inside a branch is not caught, and it ends that model's answer. The web
   search, `open_url` and image generation branches raise when their provider
   is missing. Put each "cannot run here" check in
   `is_available`.
3. `is-available-cheap-and-silent` **`is_available` runs on every turn and must
   be cheap.** It runs once per attached built-in tool per model response. Cache
   remote checks, as
   `tools/tool_implementations/python/code_interpreter_client.py:CodeInterpreterClient.health`
   does with `use_cache=True`. An
   exception hides the tool and only logs, so a bug here looks like "the model
   never uses the tool".
4. `two-response-channels` **Keep the two `ToolResult` channels apart.**
   `llm/models.py:ToolResult.content` is the only text the model sees.
   `details` is a typed object that application code reads by type:
   `chat/agent.py:ChatAgent._update_tool_context` gathers documents and files
   from it, `ToolRenderer` draws it, and chat saves it. Put what the model needs
   in `content`. Some saved model text is itself a contract, such as the
   `run_python` result JSON ([[code-execution#run-python-result-json]]).
5. `run-errors-become-results` **`Tool._run` must not let errors stop the
   turn, and must let cancellation through.** `Tool.run` is final and wraps
   `_run` in `tools/interface.py:_invoke_tool`. A `ToolCallException` becomes an
   error result with its `llm_facing_message`; raise it for errors that the
   model can fix, such as bad arguments (`parse_tool_arguments` does this). Any
   other exception becomes "Tool failed with error: ..." with the exception
   text, which the model reads and chat saves. `Tool.bind` wraps
   `result_from_children` in the same conversion and span. `ToolBatch` also
   converts exceptions from bare `AgentTool` callbacks that have no `Tool.run`.
   Raise
   `ToolExecutionException(emit_error_packet=True)` when the user must see the
   error. Cancellation is `llm/cancellation.py:AgentCancelled`, a
   `BaseException`: never catch `BaseException` in a tool.
6. `section-end-always` **Every rendered tool block ends with a `SectionEnd`
   packet.** Tools emit no packets. `chat/renderer.py:ToolRenderer.complete`
   appends `SectionEnd` on every path, and
   `chat/presentation.py:ResponsePresenter.consume` completes each open tool
   when its run ends. The frontend closes the tool block on it. Do not add a
   return path that skips it.
7. `renderer-dispatches-by-name` **A tool's packets come from `ToolRenderer`,
   chosen by tool name and details type.** `chat/renderer.py:ToolRenderer.start`
   picks the start packet by `call.name`, and `ToolRenderer.update` picks the
   delta by the type of `details`. A tool with no branch renders as a custom
   tool: `CustomToolStart` and `CustomToolArgs`, then its `content` as text for
   a successful result only. An error shows no text unless its details are
   `ToolExecutionError`. Return typed `details`: with `details=None`, the live
   stream sends the text twice, because both the result update and the
   completion emit it. Streamed argument
   deltas go only to `run_python` (`chat/renderer.py:MessageRenderer.consume`).
   Saved responses replay through the same renderer
   (`chat/presentation.py:replay_response`), so a change here changes reload too.
8. `durable-details-registered` **A new `details` type must be registered
   twice.** Chat saves `details` through the discriminated union in
   `db/models.py:StoredToolResult`, keyed by the model's `type` literal, and
   checkpoints it through `chat/checkpoint.py:CHECKPOINT_PAYLOAD_TYPES`. A new
   `type` literal missing from the union fails every save with a
   `ValidationError`. A subclass that keeps its parent's `type` literal saves as
   the parent and drops its own fields with no error.
   `chat/agent.py:ChatAgent._finalize_tool` replaces each `SearchDocsResponse`
   with `chat/models.py:ChatSearchResult` in this way, and its `staged_files`
   are not saved. Only the unwired checkpoint handoff path reads the registry
   ([[agent-runtime]]), so a missing registration fails only that path and its
   tests. Saved rows and checkpoints keep the `type` value and the tag, so
   never rename them.
9. `parallel-by-default` **Calls in one step run in parallel and share one
   `ToolContext`.** `agents/tool_execution.py:ToolBatch` starts every call of a
   step together. `ChatAgent._tool_context` advances only after the step, so
   sibling calls read the same context; citation-producing tools offset their
   numbers by `CITATIONS_PER_TOOL_CALL * invocation.call_index`
   ([[citations#number-block-per-tool-call]]). Calls start in call order. Each
   pass of `ToolBatch.execute` finalizes the calls that have completed, in call
   order, so end events follow completion order only across passes, and tab
   placement follows call order. Each finished
   call is finalized at once: `after_tool_call` (`ChatAgent._finalize_tool`)
   runs one call at a time on the run's thread. `Run.finish_tool` then writes
   the finalized result into the run record that chat saves, and publishes
   `ToolEndEvent`. After a cancel between `Run.record_tool_results` and
   `finish_tool`, the saved result is the raw result and no `ToolEndEvent` is
   sent. A tool whose calls must not overlap
   returns `ToolExecutionMode.SEQUENTIAL` from `execution_mode`, as
   `MemoryTool` does. This orders only calls with the same name: each starts
   after the previous one is finalized, and a call that waits for a child run
   or input blocks the calls after it.
10. `tool-name-is-lookup-key` **`Tool.name` is a lookup key and must be a valid
   function name.** `ToolBatch`, `ToolRenderer` and the `tool_ids` map in
   `chat/execution.py:ChatTurnExecution._run_response` find tools by name, so
   two tools with one name make one unreachable. OpenAI and Bedrock accept only
   `[a-zA-Z0-9_-]`. Tools that take user-supplied names, such as MCP and OpenAPI
   tools, must pass them through `tools/tool_name.py:sanitize_tool_name`.
11. `replay-by-class-name` **Replay finds a tool by its name or its class
   name.** Saved responses replay by tool name
   ([[#renderer-dispatches-by-name]]). Older messages with no saved response
   replay through
   `server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`,
   which dispatches on `Tool.in_code_tool_id`, the class name. A rename of
   either needs a migration, or old chats lose their tool blocks.
12. `calls-are-merged` **Merged calls share one execution and one result.**
    `agents/tool_execution.py:ToolBatch._start_compatible_calls` merges later
    calls to the same tool when the tool sets `merge_list_argument` and all
    other arguments match (`tools/interface.py:merge_tool_arguments`). Both
    lists must be non-empty string lists, and the merged list must stay within
    `merge_list_limit` (`open_url` sets `MAX_URLS_PER_CALL`). No merge happens
    when the run has `before_tool_call`, or when arguments are truncated or
    invalid. A parallel tool can merge calls that are not next to each other;
    a `SEQUENTIAL` tool merges only up to its first call that cannot merge. One
    execution runs with the first call's `call_index`, and each merged call
    gets every progress update and the pooled result. A merged execution must
    return a `ToolResult`: a `ChildRunWait` fails the batch with `ValueError`.
    Search, web search and `open_url` merge. A tool whose calls must stay
    separate leaves `merge_list_argument` unset.
13. `child-wait-cleanup` **A tool that returns `ChildRunWait` releases its
    resources through the child's completion.** `_run` returns before the
    child ends, so register cleanup with
    `invocation.agents.add_completion_cleanup(run_id, cleanup)` during `_run`.
    It runs on completion, cancellation or release. If `_run` fails before it
    returns the wait, clean up in `_run`. `CodingAgentTool._run` does both for
    its sandbox ([[code-execution]]). `result_from_children` must not depend on
    state held from `_run`.

---

## Decisions

- **Unusable tools are hidden, not reported.** `is_available` removes a tool
  before the model sees its schema. The model cannot call a tool that would
  fail, and a user is not told that a feature failed when nobody set it up. The
  cost is that a missing tool gives no signal
  ([[#is-available-cheap-and-silent]]).
- **Sub-agent control signals are not `Tool`s.** "I am done, write the report"
  has no result to persist, so it is a bare `AgentTool` with no `Tool` row.

---

## Known issues

- **`KnowledgeGraphTool` cannot run.** It is in `BUILT_IN_TOOL_MAP`, its `_run`
  raises `NotImplementedError`, and it has no constructor branch.
  The knowledge graph is an incomplete feature (see `## Not mapped` in
  PATHS.md). Do not delete it as dead code.
- **A tool call has no time limit of its own.** When no call of a step
  finishes within `agents/concurrency.py:OPERATION_TIMEOUT_SECONDS`,
  `agents/runtime.py:Run.wait_for_tool_activity` raises `TimeoutError` and the
  run fails. Nothing stops the tool's thread. A tool that ignores cancellation
  holds the turn open after Stop, a tool timeout or the turn deadline
  (`CHAT_EXECUTION_TIMEOUT_S`): `chat/execution.py:ChatTurnExecution._poll_responses`
  waits for `Run.wait_for_idle`, so the stream stays open and the session
  rejects new messages until the thread exits. Use I/O timeouts, and call
  `invocation.cancellation.check()` in long loops.
- **A step with more than 64 tool calls fails the run.**
  `agents/tool_execution.py:ToolBatch` raises `ValueError` above
  `MAX_TOOL_CALLS_PER_STEP`.
- **A failed MCP credential lookup hides the server's tools with no user
  error.** `_construct_tools_impl` catches `MCPCredentialsError`, logs a
  warning and skips the server.
- **OpenAPI tool names can collide.** `_disambiguate_mcp_tool_names` renames
  only `MCPTool`. One OpenAPI schema rejects its own duplicate operation IDs
  (`tools/tool_implementations/custom/openapi_parsing.py`), but nothing checks
  across two OpenAPI tools on one agent, or against a built-in name. The
  by-name maps keep the last one ([[#tool-name-is-lookup-key]]).
- **`tools/utils.py:is_image_generation_available` has no caller,** and its
  rule differs from the image tool's ([[image-generation]]).

---

## Dependencies

- [[agents-personas]]: `persona.tools` is the input to the captured
  configuration.
- [[agent-runtime]]: `ToolBatch` runs the bound tools, and `ToolRenderer`
  turns their events into packets.
- [[mcp-and-custom-tools]]: the OpenAPI and MCP tool classes, credential
  resolution, `Tool.enabled` and the `Tool` table helpers.
- [[plugins]]: Default Chat tool selection and per-user preferences.
- [[chat-persistence]]: `StoredToolResult` saves each result and its details.
- [[code-execution]]: the coding agent runs `BashTool` in a Code Interpreter
  session.
- [[observability]]: `Tool.run` opens one `function_span` per call.

---

## Recipes

- `built-in-tool` **A built-in tool.** Copy `FileReaderTool`
  (`tools/tool_implementations/file_reader/`). List the current set in
  `tools/built_in_tools.py:BUILT_IN_TOOL_MAP`. The INDEX.md Common tasks row
  gives the recipes in other documents that the task also needs.
  1. Put the class in `tools/tool_implementations/<name>/`, subclass `Tool`,
     and implement `_run`. Parse arguments with
     `tools/interface.py:parse_tool_arguments`.
  2. Add it to `BUILT_IN_TOOL_TYPES` and `BUILT_IN_TOOL_MAP`. Define `name` on
     the class itself (a `str` or a property), or the import of
     `tools/built_in_tools.py` fails in `_tool_llm_name`.
  3. Seed its `Tool` row in an Alembic migration with
     `in_code_tool_id=YourTool.__name__`. Copy
     `backend/alembic/versions/d3fd499c829c_add_file_reader_tool.py`.
     Construction sees only tools attached to the agent, so the class alone does
     nothing.
  4. Add a branch in `_construct_tools_impl`
     ([[#built-in-needs-constructor-branch]]).
  5. If the tool needs request data, add a field to `ToolContext` and fill it
     in each `_tool_context` builder. If it cites documents, results that are
     not in the index still need a `SearchDoc` with a `source_type` and a
     `document_id` that cannot clash with indexed IDs. Web search uses a
     `WEB_SEARCH_PREFIX` prefix and `DocumentSource.WEB`
     (`tools/tool_implementations/web_search/utils.py`).
  6. Add `ToolRenderer` branches for its start packet and its `details` type
     ([[#renderer-dispatches-by-name]]), and register the `details` type
     ([[#durable-details-registered]]). A search-like tool can reuse the search
     packets.
  7. Add its ID to `web/src/lib/tools/constants.ts` and
     `mobile/src/chat/tools.ts`.
  8. Deep research uses only the tools whose names are in the allowed set of
     `deep_research/research_agent.py:ResearchAgent.__init__`. Add a search tool
     there if deep research must use it. Nothing reports a tool that is left
     out.
- `gate-a-tool` **Gate a tool.** Pick the narrowest gate that matches who decides:

  | Who decides | Gate |
  |---|---|
  | The deployment cannot run it (no provider, no service) | `is_available` |
  | An admin, per agent | persona attachment (`Persona__Tool`) |
  | An admin, for all agents | `Tool.enabled` ([[mcp-and-custom-tools]]); built-in and MCP tools only |
  | A user, per message | `allowed_tool_ids`; `TOOL_VISIBILITY_CONFIG` decides whether chat offers the toggle |

  Do not inject a tool outside the agent tool loop as `MemoryTool` does, unless
  it is a user-level feature. Such a tool escapes every admin and per-message
  control.
- `investigate-tool-not-called` **Investigate "the model never calls tool X".** Walk the gates in order.
  Check that the tool is attached to the agent and that `Tool.enabled` is true.
  Check the `allowed_tool_ids` that the client sent. For a built-in tool, run its
  `is_available` in a shell, or look for "Failed checking availability" in
  `backend/log/api_server_debug.log`; the "Skipping tool" line is at debug
  level. Check the branch skips in gate 4: search usage `DISABLED`, an
  anonymous user on an OAuth or passthrough OpenAPI tool, and `open_url` with
  no vector DB. For Default Chat, check the user's plugin preferences. For MCP,
  look for the credential warning. Last, check for a name collision (Known
  issues).
- `force-tool-call` **Force a tool call in a test or a reproduction.** Send `forced_tool_id` with
  the message. Copy `backend/tests/integration/tests/tools/test_force_tool_use.py`.
  `chat/process_message.py:prepare_chat_turn` drops a forced ID with no error
  when the tool fails `is_tool_available_for_persona`, or when it is search and
  search is disabled; the model then answers without the forced call. Any
  other forced ID that construction did not build makes
  `chat/execution.py:create_chat_agent` fail the message with `BAD_REQUEST`.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/tools/`.
- External dependency unit tests: `backend/tests/external_dependency_unit/tools/`.
- Integration tests: `backend/tests/integration/tests/tools/`.
- By hand, turn web search off for one message. Other tools must still run, and
  `open_url` must not fetch live pages.

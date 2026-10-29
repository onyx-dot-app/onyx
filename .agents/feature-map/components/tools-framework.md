# Tools Framework

> The shared machinery for every tool the chat model can call: the `Tool`
> interface, the built-in tool registry, per-model tool construction and gating,
> and the parallel runner. Concrete tools live in their own components; this one
> owns the rules that they all depend on.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## Callers

The interface is `tools/interface.py:Tool` with its `ToolResponse` models,
`tools/tool_constructor.py:construct_tools` and
`tools/tool_runner.py:run_tool_calls`.

- **A developer who adds a tool** subclasses `Tool`, registers it, and attaches
  it to an agent. Keep [[#built-in-needs-constructor-branch]],
  [[#is-available-cheap-and-silent]], [[#run-errors-become-results]],
  [[#section-end-always]], [[#start-packet-in-run]] and
  [[#tool-name-is-lookup-key]]. The concrete tools are [[internal-search]],
  [[web-search]], [[image-generation]], [[code-execution]],
  [[mcp-and-custom-tools]], [[chat-preferences]] (`MemoryTool`) and
  [[file-store-and-user-files]] (`read_file`).
- **[[core-chat-loop]]** calls `construct_tools` once per model thread and
  `run_tool_calls` once per LLM cycle. It must keep
  [[#every-call-paired]], [[#calls-are-merged]] and [[#two-response-channels]].
- **The sub-agent loops** run their own LLM loops. The research agent calls
  `run_tool_calls` with `max_concurrent_tools=1`. The coding agent calls
  `BashTool.run` directly, so it skips the runner's guards
  ([[code-execution#errors-are-results]]).
- **[[citations]]** gets a block of citation numbers per search-like call.

---

## Scope

This component owns the `Tool` interface and its response models, tool
construction and its gates, the parallel runner, the built-in tool registry,
the research-agent and coding-agent loops, and the `CodingAgentTool` wrapper.

Neighbours own the rest:
- Each concrete tool belongs to the component listed in Callers.
- [[mcp-and-custom-tools]] owns the tool HTTP API, the `Tool` table helpers,
  the OpenAPI and MCP tool classes, and MCP credential resolution.
- [[plugins]] owns Default Chat tool selection and the per-user tool
  preferences that construction reads.
- [[core-chat-loop]] owns the LLM cycle, the stopping-tool rule, and how the
  sub-agent loops enter a turn.
- [[citations]] owns the meaning of the number blocks that the runner hands out.
- [[chat-persistence]] owns how tool calls are saved and replayed, and why tool
  results do not stay in later turns. Expect the model to call a tool again for
  output from an earlier turn.
- [[web-search]] owns the rule that turning web search off for one message makes
  `open_url` index-only (`tools/tool_constructor.py:should_disable_open_url_web_fetch`).

---

## Architecture

```
chat/process_message.py                  captures agent tools once per request
  capture_persona_tool_configuration     (db/tools.py) -> PersonaToolConfiguration
  per model thread:
    construct_tools                      -> {Tool row id: [Tool instances]}
  run_llm_loop                           ([[core-chat-loop]])
    each cycle: LLM returns tool calls
    run_tool_calls                       merge -> drop unknown -> cap -> emit_start
                                         -> build override kwargs -> run in parallel
      _safe_run_single_tool              run, convert errors, always SectionEnd
    results -> history, ToolCallInfo, citation processor
```

**Captured configuration.** `db/tools.py:capture_persona_tool_configuration`
copies the agent's `Tool` rows into frozen `ToolConfiguration` models before the
LLM loop starts. `construct_tools` opens its own short DB session, so no session
stays open for a turn that can last minutes. MCP tool schemas come from the
captured `mcp_input_schema`, not from a live MCP call.

**Construction per model.** `chat/process_message.py` calls `construct_tools`
in each model thread. A multi-model turn therefore has separate tool instances,
each with its own `Emitter`. `tools/tool_constructor.py:_construct_tools_impl`
walks the captured tools in order and applies these gates:

1. `server/features/tool/tool_visibility.py:is_tool_available_for_persona`. An
   MCP or built-in tool with `enabled=False` is skipped for every agent. An
   OpenAPI tool with `enabled=False` is skipped only in Default Chat.
2. `allowed_tool_ids`, the per-message list that the web client sends.
3. For a built-in tool, `is_available(db_session)`. An exception counts as "not
   available" and is logged.
4. A class-specific branch builds the instance. OpenAPI and MCP rows go through
   their own branches ([[mcp-and-custom-tools]]). The MCP branch builds every
   `MCPTool` of a server from the captured rows with the same `mcp_server_id`,
   and resolves credentials once per server.
5. Only for Default Chat (`DEFAULT_PERSONA_ID`): the user's OpenAPI and MCP
   plugin preferences ([[plugins]]), and `user_can_access_mcp_server`, which
   stops Default Chat from giving a group-restricted MCP server to every user
   ([[mcp-and-custom-tools#access-grants-default-chat-only]]). A custom agent
   applies neither.

Two tools are added outside this loop. `SearchTool` is added when the request
forces search on (`SearchToolUsage.ENABLED`), `DISABLE_VECTOR_DB` is off, and
the loop did not build it. `MemoryTool` is added when `user.enable_memory_tool`
is set ([[#memory-tool-bypasses-filters]]). Last, `_disambiguate_mcp_tool_names`
renames MCP tools whose names collide.

**Execution.** `tools/tool_runner.py:run_tool_calls` merges repeated calls to
`internal_search`, `web_search` and `open_url`, drops calls to unknown names,
and applies `max_concurrent_tools`. It calls `emit_start` for each call in
order, then runs all calls in a thread pool with a 10-minute timeout
(`TOOL_EXECUTION_TIMEOUT_SECONDS`). Per-request data, such as chat files and
citation start numbers, reaches a tool through its override kwargs type, which
`run_tool_calls` builds per tool class.

**Sub-agent loops.** `tools/fake_tools/research_agent.py` and
`tools/fake_tools/coding_agent.py` run their own LLM loops. Despite the
directory name, they hold no `Tool` classes. Their control functions, such as
`think_tool` and `generate_report`, are plain schemas with no `Tool` row.

---

## Contracts and traps

1. `memory-tool-bypasses-filters` **`MemoryTool` bypasses `allowed_tool_ids`
   and the agent's tools.** `tools/tool_constructor.py:_construct_tools_impl`
   adds it after the agent tool loop whenever `user.enable_memory_tool` is set.
   A user who turns every tool off for a message can still get a memory write.
   A change to per-message filtering must decide whether memory follows it.
2. `built-in-needs-constructor-branch` **A built-in tool without a constructor
   branch is silently dropped.** The `if/elif` chain in
   `tools/tool_constructor.py:_construct_tools_impl`
   has no `else`. A tool in `tools/built_in_tools.py:BUILT_IN_TOOL_MAP` with no
   branch passes `is_available` and then is never added. `KnowledgeGraphTool` is
   in this state on purpose (Known issues). The reverse also holds: an exception
   inside a branch is not caught, and it ends that model's answer. The web
   search, `open_url` and image generation branches raise `ValueError` when
   their provider is missing. Put each "cannot run here" check in
   `is_available`.
3. `is-available-cheap-and-silent` **`is_available` runs on every turn and must
   be cheap.** It runs once per attached built-in tool per model thread. Cache
   remote checks, as
   `tools/tool_implementations/python/code_interpreter_client.py:CodeInterpreterClient.health`
   does with `use_cache=True`. An
   exception hides the tool and only logs, so a bug here looks like "the model
   never uses the tool".
4. `two-response-channels` **Keep the two `ToolResponse` channels apart.**
   `tools/models.py:ToolResponse.llm_facing_response` is the only text the model
   sees. `rich_response` is a typed object that `chat/llm_loop.py:run_llm_loop`
   reads by type to save search docs, images, files and memories. Some saved
   model text is itself a contract, such as the `run_python` result JSON
   ([[code-execution#run-python-result-json]]).
5. `run-errors-become-results` **`Tool.run` must not let errors stop the
   turn.** `tools/tool_runner.py:_safe_run_single_tool` turns
   `ToolCallException`, `ToolExecutionException` and any other exception into a
   `ToolResponse` with `GENERIC_TOOL_ERROR_MESSAGE`. Raise `ToolCallException`
   with a `llm_facing_message` for errors that the model can fix, such as bad
   arguments. Set `emit_error_packet=True` on `ToolExecutionException` when the
   user must see the error.
6. `section-end-always` **Every tool call must end with a `SectionEnd`
   packet.** `tools/tool_runner.py:_safe_run_single_tool` emits it after every path, success or
   failure. The frontend closes the tool block on it. Do not add a return path
   that skips it.
7. `start-packet-in-run` **A start packet that needs the tool arguments goes in
   `run`.** `tools/tool_runner.py:run_tool_calls` calls `emit_start` before `run`, without the
   arguments. `PythonTool`, `BashTool` and `CodingAgentTool` leave `emit_start`
   empty and emit their start packet at the top of `run`. Emit it before any
   other packet that the tool emits for that call. A tool whose
   `should_emit_argument_deltas` is true also gets `ToolCallArgumentDelta`
   packets earlier, while the model streams the call
   (`chat/tool_call_args_streaming.py:maybe_emit_argument_delta`). That lookup
   uses `TOOL_NAME_TO_CLASS`, so it works only for tools in
   `BUILT_IN_TOOL_MAP`.
8. `tool-name-is-lookup-key` **`Tool.name` is a lookup key and must be a valid
   function name.** `tools/tool_runner.py:run_tool_calls` maps calls to tools by `tool.name`, so two
   tools with one name make one unreachable. OpenAI and Bedrock accept only
   `[a-zA-Z0-9_-]`. Tools that take user-supplied names, such as MCP and OpenAPI
   tools, must pass them through `tools/tool_name.py:sanitize_tool_name`.
9. `replay-by-class-name` **Replay finds a built-in tool by its class name.**
   `server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`
   loads the `Tool` row of each saved call and dispatches on `in_code_tool_id`,
   which is the class name. A class rename needs a migration of
   `Tool.in_code_tool_id`, or old chats lose their tool blocks.
10. `calls-are-merged` **The model's tool calls are not the calls that run.**
    `tools/tool_runner.py:_merge_tool_calls` merges repeated search, web search
    and `open_url` calls under the first call's `tool_call_id`. History records
    the merged call. A tool whose calls must stay separate must stay out of
    `tools/tool_runner.py:MERGEABLE_TOOL_FIELDS`.
11. `every-call-paired` **Every tool call in history needs a paired response.**
    Providers reject a history with an unanswered call. `run_tool_calls` drops
    calls to unknown tool names, and `chat/llm_loop.py:run_llm_loop` answers
    each one with `chat/chat_utils.py:create_tool_call_failure_response`. Calls
    over `max_concurrent_tools` are dropped, not queued, and do not go into
    history. A change to either path must keep every recorded call paired with a
    response.

---

## Decisions

- **Unusable tools are hidden, not reported.** `is_available` removes a tool
  before the model sees its schema. The model cannot call a tool that would
  fail, and a user is not told that a feature failed when nobody set it up. The
  cost is that a missing tool gives no signal
  ([[#is-available-cheap-and-silent]]).
- **Sub-agent control signals are not `Tool`s.** "I am done, write the report"
  has no result to persist, so it needs no `Tool` row.

---

## Known issues

- **`KnowledgeGraphTool` cannot run.** It is in `BUILT_IN_TOOL_MAP`, its `run`
  raises `NotImplementedError`, and its constructor branch is commented out.
  The knowledge graph is an incomplete feature (see `## Not mapped` in
  PATHS.md). Do not delete it as dead code.
- **A tool that passes the 10-minute timeout keeps running.** The thread pool
  returns `None` for it and the thread continues. The call gets no history
  entry, and its `SectionEnd` arrives only when the thread ends. The coding
  agent allows itself 25 minutes (`CODING_AGENT_FORCE_ANSWER_SECONDS`), so a
  long coding-agent run reaches this limit.
- **A failed MCP credential lookup hides the server's tools with no user
  error.** `_construct_tools_impl` catches `MCPCredentialsError`, logs a
  warning and skips the server.
- **OpenAPI tool names can collide.** `_disambiguate_mcp_tool_names` renames
  only `MCPTool`. One OpenAPI schema rejects its own duplicate operation IDs
  (`tools/tool_implementations/custom/openapi_parsing.py`), but nothing checks
  across two OpenAPI tools on one agent, or against a built-in name. The
  `tools_by_name` maps in `run_tool_calls` and `run_llm_loop` keep the last one.
- **`tools/utils.py:is_image_generation_available` has no caller,** and its
  rule differs from the image tool's ([[image-generation]]).

---

## Dependencies

- [[agents-personas]]: `persona.tools` is the input to the captured
  configuration.
- [[mcp-and-custom-tools]]: the OpenAPI and MCP tool classes, credential
  resolution, `Tool.enabled` and the `Tool` table helpers.
- [[plugins]]: Default Chat tool selection and per-user preferences.
- [[streaming-protocol]]: start, delta and `SectionEnd` packets.
- [[code-execution]]: the coding-agent loop runs `BashTool` in a Code
  Interpreter session.
- [[observability]]: `_safe_run_single_tool` opens one `function_span` per call.

---

## Recipes

- `built-in-tool` **A built-in tool.** Copy `FileReaderTool`
  (`tools/tool_implementations/file_reader/`). List the current set in
  `tools/built_in_tools.py:BUILT_IN_TOOL_MAP`. The INDEX.md Common tasks row
  gives the recipes in other documents that the task also needs.
  1. Put the class in `tools/tool_implementations/<name>/` and subclass
     `Tool[YourOverrideKwargs]`.
  2. Add it to `BUILT_IN_TOOL_MAP`.
  3. Seed its `Tool` row in an Alembic migration with
     `in_code_tool_id=YourTool.__name__`. Copy
     `backend/alembic/versions/d3fd499c829c_add_file_reader_tool.py`.
     Construction sees only tools attached to the agent, so the class alone does
     nothing.
  4. Add a branch in `_construct_tools_impl`
     ([[#built-in-needs-constructor-branch]]).
  5. If the tool needs request data, such as chat files, add an override kwargs
     branch in `run_tool_calls`. If it cites documents, results that are not
     in the index still need a `SearchDoc` with a `source_type` and a `document_id` that
     cannot clash with indexed IDs. Web search uses a `WEB_SEARCH_PREFIX` prefix
     and `DocumentSource.WEB` (`tools/tool_implementations/web_search/utils.py`).
  6. A search-like tool can reuse the search packets. Every tool needs a
     replay branch keyed by its class name ([[#replay-by-class-name]]).
  7. Add its ID to `web/src/lib/tools/constants.ts` and
     `mobile/src/chat/tools.ts`.
  8. Deep research uses only the tools in the `allowed_tool_names` set of
     `deep_research/dr_loop.py:run_deep_research_llm_loop`. Add a search tool
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
  level. For Default Chat, check the user's plugin preferences. For MCP, look
  for the credential warning. Last, check for a name collision (Known issues).
- `force-tool-call` **Force a tool call in a test or a reproduction.** Send `forced_tool_id` with
  the message. Copy `backend/tests/integration/tests/tools/test_force_tool_use.py`.
  The tool must pass every construction gate: a forced ID that construction did
  not build fails the whole message.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/tools/`.
- External dependency unit tests: `backend/tests/external_dependency_unit/tools/`.
- Integration tests: `backend/tests/integration/tests/tools/`.
- By hand, turn web search off for one message. Other tools must still run, and
  `open_url` must not fetch live pages.

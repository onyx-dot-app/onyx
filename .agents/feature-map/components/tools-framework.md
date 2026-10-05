# Tools Framework

> The `Tool` abstraction and the machinery around it: the interface every tool
> implements, the built-in tool catalogue, per-turn tool assembly, and parallel
> tool execution.

**Domain:** core-loop
**Edition:** CE, with EE additions in MCP credential resolution
**Owns:**
`backend/onyx/tools/interface.py`, `models.py`, `tool_constructor.py`, `tool_runner.py`,
`built_in_tools.py`, `tool_name.py`, `constants.py`, `utils.py`,
`backend/onyx/tools/fake_tools/`, `backend/onyx/server/features/tool/api.py`,
`backend/onyx/db/tools.py`

**Read first:** `[[core-chat-loop]]`. This component supplies the tool set that
`run_llm_loop` calls into and executes; it does not run the LLM loop itself.

---

## 1. What the user experiences

When an agent needs to do something beyond generating text, it calls a tool: search
the company index, search the web, open a URL, generate an image, run Python, read
an attached file, or remember a fact about the user. The user sees a tool block in
the transcript (queries, a spinner, then a result) while the tool runs, and the
final answer folds the result back into prose with citations where relevant.

Admins control which tools a persona (agent) can use by attaching or detaching them
in the persona editor. A user can also toggle tools off for a single message (for
example, turning off web search for one question) without changing the persona.

Two tools behave specially and are invisible as separate toggles: `MemoryTool` runs
whenever the user has memory enabled, regardless of which persona is active, and
`OpenURLTool` (link-opening) is not shown in the tool picker at all but is silently
scoped down when web search is excluded.

---

## 2. Surfaces

### HTTP endpoints (router prefix `/tool`, `server/features/tool/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/tool` | `list_tools` | Lists tools visible to the current user, filtered by `_may_view_tool`. |
| GET | `/tool/{tool_id}` | `get_custom_tool` | |
| GET | `/tool/openapi` | `list_openapi_tools` | |
| POST | `/admin/tool/custom` | `create_custom_tool` | Creates a custom OpenAPI tool. |
| PUT | `/admin/tool/custom/{tool_id}` | `update_custom_tool` | |
| DELETE | `/admin/tool/custom/{tool_id}` | `delete_custom_tool` | |
| PATCH | `/admin/tool/status` | `update_tools_status` | Enables/disables a `Tool` row (`Tool.enabled`). |
| POST | `/admin/tool/custom/validate` | `validate_tool` | Validates an OpenAPI schema before save. |

MCP tool CRUD lives under `/admin/mcp` and is covered by `[[mcp-and-custom-tools]]`,
not here.

### The per-message tool toggle

`handle_send_chat_message` accepts an `allowed_tool_ids` whitelist on the request.
When present, `tool_constructor.py:_construct_tools_impl` skips any persona tool
whose `db_tool_model.id` is not in that list. This is how the frontend's per-message
"turn off web search" control works. `MemoryTool` bypasses this whitelist entirely
(see §5).

### Environment configuration

No dedicated env vars gate this component directly. Individual tools read their own
env vars for availability (for example `CODE_INTERPRETER_BASE_URL` for `PythonTool`
and `BashTool`, checked in `python_tool.py:is_available` and `bash_tool.py:is_available`).

---

## 3. Data model

- `Tool` (`backend/onyx/db/models.py:Tool`): one row per tool a persona can attach.
  Three mutually-informative columns decide what kind of tool a row represents:
  - `in_code_tool_id` set: a built-in tool. The value is a class name
    (`SearchTool`, `MemoryTool`, ...) looked up in `BUILT_IN_TOOL_MAP`.
  - `openapi_schema` set: a custom tool backed by a user-supplied OpenAPI schema
    (`tool_constructor.py:build_custom_tools_from_openapi_schema_and_headers`).
  - `mcp_server_id` set: an MCP tool, one row per tool exposed by that MCP server.
  A row can have `enabled = False` without being detached from its personas; see §5.
- `Persona__Tool` (`db/models.py:Persona__Tool`): join table recording that a tool
  is *available* to a persona. Availability here does not imply usability; a
  persona can list `ImageGenerationTool` while no image provider is configured.
- `ToolCall` (owned by `[[chat-persistence]]`): the persisted record of one
  invocation, written after `run_tool_calls` returns, not by this component.

---

## 4. How it works

### 4.1 The `Tool` interface (`tools/interface.py`)

`class Tool(abc.ABC, Generic[TOverride])`. Every concrete tool subclasses it,
parameterizing `TOverride` with its own override-kwargs model (for example
`SearchTool(Tool[SearchToolOverrideKwargs])`).

Abstract members every tool must implement:
- `id`, `name`, `description`, `display_name` (properties)
- `tool_definition() -> dict`: the JSON schema handed to the LLM provider
- `emit_start(placement)`: emits the tool's specific "start" packet
- `run(placement, override_kwargs, **llm_kwargs) -> ToolResponse`: executes the tool

Overridable with defaults:
- `is_available(cls, db_session) -> bool`, default `True`. A dynamic, per-request
  gate (does a provider key exist, is an index configured, is a service healthy).
- `should_emit_argument_deltas(cls) -> bool`, default `False`. Controls whether the
  LLM's streamed tool-call arguments are forwarded token-by-token.

The constructor takes an optional `Emitter`; `Tool.emitter` (`interface.py:emitter`)
raises `ValueError` if it was never set, so a tool built without an emitter fails
loudly on first emit rather than silently dropping packets.

### 4.2 `ToolResponse`: two payloads, two audiences (`tools/models.py:ToolResponse`)

This is the load-bearing idea of the component. Every tool run produces exactly one
`ToolResponse` with two fields that must never be confused:

- `llm_facing_response: str`: the only thing that goes back into the LLM's message
  history as the tool's response. Whatever the model needs to keep reasoning must
  be in this string.
- `rich_response`: a discriminated union used **only** for UI rendering and DB
  persistence: `FinalImageGenerationResponse`, `SearchDocsResponse`,
  `MemoryToolResponse`, `CustomToolCallSummary`, `PythonToolRichResponse`, a bare
  `str`, or `None`. The LLM never sees this value; it is read by `save_chat_turn`
  (`[[chat-persistence]]`) and by the frontend renderer.

### 4.3 Built-in tool catalogue (`tools/built_in_tools.py`, `tool_name.py`)

`BUILT_IN_TOOL_MAP` maps a `Tool.in_code_tool_id` string (the class name) to the
implementation class. `TOOL_NAME_TO_CLASS` maps the LLM-facing `NAME` to the same
class, built by walking `BUILT_IN_TOOL_MAP` (`built_in_tools.py:_build_tool_name_to_class`).
`get_built_in_tool_by_id` (`built_in_tools.py:get_built_in_tool_by_id`) is the
runtime lookup `tool_constructor.py` uses for every persona-attached built-in tool.

| Tool | Class : file | LLM-facing `NAME` | Purpose | Availability gate |
|---|---|---|---|---|
| Internal search | `SearchTool` : `tool_implementations/search/search_tool.py` | `internal_search` | Query the company document index. | `is_available`: `False` if `DISABLE_VECTOR_DB`; else `True` if connectors, federated connectors, or user files exist (`search_tool.py:is_available`). |
| Web search | `WebSearchTool` : `tool_implementations/web_search/web_search_tool.py` | `web_search` | Query an external web search provider. | `True` only if an active provider row exists (`web_search_tool.py:is_available`). |
| Image generation | `ImageGenerationTool` : `tool_implementations/images/image_generation_tool.py` | `generate_image` | Generate an image via the configured image LLM. | `True` if a default image-generation config with credentials exists (`image_generation_tool.py:is_available`, `utils.py:is_image_generation_configured`). |
| Open URL | `OpenURLTool` : `tool_implementations/open_url/open_url_tool.py` | `open_url` | Fetch a specific URL's content, from the live web or the index. | Always `True` (`open_url_tool.py:is_available`); its web-fetch path can still be disabled per message, see §4.4. |
| Python / Code Interpreter | `PythonTool` : `tool_implementations/python/python_tool.py` | `run_python` | Execute Python in a sandboxed session. | `True` only if `CODE_INTERPRETER_BASE_URL` is set, the server is enabled, and its health check passes (`python_tool.py:is_available`). |
| File reader | `FileReaderTool` : `tool_implementations/file_reader/file_reader_tool.py` | `read_file` | Read an attached or project file's contents on demand. | `DISABLE_VECTOR_DB` only, gated behind a TODO pending generalization (`file_reader_tool.py:is_available`). |
| Memory | `MemoryTool` : `tool_implementations/memory/memory_tool.py` | `add_memory` | Persist a fact about the user across sessions. | No override; default `True`. Injection is gated by `user.enable_memory_tool`, not by `is_available` (see §5). |
| Coding agent | `CodingAgentTool` : `tool_implementations/coding_agent/coding_agent_tool.py` | value of `CODING_AGENT_TOOL_NAME` | Runs a sub-agent loop against a cloned repo. | `True` iff `BashTool.is_available` is `True` (`coding_agent_tool.py:is_available`). |
| Bash | `BashTool` : `tool_implementations/bash/bash_tool.py` | `bash` | Run a shell command in an isolated code-interpreter session. | `True` if `CODE_INTERPRETER_BASE_URL` is set, the server is enabled, its health check passes, and it `supports(...)` the session/bash routes (`bash_tool.py:is_available`). Not persona-attachable (see §5). |

`KnowledgeGraphTool` (`tool_implementations/knowledge_graph/knowledge_graph_tool.py`)
belongs to the knowledge graph, an incomplete feature (see INDEX.md, Incomplete
features). It is present in `BUILT_IN_TOOL_MAP` (`built_in_tools.py`), so
`get_built_in_tool_by_id` resolves it and `is_available` is checked for it. Its
`run` raises `NotImplementedError`, and its dispatch branch in
`tool_constructor.py:_construct_tools_impl` is commented out. The if/elif chain has
no trailing `else`, so a persona row with `in_code_tool_id="KnowledgeGraphTool"`
passes the availability check but is never added to `tool_dict`.

### 4.4 Per-turn assembly: `tool_constructor.py`

`construct_tools` opens a DB session (if none given) and delegates to
`_construct_tools_impl`, returning `dict[tool_id, list[Tool]]` (a list because MCP
tool-name disambiguation and custom-tool schemas can expand one DB row into more
than one runtime tool).

For each `db_tool_model` in `persona.tools`, in order:
1. Skip if `db_tool_model.enabled` is `False`.
2. Skip if `allowed_tool_ids` is given and the tool's id is not in it (the
   per-message toggle from §2).
3. For a built-in tool (`in_code_tool_id` set), resolve the class via
   `get_built_in_tool_by_id`, call `tool_cls.is_available(db_session)` in a
   `try/except` that treats a raised exception as `False`
   (`tool_constructor.py:_construct_tools_impl`), then dispatch to a class-specific
   constructor branch (`SearchTool`, `ImageGenerationTool`, `WebSearchTool`,
   `OpenURLTool`, `PythonTool`, `CodingAgentTool`, `FileReaderTool`).
4. For a custom tool (`openapi_schema` set), resolve OAuth (per-tool OAuth config,
   then passthrough auth using the user's own login token) and build one `Tool`
   per operation via `build_custom_tools_from_openapi_schema_and_headers`.
5. For an MCP tool (`mcp_server_id` set), resolve credentials via
   `resolve_mcp_credentials`, list the server's tools via
   `get_all_mcp_tools_for_server`, and build an `MCPTool` per tool, caching by
   server id so a server with many tools is only queried once per turn.

Two tools are force-injected **outside** this persona loop:
- `SearchTool`, when `search_usage_forcing_setting == SearchToolUsage.ENABLED` and
  the persona did not already attach it (`tool_constructor.py:_construct_tools_impl`,
  the block after the main loop).
- `MemoryTool`, whenever `user.enable_memory_tool` is set. This lookup uses
  `get_builtin_tool(db_session, MemoryTool)` directly and **bypasses
  `allowed_tool_ids` entirely** (see §5, §9).

`should_disable_open_url_web_fetch` (`tool_constructor.py:should_disable_open_url_web_fetch`)
returns `True` when `WebSearchTool` is explicitly excluded via `allowed_tool_ids`.
`OpenURLTool` is then constructed with `web_fetch_disabled=True`, so live web
fetches are cut off while its indexed-document fallback still works. `OpenURLTool`
itself has no chat-facing toggle (`chat_selectable=False` per its docstring), so
this is the only way to turn off its live-web behavior.

Finally, `_disambiguate_mcp_tool_names` renames any `MCPTool` whose `name` collides
with another tool's name across MCP servers.

### 4.5 Execution: `tool_runner.py:run_tool_calls`

Called once per LLM cycle from `[[core-chat-loop]]`'s `run_llm_loop`, given the
tool calls the LLM just made and the constructed `Tool` instances.

1. **Merge.** `_merge_tool_calls` collapses repeated calls to the same tool using
   `MERGEABLE_TOOL_FIELDS`: `SearchTool.NAME` and `WebSearchTool.NAME` merge their
   `queries` list; `OpenURLTool.NAME` merges its `urls` list. A merged call keeps
   the first call's `tool_call_id` and `placement`.
2. **Filter.** Calls naming a tool not in `tools_by_name` are dropped with a
   warning; they do not count against `max_concurrent_tools`.
3. **Cap.** If `max_concurrent_tools` is set, calls beyond the cap are dropped
   outright (not queued for a later cycle).
4. **Prepare overrides.** For each surviving call, `tool.emit_start(placement)`
   fires first, then the type-specific `TOverride` is built: `SearchTool` gets
   `original_query` (the last user message), `message_history`, memory context, and
   `skip_query_expansion`; `WebSearchTool` and `OpenURLTool` get their own citation
   ranges; `PythonTool` gets `chat_files`; `MemoryTool` gets user identity fields and
   history. `SearchTool`, `WebSearchTool`, and `OpenURLTool` each consume
   `starting_citation_num` and then advance it by 100
   (`tool_runner.py:run_tool_calls`), so parallel citation-producing tools cannot
   collide on citation numbers.
5. **Run.** All prepared calls run concurrently via
   `run_functions_tuples_in_parallel(_safe_run_single_tool, ..., allow_failures=True,
   timeout=TOOL_EXECUTION_TIMEOUT_SECONDS)`, where
   `TOOL_EXECUTION_TIMEOUT_SECONDS = 10 * 60`.
6. **Per-tool wrapper.** `_safe_run_single_tool` wraps the call in a tracing
   `function_span(tool.name)`, calls `tool.run(...)`, and converts any exception
   into a `ToolResponse` whose `llm_facing_response` is
   `GENERIC_TOOL_ERROR_MESSAGE.format(error=...)`:
   - `ToolCallException`: expected (bad args, provider 4xx). Uses
     `e.llm_facing_message`.
   - `ToolExecutionException`: unexpected; if `e.emit_error_packet` is set, also
     emits a `PacketException` to the stream.
   - Bare `Exception`: unexpected, generic message, always emits a `SpanError` for
     tracing.
   A `SectionEnd` packet is emitted after every tool call, success or failure, so
   the frontend always closes the tool's UI block.
7. **Citation merge.** Results whose `rich_response` is a `SearchDocsResponse` have
   their `citation_mapping` merged into the shared `citation_mapping` dict
   (mutated in place and also returned).

---

## 5. Contracts and invariants

1. **A new built-in tool needs both `BUILT_IN_TOOL_MAP` and a DB row.** Adding the
   class alone does nothing; `_construct_tools_impl` only sees tools present on
   `persona.tools`, and those rows come from `Tool.in_code_tool_id` seeded via
   alembic migration (see `backend/alembic/versions/d09fc20a3c66_seed_builtin_tools.py`,
   `f3c9e59c3b07_seed_coding_agent_tool.py`, `d3fd499c829c_add_file_reader_tool.py`
   for precedent).
2. **`is_available` must be cheap and must not raise.** `tool_constructor.py`
   wraps every call in `try/except Exception`, but a raised exception is treated as
   "not available" and logged, silently hiding a tool rather than failing the turn.
   A slow `is_available` runs on every tool construction, once per turn per
   persona-attached built-in tool.
3. **`llm_facing_response` must never carry UI-only data**, and **`rich_response`
   must never be sent to the LLM.** These are the only two channels a `ToolResponse`
   has; mixing them either leaks internal structure to the model or drops
   renderable data.
4. **Citation-number ranges must not collide.** Any new citation-producing tool run
   through `run_tool_calls` must consume `starting_citation_num` and advance it,
   matching the pattern for `SearchTool`/`WebSearchTool`/`OpenURLTool`.
5. **`emit_start` must fire before `run`.** `run_tool_calls` calls them in that
   order for every tool call; a tool that emits its own start packet inside `run`
   instead will render out of order.
6. **Every tool call must emit a `SectionEnd`.** `_safe_run_single_tool` emits it
   unconditionally after `run`, including on every exception path. Do not add a new
   early-return path that skips it.
7. **Exceptions from `Tool.run` must never propagate out of `run_tool_calls`.**
   `_safe_run_single_tool` converts `ToolCallException`, `ToolExecutionException`,
   and bare `Exception` into a `ToolResponse`, keeping the turn alive.
8. **`MemoryTool` bypasses `allowed_tool_ids`.** Its injection in
   `_construct_tools_impl` happens after, and independently of, the persona-tool
   loop that checks the whitelist. A change to per-message tool filtering must
   account for this or memory will leak into a turn the user tried to restrict.
9. **A tool with `Tool.enabled = False` stays attached to its personas.**
   `Persona__Tool` is an availability record, not a usability one; the
   `enabled` check happens in `_construct_tools_impl`, not at the DB relationship
   level.

---

## 6. Relationships

**Depends on**
- `[[streaming-protocol]]`: every tool's `emit_start`, argument-delta, and
  `SectionEnd` packets use the shared `Placement`/`Packet` vocabulary.
- `[[chat-persistence]]`: `ToolResponse.rich_response` is what `save_chat_turn`
  persists as `SearchDoc` rows, `ToolCall.tool_result`, and generated file records.
- `[[agents-personas]]`: `persona.tools` is the input to `construct_tools`; persona
  fields (document sets, attached documents, hierarchy nodes) shape `SearchTool`'s
  scope.
- `[[llm-providers]]`: `tool.tool_definition()` output is what the provider-facing
  request includes as callable functions.
- `[[observability]]`: `run_tool_calls` and `_safe_run_single_tool` open a
  `function_span(tool.name)` for every call.

**Depended on by**
- `[[core-chat-loop]]`: calls `construct_tools` once per turn and `run_tool_calls`
  once per LLM cycle.
- `[[internal-search]]`, `[[web-search]]`, `[[image-generation]]`,
  `[[code-execution]]`, `[[mcp-and-custom-tools]]`: each is a concrete `Tool`
  implementation documented separately; this component is their shared contract.
- `[[streaming-protocol]]`'s frontend consumer: `renderMessageComponent.tsx`
  switches on the packet types each tool emits.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a built-in tool | `BUILT_IN_TOOL_MAP`, a seeding migration for its `Tool` row, a construction branch in `tool_constructor.py`, a renderer case in `renderMessageComponent.tsx`, and whether it needs a `MERGEABLE_TOOL_FIELDS` entry |
| renames a tool's `NAME` | Saved chat history stores the old name in `ToolCallSimple.tool_name`; a rename breaks replay of old sessions and the frontend's type-based renderer switch in `renderMessageComponent.tsx` |
| changes `ToolResponse` (adds/removes a `rich_response` variant) | every tool that returns that variant, `save_chat_turn` (`[[chat-persistence]]`), and the frontend renderer that reads the persisted rich response |
| changes `is_available` for any built-in tool | the tool-listing/admin UI, and whether the change can raise (see §5 contract 2) |
| changes error wrapping in `_safe_run_single_tool` | the exact `GENERIC_TOOL_ERROR_MESSAGE` string other code may pattern-match on, and whether `SectionEnd` still always fires |
| changes `allowed_tool_ids` filtering | `MemoryTool`'s bypass and `should_disable_open_url_web_fetch`, both of which sit outside the main filter |
| changes MCP tool construction or caching | `[[mcp-and-custom-tools]]`, and `_disambiguate_mcp_tool_names` |
| changes citation-range allocation (`starting_citation_num`) | `[[citations]]`, and every citeable tool in `CITEABLE_TOOLS_NAMES` |

---

## 8. How to verify a change

### Tests

```bash
# Integration tests are preferred for tool construction and execution behavior.
cd backend && uv run pytest tests/integration -k tool
# Unit tests for tool_runner merging/citation logic
cd backend && uv run pytest tests/unit -k "tool_runner or tool_constructor"
```

See `backend/AGENTS.md` for authoritative commands and required env.

### Adding a new built-in tool, end to end

1. Implement the class under `tools/tool_implementations/<name>/`, subclassing
   `Tool[YourOverrideKwargs]` and implementing every abstract member in §4.1.
2. Add it to `BUILT_IN_TOOL_MAP` in `built_in_tools.py`.
3. Write an alembic migration that inserts a `Tool` row with
   `in_code_tool_id=YourTool.__name__` (mirror
   `backend/alembic/versions/d3fd499c829c_add_file_reader_tool.py`).
4. Add a construction branch in `tool_constructor.py:_construct_tools_impl` if the
   tool needs config beyond the default constructor args.
5. If the tool produces citations, add its `NAME` to `MERGEABLE_TOOL_FIELDS` and
   `CITEABLE_TOOLS_NAMES` as appropriate, and handle its `starting_citation_num` in
   `run_tool_calls`.
6. Add a renderer case in
   `web/src/app/app/message/messageComponents/renderMessageComponent.tsx` for the
   packet type(s) the tool emits, and a dedicated renderer component alongside the
   existing ones (`InternalSearchToolRenderer`, `PythonToolRenderer`, etc.).
7. Attach the tool to a persona in the admin UI or via a test fixture, then run a
   chat turn that forces the tool to fire.

### Manual reproduction

1. Confirm services are up via `backend/log/api_server_debug.log`.
2. In the admin persona editor, attach or detach a tool and confirm the change is
   reflected the next turn (no server restart required).
3. Send a message that forces a search, confirm a `SearchDoc`-backed tool block
   renders, then reload the session and confirm the same block replays.
4. Toggle a tool off for a single message using the frontend's per-message
   control, and confirm the request's `allowed_tool_ids` excludes it while the
   persona's other tools still run.

### What "working" looks like

- A newly added tool appears in the persona's tool list only after its `Tool` row
  is seeded, not just after the class is registered.
- A tool that raises inside `run` still produces a completed turn with a
  `GENERIC_TOOL_ERROR_MESSAGE`-shaped response, not a dead stream.
- Parallel search-like tool calls in one cycle never render overlapping citation
  numbers.

---

## 9. Footguns

- **`MemoryTool` bypasses `allowed_tool_ids`.** A user who toggles off every tool
  for a message will still get memory writes if `user.enable_memory_tool` is set.
- **`KnowledgeGraphTool` is registered but cannot run yet.** The knowledge graph is
  an incomplete feature. The class is in `BUILT_IN_TOOL_MAP`, but its
  `tool_constructor.py` dispatch branch is commented out and there is no fallback
  branch, so it is never added to a turn's tool set. Do not assume it runs because
  the class is in the map, and do not delete it as dead code.
- **`BashTool` is never persisted and uses a sentinel id.** The coding agent
  constructs it directly with `BASH_TOOL_SENTINEL_ID = 0`
  (`fake_tools/coding_agent.py`), not through `tool_constructor.py`, and it cannot
  be attached to a persona.
- **`fake_tools/` are not `Tool` subclasses.** `run_coding_agent_call` and
  `run_research_agent_call` (`fake_tools/coding_agent.py`, `fake_tools/research_agent.py`)
  are hand-rolled sub-agent loops that hand the LLM synthetic function schemas for
  internal control signals (`think_tool`, `generate_answer`, `generate_report`
  defined in `onyx/deep_research/dr_mock_tools.py` and `onyx/coding_agent/mock_tools.py`).
  These signals have no DB `Tool` row, never appear in `BUILT_IN_TOOL_MAP`, and
  never go through `run_tool_calls`; the coding agent dispatches its bash calls
  directly via `_run_bash_call`. The directory name suggests these are real tools;
  they are not.
- **Tool responses are dropped from saved chat history.** Only the tool-call
  *arguments* survive into the next turn's context; the `llm_facing_response` is
  replaced with a placeholder by `[[core-chat-loop]]`'s history construction. A
  tool that expects the model to recall its own past output must put the durable
  fact in the arguments or accept it will be re-fetched.
- **Merged tool calls mean the executed call is not the call the LLM wrote.**
  `_merge_tool_calls` collapses N calls to `SearchTool`/`WebSearchTool`/`OpenURLTool`
  into one before execution and before it enters history, so the model later sees
  the merged, expanded arguments rather than what it originally emitted.

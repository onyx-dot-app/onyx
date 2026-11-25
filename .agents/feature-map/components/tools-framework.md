# Tools Framework

> The shared machinery for every tool the chat model can call: the `Tool`
> interface, the built-in tool registry, per-model tool construction and gating,
> and research subagents. Concrete tools live in their own
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
  [[#parallel-by-default]] and [[#tool-name-is-lookup-key]]. Changing a tool
  definition can prevent a saved checkpoint from resuming ([[agent-runtime#restored-tools-must-match]]). The concrete tools are
  [[internal-search]], [[web-search]], [[image-generation]],
  [[code-execution]], [[mcp-and-custom-tools]], [[chat-preferences]]
  (`MemoryTool`) and [[file-store-and-user-files]] (`read_file`).
- **[[core-chat-loop]]** calls `construct_tools` once per model response and
  gives the tools to `chat/agent.py:ChatAgent` or
  `deep_research/agent.py:DeepResearchAgent`. `ChatAgent` binds them with its
  own `ToolContext`.
- **The sub-agents** run on the same runtime. `DeepResearchAgent` binds
  `skills_list` and the family's skill read tool in its research phase, and gets the skills
  catalog ([[skills]]). It passes the tools to each
  `deep_research/research_agent.py:ResearchAgent` child, which binds them with
  its own `ToolContext`.
- **[[citations]]** gets a block of citation numbers per search-like call.

---

## Scope

This component owns the `Tool` interface and `ToolContext`, tool construction
and its gates, the built-in tool registry, and the research-agent features.

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
copies the agent's built-in `Tool` rows into frozen `ToolConfiguration` models,
and its `persona__integration` rows into `IntegrationLinkConfiguration` models
(integration id and parsed `action_settings`), before the run starts. The MCP and OpenAPI
`Tool` rows of the agent are not copied. `construct_tools` opens its own short
DB session, so no session stays open for a turn that can last minutes.

**Construction per model.** `chat/execution.py:create_chat_agent` calls
`construct_tools` for each model response, so a multi-model turn has separate
tool instances. `construct_tools` returns a flat list. For built-in tools,
`tools/tool_constructor.py:_construct_tools_impl` walks the captured tools in
order and applies these gates:

1. A tool with `enabled=False` is skipped.
2. `tool_options.allowed` (`tools/models.py:ToolOptions`), the per-message
   choice that the client sends or the chat saved. A capability entry keeps a
   built-in tool by its id. An integration entry keeps the integration, and
   its optional `actions` keep only those action keys
   (`tools/models.py:IntegrationChatRequest.allowed_integrations`). The options
   only pick integrations and actions: the settings of the agent link of
   an integration still apply, so a request cannot drop a Blocked link.
   NULL keeps every tool and integration of the agent. The web composer
   (`web/src/lib/tools/hooks.ts`) sends a saved `actions` list back unchanged,
   and it does not rewrite the allow-list while a plugin catalog request has
   failed.
3. `is_available(db_session)`. An exception counts as "not available" and is
   logged.
4. A class-specific branch builds the instance, and some branches skip the
   tool with no error:
   - `SearchTool` is skipped when the search usage setting from
     `chat/files.py:determine_search_params` is `DISABLED`.
   - `OpenURLTool` is skipped when web search is off for the message and
     `DISABLE_VECTOR_DB` is set ([[web-search]]).

Then `integrations/chat_tools.py:build_integration_chat_tools` adds the MCP and
OpenAPI actions of the integrations that the agent can use, through the
integration tables ([[mcp-and-custom-tools]]). It drops each action that the
policy function (`integrations/policy.py:resolve_action_policies`) blocks, and
each integration whose credential does not resolve.

Two tools are added outside the built-in loop. `SearchTool` is added when the
request forces search on (`SearchToolUsage.ENABLED`), `DISABLE_VECTOR_DB` is
off, and the loop did not build it. `MemoryTool` is added when the
user's `enable_memory_tool` preference is set ([[#memory-tool-bypasses-filters]]). MCP and
OpenAPI actions receive stable qualified names with the integration id
(`mcp__<integration id>__<name>__<tool>`, `custom__<integration id>__<operationId>`),
independent of the other selected tools, and have `id = None`.

**Execution.** A tool implements `_run(invocation, context)` and returns a
`ToolResult`, or a `ChildRunWait` when it delegates to a sub-agent. Call data,
such as arguments, `call_index`, the cancellation signal and the progress
callback, comes in `agents/tools.py:ToolInvocation`. `invocation.messages` is
the model's view after compaction, as owned copies without result details
(`agents/tool_execution.py:_tool_view`); `invocation.recorded_results` holds
every recorded tool result before the call, with details and without
compaction: earlier steps, then this step's completed results. Tools only read
it. Use it for state derived from the whole conversation. `invocation.update`
can raise `AgentCancelled`; do not catch it. An update sent after `_run`
returns is dropped, and a result that arrives after the run closes is
discarded.
Per-request data, such as chat files, memory and the next citation number,
comes in `tools/models.py:ToolContext`. `ChatAgent._tool_context` and
`ResearchAgent._tool_context` build it when the call starts.

Code mode reads these `Tool` members: `code_mode_exposure` (abstract: `DIRECT`,
`IMMEDIATE` or `DEFERRED`; a tool with `result_from_children` must be
`DIRECT`), `code_mode_function_name` (MCP tools add their server as a
namespace and the integration's description as `namespace_description`)
and `code_mode_result` (the value and stub type a program receives); see
[[code-execution]]. A tool that must not run twice sets `interrupted_result`:
on restore, the runtime saves it as the result of a call that a lost
execution owner left running (`agents/tools.py:AgentTool`).
`inner_tools` lists the tools that run inside a tool's calls, such as the
functions of code mode programs; `chat/prompt_utils.py:callable_tools` reads it.
A call of a tool that the agent does not offer gets the agent's
`unknown_tool_hint` as its result, when the hook gives one
(`agents/tool_execution.py`). A chat agent's hook
(`chat/agent.py:ChatAgent._unknown_tool_hint`) says how to call a code mode
function from a program (`CodeModeTool.inner_call_hint`), and names the
offered tool for a name of another tool family's shapes.

A tool whose calls can wait for the user's approval sets `approval`
(`tools/models.py:ToolApprovalScope`): an integration action that its policy
asks for, or a built-in tool's `onyx:<operation>` action with no integration.
`approval_details(arguments)` gives each call's card (headline and payload), or
None for a call that runs without asking; it runs before any database work and
must not raise. The default shows the display name and the arguments. See
[[mcp-and-custom-tools#chat-approval-durable-wait]].

When the run completes normally, every call gets a result: `ToolBatch` answers
an unknown tool name, malformed arguments or truncated arguments with an error
result. On Stop or a run failure, a running call ends with no result (status
`CANCELLED` or `ERROR`) and renders with no details. `_invoke_tool` discards a
result that finishes after cancellation. Side effects that the tool already
made are not undone, so check `invocation.cancellation` before irreversible
work.

**Tool shapes.** The model's tool family (`LLMConfig.tool_family`: Claude
models, or all others) names some operations and takes their arguments in the
shape its models are trained on. One `Tool` class serves each operation; its
owning module maps each family to a shape (a name and an arguments model whose
pure `request()` gives the operation's typed input):
`tools/tool_implementations/code_mode/shapes.py:CODE_MODE_SHAPES` (`repl`/`poll` or `exec`/`wait`),
`tools/tool_implementations/sandbox/shapes.py:SHELL_SHAPES` (`bash(command, timeout, description,
run_in_background)` or `exec_command(cmd, workdir, yield_time_ms,
max_output_tokens)`, and `write_stdin` with `timeout` or `yield_time_ms` and
`max_output_tokens`), `tools/tool_implementations/subagents/shapes.py:AGENT_SHAPES` (`agent(description,
prompt)` or `spawn_agent(task_name, message)`; `send_message` with `to` or
`target`; only the OpenAI shape has `wait_agent`),
`tools/tool_implementations/skills/skill_tools.py:SKILL_READ_SHAPES` (`skill(skill)` or
`skills_read(name)`), and `tools/tool_implementations/open_url/open_url_tool.py:OPEN_URL_SHAPES`
(`web_fetch` or `open_url`, same arguments), and
`tools/tool_implementations/question/shapes.py:QUESTION_SHAPES`. Tool rows,
`in_code_tool_id`, persona assignments and approval action ids do not change
with the family. Each module also derives the names across families
(`SHELL_TOOL_NAMES`, `SPAWN_TOOL_NAMES`, `AGENT_START_TOOL_NAMES`,
`WAIT_AGENT_TOOL_NAMES`, `SKILLS_READ_TOOL_NAMES`, `OPEN_URL_TOOL_NAMES`,
`QUESTION_TOOL_NAMES`), which the name-keyed sites
use, because a chat's history holds calls of both families. A shape also
names the arguments that other code reads by name, as fields: the shell
card's `command_argument` and `workdir_argument`, and the spawn errors'
`spawn_name_argument` and `spawn_task_argument`. A sandbox turn carries its
`ShellShape` (`SandboxTurn.shell`). The agent shape tells whether the root
waits for the agents that it created by itself (no `wait_name`, the Claude
shape; [[chat-persistence]]); `ChatAgent` picks the root's instructions from
it. A call of another family's name for a tool that the agent offers gets a
result that names the agent's own (`unknown_tool_hint`). A description
that names another tool is a template that `Tool.describe(called_name)`
fills: with the tool's name, or in code mode with its program function
(`ToolStubs.called_names`); `ChatAgent.called_name` gives the prompt the
same names.

**Chat skill tools.** `chat/execution.py:create_chat_agent` adds `skills_list`
and the family's skill read tool, `skills_read` or `skill`
(`tools/tool_implementations/skills/skill_tools.py`), to the
chat agent's configured tools when the turn's user has a chat skill
([[skills]]): the agent's tools and the request's tool options do not
remove them. Restored and child agents receive them with the other configured
tools. The tools hold the user and `with_sandbox` (the turn's `sandbox_tools`;
chat built-ins need the VM) and read the user's current chat skills on each
call; the read tool checks that the user can still see the skill and
returns its SKILL.md, frontmatter included, up to 32,000 characters per call
(`SKILL_READ_MAX_CHARS`). A longer text ends with a note that gives the
`start_char` offset of the next call. `skills_read` copies no files; the
sandbox tool `load_skill` copies a skill into the VM. The Deep Research orchestrator binds
both in its research phase, its research agents bind both, and each gets the
skills catalog. The two tools have no
tool catalog rows. A direct call renders as a generic tool card with a short
JSON summary, not the SKILL.md text. In code mode they are `IMMEDIATE`
functions that return text (`tools.skills_list`, `tools.skills_read` or
`tools.skill`), and the
chat agent's skills catalog names them so. SKILL.md text that the program
prints or returns goes into its `code_mode_delta` packets; the web timeline
does not show program output ([[chat-frontend]]). Deep Research does not use
code mode and calls them directly.

**Chat sandbox tools.** `chat/execution.py:create_chat_agent` also adds
`exec_command`, `write_stdin` and the file tools (`apply_patch`, or `edit` and
`write` when the turn's model is Claude) ([[code-execution]]) when
`ChatTurnSetup.sandbox_tools` is set. `chat/process_message.py:prepare_chat_turn`
sets it in one expression: harness sandboxes run
(`microvm/configs.py:HARNESS_SANDBOX_ENABLED`), the user is not anonymous, the
chat is not incognito, the turn has one response and is not Deep Research,
and no Slack or Discord bot sent it (`SendMessageRequest.origin`). The agent's tools and
`allowed_tool_ids` do not remove them. They have no tool catalog rows, so no
admin switch, picker entry or forced-tool request reaches them.

**Argument models.** A tool declares its arguments as one Pydantic
`*Arguments` model. `parse_tool_arguments` validates calls with it, and
`tools/interface.py:tool_definition_from_arguments` makes the tool's
definition from its JSON schema without titles, so the schema and the parser
cannot drift. Field descriptions, defaults and constraints go on the model.
With `strict=True` the function makes a closed OpenAI strict schema: every
argument is required, and a defaulted argument accepts null. For a defaulted
argument whose type does not accept null, `parse_tool_arguments` reads null as
the default. A strict model has only inline argument types (a `Literal`, not an
enum or a nested model) and no object argument such as a mapping, because
strict mode requires every object to be closed. Parsing ignores unknown arguments unless the model
sets `extra="forbid"`, because not every provider enforces the schema. A
validation error names the argument and returns to the model as a tool error.
The skill, subagent, memory, file reader, knowledge graph, internal search, web
search, open URL, Python, image generation, and the code mode run
and wait tools use it.

**Default subagent controls.** `ChatAgent` adds the tools in
`tools/tool_implementations/subagents/subagent_tools.py` when it receives a child factory.
`chat/agent.py:build_chat_agent` gives one when `with_subagents` is set: the turn's caller
delivers follow-up responses, the request sets `accepts_follow_ups`, as the web chat does, and
the turn has one model.
Mobile, the CLI and other API clients omit the flag. Incognito chats and one-shot callers
(`chat/process_message.py:run_chat_turn`, used by Slack, evals and the non-streaming API)
omit these controls. Preparation also rejects deep research in incognito before it saves
the user message (`chat/process_message.py:prepare_chat_turn`). These controls have no
catalog rows or persona switches. `chat/agent.py:chat_subagent_factory` builds children
with `build_chat_agent`, the same builder that restores saved children.
Each child builds its own controls and conversation state.
Agents nest two levels below the root (`agents/agent_coordination.py:MAX_CHILD_DEPTH`); an agent
at that depth gets no spawn tool. A chat runs at most ten active background agents on a branch
(`chat/run_store.py:MAX_RUNNING_AGENTS`); `chat/models.py:AgentResultState.is_active` defines them:
unfinished runs with a result row, so foreground workers never count. A spawn beyond that
returns a tool error, and inbox work for an idle agent waits until a run finishes. Each run checks the owner's token rate limits: root turns when they are sent
or leave the queue, and runs that agents start in `chat/run_store.py:ChatRunStore.reserve_run_id`,
where inbox work checks capacity first. The `stop-subagents` route takes the chat lock, drops
pending work for agents below the root (`db/chat_inputs.py:drop_agent_work__no_commit`), and stops
the active background agents with the reason "user". A parent's Stop refuses its later spawns.
A stopped run records `STOPPED_BY_USER`: `list_agents` shows "stopped by the user", and its
result wakes no agent; the root reads it at its next step.
The controls stay direct in code mode. Each child inherits code mode but owns
its own code cells.
`list_agents` shows running and suspended agents, and agents whose latest run belongs to the
current user turn (`AgentInfo.current_turn`); `include_finished` adds the rest. It marks the caller
and accepts a `path_prefix` filter. An agent can message
any other agent in the tree. `send_message` reaches the next model step or starts an idle agent
with fresh limits; a message to the root waits for the root's next run and never starts one.
`send_message(delivery="queue")` waits for normal completion or the step limit. `interrupt_agent` cancels one
agent's active run, except the caller's and the root's, including its in-flight tool calls and
foreground children; agents it started in the background keep running. The
interrupted run reports no result and starts no follow-up; its conversation remains.
Cancellation is cooperative: the runtime signals each tool's `ToolInvocation.cancellation`
and discards results that arrive later, but a tool that does not check the signal keeps
running until it returns.
Results reach the agent's spawner automatically before its next model call.
A subagent suspends before completing until the results of children it spawned are available.
The root can finish its response while background children continue.
An idle agent starts a follow-up response for unread child results.
Only the root gets the wait tool (`wait_agent`, in the OpenAI shape only) and the `ROOT_AGENT_INSTRUCTIONS` prompt block, which names the wait tool when the shape has one; the wait rule is in [[chat-persistence]]. These results
stay in model history; only the parent's response appears as a chat message.
Tool replies use concise text, and models see agent paths, never IDs. `send_message` takes
a `target` (`to` in the Claude shape), `interrupt_agent` a `target`, and `wait_agent` `targets`: a path from spawn/list, or
`..` for the caller's parent (`tools/tool_implementations/subagents/subagent_tools.py:_find_agent`, over `discover_agents`). A path names one agent on the branch: the spawn tool refuses a name whose
path any visible agent holds, finished agents included (`agents/agent_coordination.py:register_child`).

**Question tool.** `tools/tool_implementations/question/question_tool.py:QuestionTool`
asks the user 1-4 multiple-choice questions and waits for the answers. Only the
root `ChatAgent` gets it (`question_tool`, a factory that the agent calls with
the shape), after code mode wraps the configured tools, so it stays direct and
subagents never get it. Each tool family has one shape
(`tools/tool_implementations/question/shapes.py:QUESTION_SHAPES`, keyed by the
agent's `tool_family`): its name, its arguments and its description, whose limits
come from the arguments' field bounds. The name is `ask_user_question` for Claude
models and `request_user_input` for others; a restored root gets the tool when its
saved step declared one, in the active model's shape
(`chat/restoration.py:restore_chat_agent`). Which turns offer it, and how its call
parks and resumes, is [[mcp-and-custom-tools#chat-approval-needs-waiting-client]].
The renderer parses a live call's arguments in the shape of its name
(`QUESTION_SHAPES_BY_NAME`); a reload rebuilds the card from the request row.
The shapes differ:
`request_user_input` takes 1-3 questions with 2-3 options and an `id` each;
`ask_user_question` takes the shape Claude models are trained on, 1-4 questions
with 2-4 options, `multiSelect` and no `id`. Both are `ToolArguments` and ignore the
extra keys that the model adds. Each shape's `request()` gives the same `ToolQuestion` list; a
Claude question's ID is its text, which must be unique, so the model reads
Claude's answers by question text. The card, the saved row, the answers and
restoration use only that list. Its arguments are not
strict: the nested question models are `$defs` references. A question sets
`multi_select` when more than one option can apply; the answers route
(`chat/tool_questions.py:card_answers`) takes several options only for such a
question and keeps the chosen options in the question's order. The model reads a card
answer as `{"answers": {"<id>": {"answers": ["<label>", ..., "user_note: <text>"]}}}`,
with every chosen label in the question's order,
or the text that the user typed, after the query hook and with nothing added
(`chat/tool_questions.py:question_answer`).

**Subagents.** `DeepResearchAgent` spawns a `ResearchAgent` child and returns
`ChildRunWait`. The runtime calls `result_from_children` when the child ends.
Research control functions, such as `generate_report`,
are plain `AgentTool` objects with no `Tool` row, and
`chat/renderer.py:HIDDEN_TOOLS` keeps them out of the stream.

---

## Contracts and traps

1. `memory-tool-bypasses-filters` **`MemoryTool` bypasses the tool options
   and the agent's tools.** `tools/tool_constructor.py:_construct_tools_impl`
   adds it after the agent tool loop whenever its `enable_memory_tool` argument
   (the user's preference, captured in `ChatTurnSetup`) is set.
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
   `run_python` result JSON ([[code-execution#run-python-result-json]]). A
   tool whose `content` cuts its value sets `full_value` too: a code mode
   program receives it
   (`tools/tool_implementations/code_mode/stubs.py:program_value`), and chat's
   sandbox spill always writes it to a file ([[code-execution]]). Set it only
   when the cut leaves something out. Only `ToolResult`, what a tool returns,
   has the field; the recorded `ToolResultMessage` shares the other fields
   (`llm/models.py:ToolResultFields`), so nothing saves it. Code that takes
   any result or message checks `ToolResultFields`.
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
   completion emit it. Streamed arguments
   show live only for some tools (`chat/renderer.py:MessageRenderer.consume`):
   `run_python`, the code mode run tool (`exec` or `repl`) and `generate_image` stream argument deltas, the file tools
   (`write`, `edit`, `apply_patch`) report `file_tool_progress`. Every stream
   is throttled
   ([[streaming-protocol]]). Code mode calls render with
   `chat/renderer.py:CodeModeRenderer`, a `ToolRenderer` that
   `tool_renderer` picks by tool name; question calls render only their card
   (`chat/renderer.py:QuestionToolRenderer`: `tool_question_request` and
   `tool_question_resolved`, then a section end). A result that a run release hook sets
   streams through `ToolRenderer.amend`. Only a code mode card renders what
   the amendment added (the cell's closing record), after the call's section
   end, live and on replay. The generic display adds nothing live; replay
   shows the saved, amended result. Saved responses replay through the same renderer
   (`chat/presentation.py:replay_response`), so a change here changes reload too.
8. `durable-details-registered` **A new `details` type must be registered
   once.** `db/models.py:SavedToolResultDetails` is the one union of saved
   details, keyed by the model's `type` literal. `StoredToolResult` saves
   through it, `chat/checkpoint.py:CHECKPOINT_PAYLOAD_TYPES` tags each member
   `result.<type>.v1`, and temporary chats keep it
   (`chat/models.py:serialize_incognito_message`). A new `type` literal missing
   from the union fails every save with a `ValidationError`. A tool that code
   mode programs can call also needs its details type in
   `tools/tool_implementations/code_mode/models.py:CodeModeCallDetails`, the
   union of nested call details.
   `tools/tool_implementations/code_mode/cells.py:durable_details` drops
   details of any other type, so the nested call saves and replays without
   them. A subclass that keeps its parent's `type` literal saves as
   the parent and drops its own fields with no error.
   `chat/agent.py:ChatAgent._finalize_tool` replaces each `SearchDocsResponse`
   with `chat/models.py:ChatSearchResult` in this way, and its `staged_files`
   are not saved. Only the unwired checkpoint handoff path reads the registry
   ([[agent-runtime]]), so a missing registration fails only that path and its
   tests. Saved rows and checkpoints keep the `type` value, so never rename it.
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
   `ToolEndEvent`. Before `Run.record_tool_results` records and streams a
   result, `Agent.prepare_tool_result` can replace it, one result at a time in
   completion order; chat's sandbox spill uses it, and then adds the file copy
   status line to the root agent's sandbox and code mode results
   ([[code-execution]]). After a
   cancel between `Run.record_tool_results` and `finish_tool`, the saved
   result is the recorded result, before `after_tool_call`, and no
   `ToolEndEvent` is sent. A tool whose calls must not overlap
   returns `ToolExecutionMode.SEQUENTIAL` from `execution_mode`, as
   `MemoryTool` does. This orders only calls with the same name, or with the
   same `sequence_group` (the sandbox file tools share one): each starts
   after the previous one is finalized, and a call that waits for a child run
   or input blocks the calls after it.
10. `tool-name-is-lookup-key` **`Tool.name` is a lookup key and must be a valid
   function name.** `ToolBatch`, `ToolRenderer` and the `tool_ids` map in
   `chat/execution.py:ChatTurnExecution._run_response` find tools by name, so
   two tools with one name make one unreachable. OpenAI and Bedrock accept only
   `[a-zA-Z0-9_-]`. Tools that take user-supplied names, such as MCP and OpenAPI
   tools, use `tools/tool_name.py:normalize_external_tool_name`. MCP names are
   `mcp__<server id>__<server name>__<tool>`; OpenAPI names are
   `custom__<tool id>__<operation>`. The ID comes first, so a user-chosen name
   cannot make two tools collide.
   Names fit 64 characters; sanitation and truncation add a stable hash.
   Execution retains the original upstream name. Users see the tool's
   `display_name`. Each call's `ToolExecutionRecord.display_name` keeps it,
   and `tool_call.display_name` saves it, so replay reads it from the call.
   `CustomToolStart` carries it (`chat/renderer.py:ToolRenderer`), and code
   mode calls keep it in `CodeModeCall.display_name`. Web, mobile and CLI
   labels, including auth cards, read only the start packet's field.
11. `replay-by-class-name` **Replay finds a tool by its name or its class
   name.** Saved responses replay by tool name
   ([[#renderer-dispatches-by-name]]). Older messages with no saved response
   replay through
   `server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`,
   which dispatches on `Tool.in_code_tool_id`, the class name. Legacy replay
   skips calls whose tool row is missing ([[chat-persistence#tool-id-not-foreign-key]]).
12. `calls-are-merged` **Merged calls share one execution and one result.**
    `agents/tool_execution.py:ToolBatch._start_compatible_calls` merges later
    calls to the same tool when the tool sets `merge_list_argument` and all
    other arguments match (`tools/interface.py:merge_tool_arguments`). Both
    lists must be non-empty string lists, and the merged list must stay within
    `merge_list_limit` (`open_url` sets `MAX_URLS_PER_CALL`, search
    `MAX_QUERIES_PER_CALL`). No merge happens
    when the run has `before_tool_call`, or when arguments are truncated or
    invalid. A parallel tool can merge calls that are not next to each other;
    a `SEQUENTIAL` tool merges only up to its first call that cannot merge. One
    execution runs with the first call's `call_index`, and each merged call
    gets every progress update and the pooled result. A merged execution must
    return a `ToolResult`: a `ChildRunWait` fails the batch with `ValueError`.
    Search, web search and `open_url` merge. A tool whose calls must stay
    separate leaves `merge_list_argument` unset.

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
- [[code-execution]]: Python, code mode, and sandbox tools.
- [[observability]]: `Tool.run` opens one `function_span` per call.

---

## Recipes

- `built-in-tool` **A built-in tool.** Copy `FileReaderTool`
  (`tools/tool_implementations/file_reader/`). List the current set in
  `tools/built_in_tools.py:BUILT_IN_TOOL_MAP`. The INDEX.md Common tasks row
  gives the recipes in other documents that the task also needs.
  1. Put the class in `tools/tool_implementations/<name>/`, subclass `Tool`,
     and implement `_run`. Declare the arguments as one `*Arguments` model
     ("Argument models" above). Build `tool_definition()` from it with
     `tools/interface.py:tool_definition_from_arguments` (`strict=True` for a
     built-in tool), and parse calls with
     `tools/interface.py:parse_tool_arguments`.
  2. Add it to `BUILT_IN_TOOL_TYPES` and `BUILT_IN_TOOL_MAP`. Define its
     name as a `NAME` class attribute, or as a `name` property that reads
     the tool family's shape when the families name it differently
     (**Tool shapes** above).
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
     `deep_research/research_agent.py:ResearchAgent.__init__`, which includes
     the skill tools (`SKILL_TOOL_NAMES`). Add a search tool there if deep research must use it.
     Nothing reports a tool that is left out.
- `gate-a-tool` **Gate a tool.** Pick the narrowest gate that matches who decides:

  | Who decides | Gate |
  |---|---|
  | The deployment cannot run it (no provider, no service) | `is_available` |
  | An admin, per agent | persona attachment (`Persona__Tool`) |
  | An admin, for all agents | `Tool.enabled` ([[mcp-and-custom-tools]]); built-in and MCP tools only |
  | A user, per message | `tool_options.allowed`; `TOOL_VISIBILITY_CONFIG` decides whether chat offers the toggle |

  Do not inject a tool outside the agent tool loop as `MemoryTool` does, unless
  it is a user-level feature. Such a tool escapes every admin and per-message
  control.
- `investigate-tool-not-called` **Investigate "the model never calls tool X".** Walk the gates in order.
  Check that the tool is attached to the agent and that `Tool.enabled` is true.
  Check the `tool_options` that the client sent or the chat saved. For a built-in tool, run its
  `is_available` in a shell, or look for "Failed checking availability" in
  `backend/log/api_server_debug.log`; the "Skipping tool" line is at debug
  level. Check the branch skips in gate 4: search usage `DISABLED`, an
  anonymous user on an OAuth or passthrough OpenAPI tool, and `open_url` with
  no vector DB. For Default Chat, check the user's plugin preferences. For MCP,
  look for the credential warning. Last, check for a name collision (Known
  issues).
- `force-tool-call` **Prefer an Action for the current request.** Send
  `tool_options.preferred` with the message: a capability (a built-in tool id) or
  an action (an integration id and an action key, matched by
  `Tool.integration_action`).
  The trailing reminder names that Action's
  operations on every model step. The model may call another tool or answer directly;
  the preference does not change tool definitions or execution permissions.
  Use a scripted model to test a required call deterministically, as in
  `backend/tests/integration/tests/llm_workflows/test_tool_policy_enforcement.py`.
  When project files replace retrieval, preparation omits an enabled, configured,
  allowed Search preference and its reminder for that request.
  Unavailable preferred Actions return `BAD_REQUEST`; Deep Research rejects a
  preference at request validation. Non-null `forced_tool_id` requests are rejected
  with migration guidance, rather than silently weakening the old contract.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/tools/`.
- External dependency unit tests: `backend/tests/external_dependency_unit/tools/`.
- Integration tests: `backend/tests/integration/tests/tools/`.
- By hand, turn web search off for one message. Other tools must still run, and
  `open_url` must not fetch live pages.

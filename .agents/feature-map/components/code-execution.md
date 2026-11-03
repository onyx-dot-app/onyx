# Code Execution

> Runs code for the user: `run_python` runs Python, and the coding agent's
> `bash` runs shell commands in a repository. Both are HTTP clients of an
> external Code Interpreter service, so no user code runs in an Onyx process.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## User experience

- **An end user** asks for a calculation, a chart or a file conversion. The
  assistant writes Python, the user sees the code, then the output as it
  streams. Files that the code writes, such as a chart or a CSV, appear as
  downloads. Files that the user attached to the chat are available to the code.
- **An end user** asks a question about a public GitHub repository. The coding
  agent downloads the repository and runs shell commands to explore it. The
  user sees its thinking and bash steps, then an answer.
- **An admin** opens the Code Interpreter admin page. It shows whether the
  service is reachable and healthy, and has a switch that turns code execution
  off for the whole deployment.
- **When the admin switch is off, the service is unreachable, or the URL is
  set to an empty value**, the model is not offered `run_python` or the coding
  agent. The user sees no error. When code fails or
  times out, the user sees the error output and the turn continues.

---

## Scope

This component owns `PythonTool`, `BashTool`, the Code Interpreter client and
its version gates, the one-row settings table with its admin API and page, and
the meaning of `BASH_TOOL_SENTINEL_ID`.

It does not own:
- The Code Interpreter service. It is a separate deployment with its own
  release line. This repository has only the client and a pinned image tag in
  the Docker Compose files.
- The coding-agent loop and its wrapper tool `CodingAgentTool`
  ([[tools-framework]]). This document describes only the session that the loop
  creates for bash.
- Access to generated files. They use the chat-session stamp that
  [[file-store-and-user-files]] defines.
- The Craft sandboxes ([[craft-sandboxes]]). They are a separate system and do
  not use the Code Interpreter client.

---

## Architecture

```
run_python (stateless, one call = one execution)
  PythonTool._run
    _select_files_for_staging        referenced files first, then recent, inside caps
    _upload_and_stage                upload once per (filename, hash) per tool instance;
                                     best effort across parallel calls
    client.execute_streaming         POST /v1/execute/stream (SSE); on 404 -> /v1/execute
    per output event                 invocation.update(ToolProgress(details=PythonExecutionDelta))
    generated files                  download -> file store (session stamp)
                                     -> delete the service copy

bash (one session per coding-agent call)
  CodingAgentTool._run               tools/tool_implementations/coding_agent/
    coding_sandbox_session           download HEAD archive -> upload -> create_session
                                     (1 h TTL) -> extract -> session_id
    CodingAgent(BashTool(BASH_TOOL_SENTINEL_ID, session_id))
    spawn_agent -> ChildRunWait      the child run calls bash, one call at a time
    add_completion_cleanup           after the child's first run completes or releases
                                     and its workers drain: mark the agent's sandbox
                                     unavailable, delete_session; best effort, the
                                     TTL is the backstop
```

**Availability.** `PythonTool.is_available` needs three things: a non-empty
`CODE_INTERPRETER_BASE_URL`, `CodeInterpreterServer.server_enabled`, and a
healthy service. `BashTool.is_available` adds a version check:
`client.supports(...)` compares the service version with the `@requires`
minimum of the session methods. `CodingAgentTool.is_available` returns
`BashTool.is_available`. The health result is cached for 30 seconds per base
URL in the process (`_HEALTH_CACHE_TTL_SECONDS`). The admin health endpoint
makes a live check, and every live check refreshes that cache.

**Input files.** `PythonTool` reads the turn's chat files from
`ToolContext.chat_files`. `chat/agent.py:ChatAgent._finalize_tool` attaches the
raw source files of search hits to `ChatSearchResult.staged_files`
(`chat/files.py:build_python_chat_files_from_search_docs`, connector-origin
files only). `chat/agent.py:ChatAgent._update_tool_context` merges them into
`chat_files` after the step and skips a filename already present, so the code in
a later step can open a spreadsheet that search found. Staging has caps on file
count, total bytes and parallel uploads. When files are dropped, the model gets
a `staging_notice` in the result.

**Busy service.** Execution, session creation and session bash calls go through
`CodeInterpreterClient._send_with_admission_retry`. It retries HTTP 429 and 503,
follows `Retry-After`, and stays inside the call's time budget. Then it raises
`CodeInterpreterBusyError`. File upload, download, delete, session delete and
health calls are not retried.

---

## Contracts and traps

1. `isolation-is-service-job` **Isolation is the service's job, not Onyx's.**
   Nothing in `backend/onyx` sandboxes code or checks that the service does.
   Onyx trusts the URL in `CODE_INTERPRETER_BASE_URL`. The "no network access"
   rule for bash sessions exists only as text. The model reads it in
   `coding_agent/tool_definitions.py:BASH_TOOL_DESCRIPTION` and the coding-agent
   prompt (`prompts/coding_agent/coding_agent.py:CODING_AGENT_PROMPT`).
   `BashTool.DESCRIPTION` is not sent to the model, because `CodingAgent`
   registers its own bash definition. Treat a change to what that URL may point
   at as a security change.
2. `default-url-not-empty` **The default URL is not empty.**
   `CODE_INTERPRETER_BASE_URL` defaults to `http://localhost:8000` in
   `configs/app_configs.py`. Only an explicit empty value turns the tools off
   without a network call. An unset value makes every turn depend on the health
   check, which fails when nothing listens.
3. `truncate-before-model` **Truncate output before it reaches the model.**
   Both tools pass stdout and stderr through
   `tools/tool_implementations/utils.py:truncate_output`, each capped at
   `CODE_INTERPRETER_MAX_OUTPUT_LENGTH`. Only the live `PythonExecutionDelta`
   stream is complete. The saved `details` hold the truncated output, so a
   reloaded chat shows truncated output. When live output was streamed,
   `chat/renderer.py:ToolRenderer.update` sends the final result with empty
   stdout and stderr and only the new file IDs, so the client must keep the
   deltas it already has.
4. `errors-are-results` **Execution errors are results, not exceptions.** Both
   `_run` methods catch client errors and return the result JSON with
   `exit_code=-1` and `error` set. The model sees the failure and can fix its
   code. `Tool.run` is a second guard for both
   ([[tools-framework#run-errors-become-results]]): the coding agent calls
   `BashTool.run` from `coding_agent/agent.py:CodingAgent._bash`.
5. `run-python-result-json` **`LlmPythonExecutionResult` is saved in two
   forms.** `tools/models.py:LlmPythonExecutionResult` is the model text, as
   JSON in `content`, and the typed `details` that chat saves in
   `ToolCall.result` and in checkpoints. Checkpoints store `details` under a
   stable tag in `chat/checkpoint.py:CHECKPOINT_PAYLOAD_TYPES` (`tool.python.v1`,
   `tool.bash.v1`, `coding.result.v1`). Register a new details type there, and
   keep each tag able to parse old payloads, or checkpoint restore fails.
   `server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`
   parses the JSON for messages saved before response items existed. Both
   readers, and `db/chat_response.py:_extract_referenced_file_descriptors`,
   take the file ID from the last segment of `file_link`. Saved rows keep old
   data, so a field rename or a new `file_link` format must keep every reader
   able to parse it.
6. `generated-files-need-session` **Generated files need the chat session ID.**
   `PythonTool` saves them with
   `file_store/utils.py:chat_image_gen_metadata` and the chat session ID.
   `tools/tool_constructor.py:_require_chat_session_id` raises when a caller
   builds the tool without one. The access rule is in
   [[file-store-and-user-files]].
7. `bash-tool-sentinel` **`BashTool` exists only inside the coding agent.** It
   has no `Tool` row and is not in `BUILT_IN_TOOL_MAP`.
   `tools/tool_implementations/coding_agent/coding_agent_tool.py:CodingAgentTool._run`
   builds it with `BASH_TOOL_SENTINEL_ID = 0`. Its calls are saved with the
   coding agent's child run and replay on reload, but they have no `tool_id`.
   Persona attachment, `Tool.enabled` and `allowed_tool_ids` act on
   `CodingAgentTool`, not on `bash`.
8. `bash-calls-sequential` **Bash calls in one coding-agent call share a file
   system and run in order.** `coding_agent/agent.py:CodingAgent` registers
   bash with `ToolExecutionMode.SEQUENTIAL` on purpose. Do not make it
   parallel.
9. `coding-sandbox-one-run` **The coding sandbox lives for one child run.**
   `CodingAgentTool._run` registers the sandbox cleanup with
   `add_completion_cleanup` on the first run. The cleanup sets
   `CodingAgent.is_sandbox_available` to false, and
   `coding_agent/agent.py:CodingAgent._prepare_step` then rejects a new run. Before
   a feature sends a follow-up run to a coding agent, tie the cleanup to the
   agent's lifetime. Only a locally owned child run can register the cleanup.
10. `run-python-stateless` **`run_python` has no state between calls.** Each call
   is a new execution, and variables do not carry over. `run_python` is a
   `PARALLEL` tool, so the calls of one model step run at the same time on one
   `PythonTool` instance.
   `tools/tool_implementations/python/python_tool.py:PythonTool._uploaded_file_cache`
   only reduces repeat uploads, with no lock: two parallel calls can upload
   the same file. Do not add other state that calls share. A generated file is
   not an input to a later call in the same turn. In a turn that persists
   content, it becomes an input in later turns only when the answer text
   contains its file ID: `db/chat_response.py:_extract_referenced_file_descriptors`
   then attaches it to the message, and the next turn loads message files as
   chat files. A content-free turn saves no tool calls, so it attaches none.
11. `keep-run-python-name` **Do not rename `run_python` to `python`.** OpenAI
    rejects a function named `python` (the comment on
    `tools/tool_implementations/python/python_tool.py:PythonTool`).
12. `version-gate-new-routes` **A new service route needs a version gate.** The
    service ships on its own release line, and a deployment can run an older
    image. Mark a client method that needs a newer service with
    `@requires("x.y.z")`
    (`tools/tool_implementations/python/code_interpreter_client.py:requires`),
    and check it with `CodeInterpreterClient.supports` in `is_available`. Otherwise an older service makes the tool appear and then
    fail on every call. `execute_streaming` shows the other pattern: it falls
    back to `/v1/execute` when the service answers 404.
13. `single-settings-row` **The settings table has exactly one row.**
    `db/code_interpreter.py:fetch_code_interpreter_server` uses `.one()`. A
    migration seeds the row with `server_enabled=true`. Without the row,
    `is_available` raises and both tools are hidden.

---

## Decisions

- **`run_python` is stateless and `bash` has a session.** A Python call is one
  self-contained script, so no session cleanup is needed. The coding agent
  explores a repository over many commands, so it needs a file system that stays
  between calls. The session TTL removes the pod if Onyx crashes before it
  deletes the session.

---

## Known issues

- **Uploaded input files stay on the service.** `PythonTool` does not delete
  staged files, because its upload cache reuses their IDs.
  `coding_agent/agent.py:coding_sandbox_session` does not delete the uploaded
  repository archive (up to 500 MB). The service's own file TTL removes them.
  Onyx cannot see that TTL.
- **The coding agent reaches only public repositories.**
  `tools/tool_constructor.py:_construct_tools_impl` builds `CodingAgentTool`
  without a `github_token`, so `coding_sandbox_session` downloads without
  credentials.
- **Nothing resumes an interrupted coding-agent call.** After a process stops,
  the next read of the turn marks it ERROR
  (`chat/run_store.py:ChatRunStore._load_status` calls
  `db/chat_checkpoint.py:interrupt_response__no_commit`). The cleanup never
  runs, so the sandbox stays until its 1 h TTL. Also,
  `chat/subagents.py:ChatAgentDirectory.restore_agent` raises for a coding
  agent: the coding child is saved without a restoration configuration.
- **Stop does not abort a running execution.** Neither tool cancels its HTTP
  request. A bash call blocks until the service returns, up to
  `CODE_INTERPRETER_DEFAULT_TIMEOUT_MS` plus 10 s, and the sandbox delete waits
  for it. A `run_python` stream stops at its next output chunk. The result is
  discarded, and generated files that `PythonTool` already saved belong to no
  `ToolCall`.

---

## Dependencies

- [[tools-framework]]: the `Tool` interface, construction, and the coding
  agent.
- [[file-store-and-user-files]]: generated files and their session stamp.
- [[streaming-protocol]]: the Python, bash and coding-agent packets.
- [[authorization]]: `require_permission(FULL_ADMIN_PANEL_ACCESS)` guards the admin
  API.

---

## Recipes

- `local-code-interpreter` **Run a local Code Interpreter service.** Start the `code-interpreter`
  service from `deployment/docker_compose/docker-compose.yml` with the
  `deployment/docker_compose/docker-compose.dev.yml` overlay, which publishes
  port 8000 on the host. That
  matches the default `CODE_INTERPRETER_BASE_URL` for a backend that runs on the
  host. Check it with `GET /api/admin/code-interpreter/health`
  through the frontend.
- `investigate-python-not-run` **Investigate "the model never runs Python".** Check, in order: that
  `CODE_INTERPRETER_BASE_URL` is set and not empty
  ([[#default-url-not-empty]]); that the admin switch is on
  ([[#single-settings-row]]); that the admin health endpoint reports healthy;
  for the coding agent, that the service version supports the session routes
  ([[#version-gate-new-routes]]). The agent and per-message gates are in
  [[tools-framework#investigate-tool-not-called]].
- `client-method-new-route` **A client method for a new service route.** Copy
  `CodeInterpreterClient.create_session`: a `@requires` minimum version and a
  call through `_send_with_admission_retry` when the service can be busy. List
  the current methods in `CodeInterpreterClient`. Add the method to the
  `client.supports(...)` check of each tool that uses it.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/tools/` (the Python tool availability and
  coding-agent files) and the `python/`, `bash/` and `coding_agent/` folders
  under `backend/tests/unit/onyx/tools/tool_implementations/`.
- External dependency unit tests, against a running service:
  `backend/tests/external_dependency_unit/tools/`.
- Integration: `backend/tests/integration/tests/code_interpreter/`.
- By hand, ask for a chart. The image must download, and it must still show
  after a reload. Turn the admin switch off: the next message must have no
  `run_python` call and no error.

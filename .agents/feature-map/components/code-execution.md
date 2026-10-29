# Code Execution

> Runs code for the user: `run_python` runs Python, and the coding agent's
> `bash` runs shell commands in a repository. Both are HTTP clients of an
> external Code Interpreter service, so no user code runs in an Onyx process.

**Verified against:** `a4e97fcea1` (2026-10-29)
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
  PythonTool.run
    _select_files_for_staging        referenced files first, then recent, inside caps
    _upload_and_stage                upload once per (filename, hash) per tool instance
    client.execute_streaming         POST /v1/execute/stream (SSE); on 404 -> /v1/execute
    per output event                 PythonToolDelta packet
    generated files                  download -> file store (session stamp)
                                     -> delete the service copy

bash (one session per coding-agent call)
  run_coding_agent_call              tools/fake_tools/coding_agent.py
    _setup_session                   download HEAD archive -> upload -> create_session
                                     (1 h TTL) -> extract -> yield session_id
      BashTool(BASH_TOOL_SENTINEL_ID, session_id)
      _run_bash_call per LLM call    POST /v1/sessions/{id}/bash, one at a time
    finally: delete_session          best effort; the TTL is the backstop
```

**Availability.** `PythonTool.is_available` needs three things: a non-empty
`CODE_INTERPRETER_BASE_URL`, `CodeInterpreterServer.server_enabled`, and a
healthy service. `BashTool.is_available` adds a version check:
`client.supports(...)` compares the service version with the `@requires`
minimum of the session methods. `CodingAgentTool.is_available` returns
`BashTool.is_available`. The health result is cached for 30 seconds per base
URL in the process (`_HEALTH_CACHE_TTL_SECONDS`). The admin health endpoint
makes a live check, and every live check refreshes that cache.

**Input files.** `run_tool_calls` passes the turn's chat files to `PythonTool`.
`chat/llm_loop.py:run_llm_loop` also adds the raw source files of search hits
that connectors stored (`chat/files.py:build_python_chat_files_from_search_docs`),
so the code can open a spreadsheet that search found. Staging has caps on file
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
   rule for bash sessions exists only as text: the docstring on
   `tools/tool_implementations/python/code_interpreter_client.py:CodeInterpreterClient.execute_bash_in_session`
   and the `BashTool` description that the model reads. Treat a change to what
   that URL may point at as a security change.
2. `default-url-not-empty` **The default URL is not empty.**
   `CODE_INTERPRETER_BASE_URL` defaults to `http://localhost:8000` in
   `configs/app_configs.py`. Only an explicit empty value turns the tools off
   without a network call. An unset value makes every turn depend on the health
   check, which fails when nothing listens.
3. `truncate-before-model` **Truncate output before it reaches the model.**
   Both tools pass stdout and stderr through
   `tools/tool_implementations/utils.py:truncate_output`, each capped at
   `CODE_INTERPRETER_MAX_OUTPUT_LENGTH`. `PythonTool` streams the raw chunks to
   the UI and truncates only the model text.
4. `errors-are-results` **Execution errors are results, not exceptions.** Both
   `run` methods catch client errors and return the result JSON with
   `exit_code=-1` and `error` set. The model sees the failure and can fix its
   code. For `run_python`, [[tools-framework#run-errors-become-results]] is a
   second guard. Bash calls skip the runner. An exception that escapes
   `BashTool.run` reaches the handler in
   `tools/fake_tools/coding_agent.py:run_coding_agent_call`, which ends the
   whole coding-agent call with an error packet.
5. `run-python-result-json` **The `run_python` result JSON is a contract with
   two readers.** `tools/results.py:LlmPythonExecutionResult` is the model text
   and is saved as the tool call response. `chat/llm_loop.py:run_llm_loop` reads
   `generated_files` from it to add the file reminder.
   `server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`
   reads `stdout`, `stderr` and `generated_files[].file_link` from it to rebuild
   the block on reload. It takes the file ID from the last segment of
   `file_link`, as `db/chat_display.py:extract_referenced_file_descriptors` does
   with the rich response. Saved chats keep the old JSON, so a field rename or a
   new `file_link` format must keep these readers able to parse it.
6. `generated-files-need-session` **Generated files need the chat session ID.**
   `PythonTool` saves them with
   `file_store/utils.py:chat_image_gen_metadata` and the chat session ID.
   `tools/tool_constructor.py:_require_chat_session_id` raises when a caller
   builds the tool without one. The access rule is in
   [[file-store-and-user-files]].
7. `bash-tool-sentinel` **`BashTool` exists only inside the coding agent.** It
   has no `Tool` row and is not in `BUILT_IN_TOOL_MAP`.
   `tools/fake_tools/coding_agent.py:run_coding_agent_call` builds it with
   `BASH_TOOL_SENTINEL_ID = 0`, and its calls are not saved as `ToolCall` rows.
   A reloaded chat shows the coding agent's query and answer, but not its bash
   steps. Persona attachment, `Tool.enabled` and `allowed_tool_ids` act on
   `CodingAgentTool`, not on `bash`.
8. `bash-calls-sequential` **Bash calls in one coding-agent call share a file
   system and run in order.** `run_coding_agent_call` runs them one at a time on
   purpose. Do not run them in parallel.
9. `run-python-stateless` **`run_python` has no state between calls.** Each call
   is a new execution, and variables do not carry over.
   `tools/tool_implementations/python/python_tool.py:PythonTool._uploaded_file_cache`
   only stops the same input file from
   uploading twice. A generated file is not an input to a later call in the same
   turn. It becomes an input in later turns only when the answer text contains
   its file ID: `db/chat_display.py:extract_referenced_file_descriptors` then
   attaches it to the message, and the next turn loads message files as chat
   files.
10. `keep-run-python-name` **Do not rename `run_python` to `python`.** OpenAI
    rejects a function named `python` (the comment on
    `tools/tool_implementations/python/python_tool.py:PythonTool`).
11. `version-gate-new-routes` **A new service route needs a version gate.** The
    service ships on its own release line, and a deployment can run an older
    image. Mark a client method that needs a newer service with
    `@requires("x.y.z")`
    (`tools/tool_implementations/python/code_interpreter_client.py:requires`),
    and check it with `CodeInterpreterClient.supports` in `is_available`. Otherwise an older service makes the tool appear and then
    fail on every call. `execute_streaming` shows the other pattern: it falls
    back to `/v1/execute` when the service answers 404.
12. `single-settings-row` **The settings table has exactly one row.**
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

- **Staged input files stay on the service.** `PythonTool` does not delete
  them, because its upload cache reuses their IDs. The service's own file TTL
  removes them. Onyx cannot see that TTL.
- **The coding agent reaches only public repositories.**
  `tools/tool_constructor.py:_construct_tools_impl` builds `CodingAgentTool`
  without a `github_token`, so `_setup_session` downloads without credentials.
- **`CODING_AGENT_BASH_TIMEOUT_MS` has no reader.** Bash calls use
  `CODE_INTERPRETER_DEFAULT_TIMEOUT_MS`.

---

## Dependencies

- [[tools-framework]]: the `Tool` interface, construction, the runner, and the
  coding-agent loop.
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

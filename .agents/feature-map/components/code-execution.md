# Code Execution

> `run_python` sends Python code to an external Code Interpreter service.
> Code mode's `execute_code` runs
> a Python program that calls the other chat tools in local Monty sandbox
> workers, and the sandbox tools run commands, edit files and publish files
> in the user's Firecracker VM.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## User experience

- **An end user** asks for a calculation, a chart or a file conversion. The
  assistant writes Python, the user sees the code, then the output as it
  streams. Files that the code writes, such as a chart or a CSV, appear as
  downloads. Files that the user attached to the chat are available to the code.
- **With code mode on** (`CODE_MODE_ENABLED=true`), the chat model gets the
  `execute_code` and `wait_code` tools instead of the tools it can nest, when
  it has any. Deep research does not use code mode. A
  preferred Action that became a function is named as one in the reminder. One program can run
  several searches and MCP calls in parallel and print only what the answer
  needs. Each program runs in a cell. When the cell still runs after
  `yield_time_ms` (default 30 s) or calls `yield_control()`, the call returns
  the output so far and the cell keeps running. The model gets the rest with
  `wait_code`, or stops the cell with `wait_code(terminate=true)`.
- **The user sees the tool calls, not the code.** Each tool call that a
  program makes shows as its own timeline step, the same as a direct call:
  searches, MCP and custom tools, URL reads, images. The program, its output,
  cells and `wait_code` calls stay hidden. A call that is still running when
  its cell yields shows as running until it ends or the response stops it.
  While a program works between calls, the timeline header reads "Working".
  Images that a program generates show above the answer. Each program starts
  fresh; a program keeps JSON values for later programs of the chat, also in
  later messages, with `store()` and `load()`.
- **An admin** opens the Code Interpreter admin page. It shows whether the
  service is reachable and healthy, and has a switch that turns code execution
  off for the whole deployment.
- **When the admin switch is off, the service is unreachable, or the URL is
  set to an empty value**, the model cannot call `run_python`. When code fails or
  times out, the user sees the error output and the turn continues.
- **With harness sandboxes** (`SANDBOX_RUNTIME=firecracker` and
  `SANDBOX_FC_TEMPLATE`), every chat agent gives the model `exec_command`,
  `write_stdin` and file tools: `edit` and `write` for Claude models (in
  the shapes of Claude Code's Edit and Write), `apply_patch` for all other
  models. This applies except in anonymous,
  incognito and multi-model turns and in Slack and Discord bot turns (bots
  get service-account sandboxes later). Admins cannot turn them off
  per agent, and users cannot pick or force them. Commands run in the user's
  private VM, in the chat's session directory, whose files stay for later
  turns. The user sees each command and its output as it streams, and the
  files that each patch, edit or write changed, on the same patch card. While
  the model writes a `write` or `edit` call, the card names the file and
  counts the lines written so far; an `apply_patch` card names the files and
  counts them. Every
  model also gets `publish_files`, which gives files from the VM to the user
  as download cards; owners and viewers of a shared chat can download them,
  and a hard chat delete deletes them.

---

## Scope

This component owns `PythonTool`, the Code Interpreter client, the settings
table with its admin API and page, and code mode's sandbox driver, tool
stubs, program store, model-facing text, `CodeModeTool` and its result
details, and the sandbox tools (`exec_command`, `write_stdin`,
`apply_patch`, `edit`, `write`, `publish_files`). Code mode's packets and replay belong to [[streaming-protocol]], and
the shared reader of result documents belongs to [[citations]].

It does not own:
- The Code Interpreter service. It is a separate deployment with its own
  release line. This repository has only the client and a pinned image tag in
  the Docker Compose files.
- Access to generated and published files. They use the chat-session stamp
  and the `chat_artifact` row that [[file-store-and-user-files]] defines.
- The Craft sandboxes ([[craft-sandboxes]]). They are a separate system and do
  not use the Code Interpreter client. The sandbox tools call their
  `HarnessSandbox` client, which [[craft-sandboxes]] owns.

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
```

```
execute_code / wait_code (code mode; a cell per program, a store per chat)
  chat/execution.py:create_chat_agent   ChatAgent(code_mode=CODE_MODE_ENABLED); the flag is
                                        saved in ChatFeatureState.code_mode, and restoration
                                        uses the saved value, not the env flag
  code_mode_tool.py:with_code_mode      ChatAgent only: by Tool.code_mode_exposure, DIRECT
                                        tools stay direct; IMMEDIATE and DEFERRED ->
                                        CodeModeTool(inner, cells=CodeCells()) and
                                        WaitCodeTool(cells); the definitions stay fixed for
                                        every step, the final step included
  CodeModeTool.operation_names          how the preference reminder names a preferred tool
                                        that became a function (prompt.py:
                                        program_function_operation)
  chat/prompt_utils.py:callable_tools   offered tools, then each tool's inner_tools; the
                                        prompt reads both and adds CODE_MODE_GUIDANCE when
                                        execute_code is offered; in both modes
                                        SearchTool._run, not the prompt, caps queries at 3
  stubs.py:build_tool_stubs             function names `<namespace>__<name>` from
                                        Tool.code_mode_function_name (MCP: server), as
                                        methods of `class tools` (programs call
                                        `await tools.<name>(...)`);
                                        `listed_text` (no DEFERRED ones, in the description);
                                        `program_text(code)` types one program: the listed
                                        functions, the DEFERRED ones whose names the code
                                        uses, and the imported modules; tool_search()
                                        (tool_search.py, BM25) only when some are DEFERRED,
                                        scoring the name, namespace and description plus
                                        PARAMETER_WEIGHT times a separate score of the
                                        argument schema's property names and descriptions
                                        (tool_search.py:ToolIndex.search)
  CodeModeTool._run -> CodeCells.start  MAX_OPEN_CELLS per response, MAX_RUNNING_CELLS per
                                        process (else BUSY_MESSAGE); cell id = 1 + the highest
                                        id in the branch; store snapshot = store.py:store_snapshot
    CodeCell                            a driver thread runs the program inside a
                                        code_mode_cell span (status, duration, call count,
                                        tool names); the call returns at yield_time_ms, at
                                        yield_control(), or at the end
      execute_program                   sandbox.py: checkout a new Monty worker (the wait
                                        observes Stop), feed the imports of IMPORTABLE_MODULES
                                        and of the `tools` module (_tools_module),
                                        type-check tool and store/load calls against the
                                        program's stubs, feed_start
        FunctionSnapshot                `tools.<name>` call -> CodeCell._call on a thread
                                        (a bare tool name is a NameError), at most
                                        MAX_CONCURRENT_TOOL_CALLS per cell and
                                        an equal share of MAX_TOOL_CALL_THREADS per process
                                        at once (the rest queue); store()/load()/yield_control() answered at
                                        once; a sleep is a deadline in the run, no thread
        FutureSnapshot                  no call or sleep finished: keep the worker and wait on
                                        an event (a call ends, a thread frees up, the cell's
                                        cancellation, a waiting program claims this worker);
                                        on the last, dump the snapshot (within
                                        MAX_SUSPENDED_BYTES), return the worker, and
                                        load_snapshot on a new worker once its calls end,
                                        or RESUME_BATCH_SECONDS (0.1 s) after the first ends
        _watched                        while a worker computes, SIGKILLs it on the cell's
                                        cancellation, or by timer at the lifetime; the crash
                                        maps to cancelled / timed_out
        program end                     calls never awaited are not waited for: started ones
                                        in SandboxResult.unawaited_calls, cancelled by the
                                        cell; queued ones in unstarted_calls, never run
      CodeCell._run_call                inner_tool.run(ToolInvocation(CodeModeCall.id,
                                        trace_metadata: call id, cell id, index, function
                                        name), the observer's ToolContext, a CitationAllocator
                                        block when code_mode_result.cites), inside
                                        cancellation_scope(cell signal)
        stubs.py:program_value          converts the result by Tool.code_mode_result
      progress                          CodeModeCallStarted/Progress/Finished, CodeModeStdout,
                                        sent to the observer or buffered until the next one
  WaitCodeTool._run -> CodeCells.wait   the cell's one observer: output and calls since the
                                        previous observation, the final result, or
                                        terminate=true stops the cell; for a closed cell,
                                        a sentence that names where its saved results
                                        hold its end (tools/tool_implementations/code_mode/prompt.py:closed_cell_text)
  each observation                      taken under the cell lock, formatted after it:
                                        prompt.py:format_content (model text, cut once
                                        in the middle to max_output_chars, 40,000 by
                                        default, at most 160,000) and
                                        CodeModeExecutionResult (each part cut to the
                                        same budget): a CellWindow
                                        (stdout, calls, commit at the program's end,
                                        tool_call_count) with cell_id, observation and status
                                        (running while the cell runs)
  chat/agent.py:_finished_cells (Agent.on_finish) -> CodeCells.finish
                                        stop every open cell; a ToolResultAmendment with the
                                        result of each observation Stop interrupted, and one
                                        with a CellClosing for each cell whose last saved
                                        observation is running
  chat/agent.py:_prepare_step (a run's first step) -> CodeCells.reopen
                                        empty cells for the next run of the same agent (a
                                        message or results to an idle child) after finish
  chat/agent.py:_suspended_cells (Agent.on_suspend) -> CodeCells.suspend
                                        the same when the run suspends (see
                                        ToolInvocation.run_work), with reason="suspended";
                                        later calls can start cells. A cell whose program
                                        waits for input stays parked
  ChatAgent.capture_state / restore_state  CodeCells.saved / restore: a parked cell is a
                                        SavedCodeCell in ChatFeatureState.code_cells; its
                                        dump goes to the file store at handoff, under a
                                        unique ID (chat/restoration.py:persist_checkpoint_files)
  CodeModeTool / WaitCodeTool.resume_with_input -> CodeCells.resume
                                        build the saved cell with the current tools and
                                        continue the observation that waited, with the
                                        answers, in any process (sandbox.execute_program
                                        with `parked`)
  CodeModeTool / WaitCodeTool.continue_open_input -> CodeCells.continue_open
                                        a program that parked in the background, with
                                        no observation, continues there once each of its
                                        requests has an answer (CodeCell.continue_background)
  chat/renderer.py:CodeModeRenderer one child ToolRenderer per call, sub_turn_index = n;
                                        a closing record follows the card section end
```

```
exec_command / write_stdin / apply_patch | edit + write / publish_files (no tool row; Tool.id is None)
  prepare_chat_turn                     ChatTurnSetup.sandbox_tools: HARNESS_SANDBOX_ENABLED,
                                        and not for anonymous users (one VM per user), in
                                        incognito or when the request selects more than
                                        one model, and not for
                                        Slack or Discord bot turns (MessageOrigin
                                        SLACKBOT / DISCORDBOT; the chat route sets
                                        DISCORDBOT from the bot's service API key)
  chat/execution.py:create_chat_agent   builds the tools with one SandboxTurn for every
                                        agent, as it adds the skill tools; a durable resume
                                        prepares the turn again and builds them the same way.
                                        sandbox_tools_for_model(model names) owns the set and
                                        its order: EditTool and WriteTool when any of the turn
                                        LLM's names (model_identity_names) contains "claude"
                                        (model_capabilities.is_claude_model, the one rule that
                                        LLM requests and prompt caching use too), else
                                        ApplyPatchTool; never both; PublishFilesTool for every
                                        model. The reserved-token prompt
                                        (calculate_reserved_tokens) names the same set
  prompt_utils.py:build_system_prompt   the `## Sandbox` section describes the VM once
                                        (sandbox_tools.py:sandbox_guidance): one use per
                                        SandboxTool that the turn offers, in order, named
                                        as the model calls it (CodeModeTool.called_name in
                                        code mode), except tools whose USE is None
                                        (publish_files); the tool descriptions describe
                                        only the tools
  SandboxTurn.start_call                first call: the user's Sandbox row
                                        (build/db/sandbox.py:get_or_create_sandbox); before
                                        each call: HarnessSandbox.begin_turn (an error is
                                        logged, the call still runs)
  ExecCommandTool / WriteStdinTool      HarnessSandbox.exec_command / write_stdin; each
                                        ExecOutputDelta -> ToolProgress, which the tool
                                        stops at max_output_chars; the result is the exec
                                        header text (wall time, exit code or ending,
                                        session ID while it runs, character count) and the
                                        output that the harness kept (head, tail and the
                                        count between them), cut in the middle to
                                        max_output_chars (40,000 by default, at most
                                        160,000) by tool_implementations/utils.py:cut_middle
                                        with one marker (truncation_marker) that
                                        counts every omitted character; SandboxExecResult
                                        saves that cut, and its truncated flag says the
                                        cut, the byte cap or the daemon left output out.
                                        When the cut leaves output out, full_value holds
                                        all the kept output (cut_middle with no cut),
                                        truncated only for the byte cap or the daemon. A cancel of the current signal (a
                                        Stop, or the end of the calling cell) ends the wait,
                                        kills the command (SIGKILL) and raises AgentCancelled;
                                        the stopped call has no result and renders as stopped
  ApplyPatchTool (SEQUENTIAL)           sandbox/patch.py parses; paths become session-relative
                                        (harness_base.session_relative_path); one
                                        stat_files call gets the facts of every path and its
                                        directory. A path is an existing file's device
                                        and inode, or its directory's and its name
                                        (patch.ensure_unique_targets). Add, Update and Move
                                        onto a link fail ("<path> is a symbolic link to
                                        <target>; edit that path instead"); a link out of
                                        the session or with an absolute target, a link loop,
                                        or the directory itself fails; every file is read and
                                        every result computed (at most
                                        APPLY_PATCH_MAX_STAGED_BYTES of updated files held in
                                        memory; each search is linear, and the searches of one
                                        patch read at most MAX_SEEK_LINES source lines and
                                        stop at a Stop); a Stop before the
                                        first write changes nothing; then write_file (keeps
                                        an existing file's mode) and delete_file (a link
                                        goes, not its target). No lock spans runs: a patch
                                        whose context changed fails verification, and two
                                        runs that patch one file at once can lose an edit
  EditTool / WriteTool (SEQUENTIAL)     sandbox_tools._change_file: one stat_files call; the
                                        same checks, read (_read_text) and mode-keeping write
                                        (_write_file) as apply_patch, and the same size caps
                                        (patch.FILE_TOOL_MAX_INPUT_BYTES / _MAX_FILE_BYTES;
                                        an edit whose result passes the file cap fails before
                                        it is built). edit: patch.edit_text, exact text with
                                        no fuzzy passes; only line breaks may differ. Unchanged
                                        text keeps its line breaks; new text gets the file's
                                        first one, as an apply_patch update does. An empty
                                        old_string creates a file, or fills an empty one;
                                        on a file with content it fails ("Cannot create new
                                        file - file already exists."). Errors and results use
                                        Claude Code's texts. write creates or overwrites
                                        (parents created); no read-first rule, as reads are
                                        not tracked. Both save ApplyPatchResult.
                                        The file tools and publish_files share one
                                        sequence_group: their calls of one step run one at
                                        a time, so a publish sees the step's earlier edits
  PublishFilesTool (SEQUENTIAL)         at most PUBLISH_FILES_MAX_FILES (20) files a call;
                                        for each file in order: HarnessSandbox.read_file
                                        (a working-directory path, or an absolute path
                                        under ONYX_VM_FILES_ROOT; other paths are refused
                                        with a hint to copy the file into the working
                                        directory; a regular file of at most
                                        PUBLISH_FILES_MAX_BYTES, 100 MiB), then
                                        db/chat.save_chat_artifact: a CHAT_ARTIFACT file
                                        record and its chat_artifact row (the VM path,
                                        title and the SandboxTurn's chat session, the root
                                        chat's: subagents share the turn) in one commit.
                                        A failure, or a Stop during or after the copies,
                                        deletes the files that the call saved: all or none.
                                        Saves PublishedFiles (file ID, name, title, absolute
                                        path, size, MIME type); each publish is a new file,
                                        and the path is the file's identity.
                                        save_chat_turn adds the files to the response's
                                        ChatMessage.files ([[chat-persistence]])
  Agent.prepare_tool_result (ChatAgent) sandbox/spill.py:spill_large_result, in a chat whose
                                        configured tools hold a SandboxTool. A result
                                        with ToolResult.full_value always spills: the tool
                                        sets it only when its cut leaves something out.
                                        Any other result spills when it is over
                                        RESULT_MAX_CHARS or past the step's
                                        STEP_MAX_CHARS, and its preview leaves out more
                                        than SPILL_MIN_DROPPED_CHARS (PREVIEW_HEAD_CHARS +
                                        PREVIEW_TAIL_CHARS). Exempt
                                        from those two limits (_OWN_LIMITS): the cells,
                                        exec_command, write_stdin, read_file, skills_read
                                        and CITEABLE_TOOLS_NAMES. A cell's closing record
                                        sets the recorded result and its own output uncut
                                        as the full value. Where:
                                        the full value or the content, at most
                                        SPILL_MAX_BYTES (a lone surrogate becomes "?"), to
                                        /tmp/onyx/tool-results/<chat session>/<message>_<call>.txt
                                        (_amended for a release hook's amendment) with
                                        HarnessSandbox.write_file, which wakes the VM. No
                                        write starts after a Stop. The run's _result_lock
                                        covers prepare_tool_result, so the parallel calls
                                        of one step spill one after another.
                                        Lifetime: a file lasts while the VM runs, until
                                        the chat's purge (the purge rule at
                                        harness_base.py:TOOL_RESULTS_ROOT), or until
                                        eviction deletes it. Eviction runs after each
                                        write, outside its wait, on one VM lookup
                                        (delete_listed_files, LIST_MAX_ENTRIES): it
                                        deletes the oldest files of any chat, files with
                                        no modification time last, while all of them hold
                                        more than TOOL_RESULTS_MAX_BYTES, or half of it
                                        when the listing is truncated.
                                        The model and the saved row get the tool's content
                                        with a <persisted-output> note (path, size, how to
                                        read it, and that a missing file means a restart
                                        or eviction), or a preview in that note. open_url's
                                        pages go one JSON object to a line, and the note
                                        lists each page's citation number. The card
                                        shows the head and tail with
                                        renderer.SPILLED_OUTPUT_NOTE
                                        (CustomToolCallSummary.spilled,
                                        CodeModeExecutionResult.spilled,
                                        SandboxExecResult.spilled), live and on
                                        replay. A failed write or a write past
                                        SPILL_WRITE_TIMEOUT_SECONDS gives the bounded view
                                        with SPILL_FAILED_NOTE; a Stop ends the wait with
                                        AgentCancelled. Calls inside a program skip the
                                        hook; the program gets the full value
                                        (stubs.py:program_value)
  Agent.on_drained (root ChatAgent)     SandboxTurn.end: create_chat_agent passes it to the
                                        root chat agent only (bind_run_store: also to a
                                        restored root), not to subagents or deep research
                                        (which gets no sandbox tools). end_turn after each
                                        finish or suspension of the root run, once its work
                                        (tool threads, program calls, foreground children)
                                        drains. A background child that outlives the root
                                        lets its renewed mark expire (TURN_LEASE_SECONDS). A
                                        suspension with a waiting or working foreground
                                        child, and a handoff in that state, end no turn; the
                                        run's later end or the lease does
```

**Availability.** `PythonTool.is_available` needs three things: a non-empty
`CODE_INTERPRETER_BASE_URL`, `CodeInterpreterServer.server_enabled`, and a
healthy service. The process caches the health result for 30 seconds per base
URL in the process (`_HEALTH_CACHE_TTL_SECONDS`). The admin health endpoint
makes a live check, and every live check refreshes that cache.

**Input files.** `PythonTool` reads the turn's chat files from
`ToolContext.chat_files`. Before the turn,
`chat/files.py:load_context_user_files_for_tools` adds project and agent files
as lazy chat files, but only the types in
`OnyxMimeTypes.CODE_INTERPRETER_STAGED_MIME_TYPES` (CSV, Excel, Word,
PowerPoint) and code files by extension
(`server/query_and_chat/chat_utils.py:is_code_interpreter_staged_file`,
`OnyxFileExtensions.SANDBOX_ONLY_EXTENSIONS`). Other project and agent files reach the model only as prompt
text or through search. `chat/agent.py:ChatAgent._finalize_tool` attaches the
raw source files of search hits to `ChatSearchResult.staged_files`
(`chat/files.py:build_python_chat_files_from_search_docs`, connector-origin
files only), only when the chat offers the Python tool. Files already in
`ChatAgent.chat_files` from an earlier step are not loaded again. Search documents
and citations are retained without Python. `chat/agent.py:ChatAgent._update_tool_context` merges them into
`chat_files` after the step and skips a filename already present, so the code in
a later step can open a spreadsheet that search found. A code mode cell stages
the files of its nested searches the same way
(`tools/tool_implementations/code_mode/cells.py:CodeCell._run_call`), so a later
`run_python` call in the same program can open them. Staging has caps on file
count, total bytes and parallel uploads. When files are dropped, the model gets
a `staging_notice` in the result.

**Busy service.** Python execution requests go through
`CodeInterpreterClient._send_with_admission_retry`. It retries HTTP 429 and 503,
follows `Retry-After`, and stays inside the call's time budget. Then it raises
`CodeInterpreterBusyError`. The client sends file and health requests once.

---

## Contracts and traps

1. `isolation-is-service-job` **The Code Interpreter service isolates Python execution.**
   Onyx trusts the service at `CODE_INTERPRETER_BASE_URL`. Changing this URL changes where user code runs.
   Code mode runs programs in its own sandbox ([[#code-mode-sandbox-is-language-level]]).
2. `default-url-not-empty` **The default URL is not empty.**
   `CODE_INTERPRETER_BASE_URL` defaults to `http://localhost:8000` in
   `configs/app_configs.py`. Only an explicit empty value turns the tool off
   without a network call. An unset value makes every turn depend on the health
   check, which fails when nothing listens.
3. `truncate-before-model` **Truncate output before it reaches the model.**
   `run_python` passes stdout and stderr through
   `tools/tool_implementations/utils.py:truncate_output`, each capped at
   `CODE_INTERPRETER_MAX_OUTPUT_LENGTH`. Only the live `PythonExecutionDelta`
   stream is complete. The saved `details` hold the truncated output, so a
   reloaded chat shows truncated output. When live output was streamed,
   `chat/renderer.py:ToolRenderer.update` sends the final result with empty
   stdout and stderr and only the new file IDs, so the client must keep the
   deltas it already has.
4. `errors-are-results` **Execution errors are results, not exceptions.**
   `PythonTool._run` catches client errors and returns result JSON with
   `exit_code=-1` and `error` set. The model sees the failure and can fix its
   code. `Tool.run` also handles exceptions ([[tools-framework#run-errors-become-results]]).
5. `run-python-result-json` **`LlmPythonExecutionResult` is saved in two
   forms.** `tools/models.py:LlmPythonExecutionResult` is the model text, as
   JSON in `content`, and the typed `details` that chat saves in
   `ToolCall.result` and in checkpoints. Checkpoints store `details` under a
   tag in `chat/checkpoint.py:CHECKPOINT_PAYLOAD_TYPES` that comes from the
   `type` literal (`result.python_execution.v1`). Register a new details type in
   `db/models.py:SavedToolResultDetails`, or saving and checkpoint restore fail.
   `server/query_and_chat/session_loading.py:translate_assistant_message_to_packets`
   parses the JSON for messages saved before response items existed. Both
   readers, and `db/chat_response.py:_extract_referenced_file_descriptors`,
   take the file ID from the last segment of `file_link`. Saved rows keep old
   data, so a field rename or a new `file_link` format must keep every reader
   able to parse it.
6. `generated-files-need-session` **Generated files need the chat session ID.**
   `PythonTool` saves them with
   `file_store/utils.py:save_chat_output_file` and the chat session ID.
   `tools/tool_constructor.py:_require_chat_session_id` raises when a caller
   builds the tool without one. The access rule is in
   [[file-store-and-user-files]].
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
13. `code-mode-sandbox-is-language-level` **The code mode sandbox is Monty,
    not a container.** `pydantic-monty` runs programs in its own worker
    processes (`tools/tool_implementations/code_mode/sandbox.py:sandbox_pool`,
    `MAX_SANDBOX_PROCESSES` per server process), which run as the API server's
    user. Programs have no access to the environment, files, network or
    processes, so the tool functions are the only way out. Each value that the
    host copies or saves from a program goes through
    `tools/tool_implementations/code_mode/store.py:json_value`. It copies the
    value as JSON within a byte and depth limit. A value over a limit raises
    inside the program for `store()` and tool arguments. For the value of the
    last expression the program has ended, so the error becomes the program's
    error. Sandbox values can share references (`x = [x, x]`), so an
    unbounded host walk would use host memory outside the sandbox limits.
    `tools/tool_implementations/code_mode/models.py:SandboxLimits` bounds each
    cell: lifetime (`lifetime_seconds`, 900 s of wall
    clock, tool calls included), compute time, memory, tool calls
    (`max_tool_calls`, 100 per cell) and output. Compute time excludes time
    spent in tools, so the lifetime is the outer bound. The lifetime and the
    reported duration start at the first worker checkout, so queueing does not
    count. At most `MAX_CONCURRENT_TOOL_CALLS` (16) nested calls of a cell run
    at once; later calls queue without a thread, and queued calls never start
    after the program ends. A server process runs at most
    `MAX_TOOL_CALL_THREADS` (192) nested calls at once
    (`tools/tool_implementations/code_mode/sandbox.py`). While several programs
    want threads, each takes at most an equal share
    (`_ToolCallThreads`). A queued call waits for a free thread instead of
    failing, and a call that ignores cancellation keeps its thread until it
    returns. The `onyx_code_mode_tool_call_threads_held_after_end` gauge counts
    these threads, and a call that returns `LATE_CALL_WARNING_SECONDS` after
    its program ended logs a warning. An MCP call stops when its cell stops
    (`server/features/mcp/client.py:call_mcp_tool` with the invocation's
    cancellation), and each MCP request times out after
    `MCP_TOOL_CALL_TIMEOUT_SECONDS`. A response has at most `MAX_OPEN_CELLS` (4)
    open cells (`tools/tool_implementations/code_mode/cells.py`). An idle cell
    costs its driver thread, and also a worker while its program waits on a
    tool and its dump does not fit in `MAX_SUSPENDED_BYTES`. A server process runs at most
    `MAX_RUNNING_CELLS` (64) cells whose program has not ended
    (`tools/tool_implementations/code_mode/cells.py:_RunningCells`); a new cell over this limit, or
    while a continuing program waits for a slot, gets `BUSY_MESSAGE` and does not start. A new program that finds no free worker for
    `CHECKOUT_TIMEOUT_SECONDS` gets `BUSY_MESSAGE`; a resumed program waits for
    a worker up to its lifetime. A program that waits (an `await` on
    unfinished tool calls or sleeps, or a synchronous `time.sleep`) keeps its
    worker while no other program waits for one. Each program that waits for
    a worker claims one such holder (`tools/tool_implementations/code_mode/sandbox.py:_WorkerDemand`). It waits at
    once when the process has checked out all `MAX_SANDBOX_PROCESSES` workers,
    and claims again each time its checkout times out. Before a claimed holder
    returns its worker, the claim becomes a credit of that waiter, so no other
    checkout can use it up; the waiter's next checkout timeout uses the credit
    up. A waiter that stops waiting passes its claim to a waiter that has
    none, or withdraws it from a holder that has not given up yet. The claimed holder's
    `tools/tool_implementations/code_mode/sandbox.py:execute_program`
    dumps the waiting program and returns the worker. A dumped program resumes
    on a new worker once all of its pending calls end, or `RESUME_BATCH_SECONDS`
    (0.1 s) after the first of them ends, with every result so far; a program
    that kept its worker resumes on each call. Dumps held by the process are bounded by
    `MAX_SUSPENDED_BYTES` (256 MB); a program whose dump does not fit keeps its
    worker, and skips later dumps while the free budget is below its last dump
    size. A dump needs about the heap plus twice the dump size inside the
    worker, so before a dump `tools/tool_implementations/code_mode/sandbox.py:_suspend`
    reads how much the worker's resident memory grew since checkout; above
    `MAX_DUMP_MEMORY_SHARE` (a quarter) of `SandboxLimits.max_memory_bytes`
    the program keeps its worker too
    (`onyx_code_mode_suspensions_total{outcome="over_memory"}`). A dump that
    still runs out of memory ends the program with `DUMP_MEMORY_MESSAGE` and
    counts a lost worker (`reason="out_of_memory"`). A program that runs out
    of its memory limit fails with its `MemoryError` and `PROGRAM_MEMORY_HINT`,
    which tells it to keep less or to save large results to files. The compute
    limit carries across these segments. While a worker computes, the cell's
    cancellation kills it at once, and a timer kills it at the end of its
    lifetime when that falls within the segment; the pool replaces it. Waits
    wake on events (a call ends, a thread frees up, cancellation), not by
    polling; only the pool checkout retries in 0.25 s steps.
    So `MAX_SANDBOX_PROCESSES` (8 per server process) bounds CPU, not users:
    8 workers serve dozens of concurrent users (a benchmark with 64 concurrent
    users added about 0.05 s at p50). Each program may use 128 MB
    (`SandboxLimits.max_memory_bytes`), and suspended program dumps may hold
    `MAX_SUSPENDED_BYTES` (256 MB) more, so worst-case sandbox memory stays
    near 1.3 GB, within the default 3 Gi API server pod. All tenants share the
    pool; counters with a `tenant_id` label (programs, cell and worker
    seconds, busy rejections; `server/metrics/code_mode.py`) attribute its use,
    and no limit applies per tenant. Users and tenants do not trust each other,
    so a worker serves one session (`MAX_CHECKOUTS_PER_WORKER` = 1) and the
    pool then replaces it; a resumed program also gets a new worker. The pool
    runs the `monty` binary in the server environment's scripts directory
    (`sysconfig`), never one that `MONTY_BIN` or `PATH` names, and does not
    start without it. Every program starts with `IMPORTABLE_MODULES` imported:
    a feed without a type check runs the imports before the program, and the
    type checker reads the same names from the program's stubs, so tracebacks
    keep the program's line numbers.
14. `code-mode-nested-calls-are-real-calls` **Nested calls go through
    `Tool.run`.** Persona gates, per-user auth, tracing spans and incognito
    checks apply as for direct calls. Each tool declares how code mode offers
    it (`Tool.code_mode_exposure`, abstract): `DIRECT` (its own tool),
    `IMMEDIATE` (a function whose stub the description lists: the built-in
    tools) or `DEFERRED` (a callable function that the description omits; the
    model finds it with `tool_search(query)`: MCP and OpenAPI tools). A tool
    that waits for a child run (`Tool.result_from_children`) must be `DIRECT`.
    `tools/tool_implementations/code_mode/code_mode_tool.py:with_code_mode`
    raises otherwise. The code mode tools are `DIRECT` too. MCP functions are
    named from `mcp__<server id>__<server>__<tool>`
    (`MCPTool.code_mode_function_name`), converted to a Python identifier
    that stays unique among the turn's functions; the description names the
    namespaces of deferred functions (an MCP tool's is its server) as tool
    groups in one fixed paragraph. Programs call
    every function through the `tools` namespace, `await tools.f(...)`: a
    module that every program imports
    (`tools/tool_implementations/code_mode/sandbox.py:TOOLS_NAMESPACE`), which
    the program's stubs declare as `class tools`, so the type checker checks
    each call. Bare names stay free for the program's own functions, and a
    model does not read the functions as tools that it can call directly.
    `store`, `load`, `yield_control` and `tool_search` stay globals; a
    function can take one of their names, and only the result types that the
    stubs declare avoid them. An explicit `import tools` or
    `from tools import f` stops the program before it runs
    (`TOOLS_IMPORT_MESSAGE`). The system prompt's tool sections name each
    tool as the model calls it (`CodeModeTool.called_name`). A
    direct call of a function name, or of its tool's name, also after
    `tools.` or `tools_`, as a tool of its own returns how to call it from a
    program
    (`Tool.inner_call_hint`, `agents/tool_execution.py`).
    `CodeModeResultSpec.usage` adds a code-mode-only
    docstring note; `internal_search` uses it to ask for all queries of one
    need in one call, since each call runs its own retrieval pipeline. Image
    generation is nested: a program gets `list[ImageResult]` (`file_id`,
    `revised_prompt`), and the user sees the images without the program
    printing them; the observation lists each image's `file_id` and revised
    prompt (`tools/tool_implementations/code_mode/prompt.py:images_note`), so
    a later message can edit it. Action preferences are advisory:
    `build_chat_prompt` asks each offered tool for `Tool.operation_names`, and
    `CodeModeTool` answers with its functions, so the reminder names a nested
    tool as a function of `execute_code` programs.
    Nested calls get the run's `before_tool_call` hook and approval gate as
    direct calls do (`ToolInvocation.nested_calls`, a `NestedCallGate`;
    `tools/tool_implementations/code_mode/cells.py:CodeCell._call`): a
    `ToolResult` decision becomes the call's result, so a denial raises in the
    program as a tool error does. The cell keeps one gate (`CodeCell._gate`):
    each of its requests belongs to the call that started it, or that rebuilt
    it in this process, also while `wait_code` observes it, so the run offers
    their answers together; `before_tool_call` sees that call's step, or for
    a cell rebuilt from a saved run, the step in which it continued. A request decision shows the request at once,
    also for a cell that runs in the background, and the call waits without a
    thread (the handler returns
    `tools/tool_implementations/code_mode/sandbox.py:AWAITS_INPUT`). Once the program
    waits only for such calls and no other call or sleep of it runs
    (`tools/tool_implementations/code_mode/sandbox.py:_Run.parkable`), it parks: the sandbox dumps it, returns its
    worker, and the cell gives back its running-cell slot (`CodeCell._park`).
    An observation that sees the park ends with `NestedInputWait`, which the
    run saves; its stdout and calls so far stay in the cell's window. A dump
    that the memory share forbids (`MAX_DUMP_MEMORY_SHARE`, about 34 MB of
    heap with the default limits) is refused, and so is a dump that does not fit
    in `MAX_SUSPENDED_BYTES`, which counts a parked dump until nothing holds the
    cell's saved program, and a program that holds a
    result it has not received: each waiting call ends its request and fails with
    `tools/tool_implementations/code_mode/cells.py:PARK_REFUSED_MESSAGE`, and the program continues. A dump that
    still runs out of memory loses the worker, so the program stops with
    `tools/tool_implementations/code_mode/sandbox.py:PARK_MEMORY_MESSAGE`. When the run
    suspends, a cell whose program is parked for input is saved with the Monty
    version that dumped it, with or without an observation; other cells close.
    The cell keeps the request of each waiting call (`SavedCodeCell.requests`).
    After the answers, the cell continues as the `CodeCells.resume` (an
    observation waited) or `CodeCells.continue_open` (no observation) row of
    the Architecture flow says: it takes a running-cell slot, waiting for one,
    and loads the dump on a new worker.
    A dump from another Monty version stops the program with
    `tools/tool_implementations/code_mode/cells.py:PROGRAM_VERSION_MESSAGE`. An approved call runs then, unless its
    tool is gone, its function name now names another tool, or its parameters
    changed (`UNAVAILABLE_CALL_MESSAGE`); a
    rejected call raises the rejection in the program. The program's lifetime
    counts the time it ran before it parked, not the wait. A run that ends
    while a cell is parked closes it; a restored run that ends before a saved
    cell resumes gives that cell's observation the same cancelled record. The
    cells never delete a dump: the checkpoint row that saved it owns it and
    deletes it when it ends or is replaced
    ([[chat-persistence#checkpoints-for-approvals]]). A hook that
    raises fails the run, as for a direct call: `NestedCallGate.decide` raises
    `agents/tools.py:BeforeToolCallFailed`, a `BaseException` that the program
    cannot catch; the cell stops its program, and the observation that reports
    the end raises it out of the tool. When no observation reports it, closing
    the cells raises `agents/models.py:ReleaseFailed` from the run's finish or
    suspend hook, and the run fails. Nested calls run in the program's
    cancellation scope: the program's end, timeout or Stop cancels their model
    work and the HTTP work of tools that observe cancellation. Python execution continues until its next output chunk (see Known issues). Calls to a sequential tool run one at a time, and the wait
    for that lock is cancellable. Each `CodeModeCall` has a `state` (`ok`,
    `error`, `unfinished`, or `running` for a call that had not ended when an
    observation returned); `is_error` derives from it and is False for
    `running`. A program that does not complete
    lists each call by state and warns that completed calls may have had
    effects, also the unfinished ones. Each tool owns what a program receives:
    `Tool.code_mode_result` (`tools/models.py:CodeModeResultSpec`) gives the
    stub return type, the conversion (`CodeModeResultKind`: a JSON object, text,
    JSON when it parses, or an MCP result unwrapped from `{"tool_result": ...}`)
    and whether the call takes a citation block. A program gets an MCP result
    as the server's `structuredContent` when it sends one, else its text
    (parsed when it is valid JSON); the model reads the text in
    direct tool calls (`tools/tool_implementations/mcp/mcp_tool.py:_tool_result_value`).
    `CustomToolCallSummary.structured_result` carries the server's structured
    content live, and is not saved or streamed. A server-reported tool failure
    (`isError`) is an error result. `CodeModeResultSpec.output_schema` carries the tool's
    stored `outputSchema` (`Tool.mcp_output_schema`, saved when the server's
    tools sync). The stub declares it as a TypedDict when its top level is an
    object whose property names are Python names that NFKC does not change;
    otherwise the stub annotates the result from the schema
    (`tools/tool_implementations/code_mode/stubs.py:_schema_result_type`). When the content is a model's
    JSON, the spec names the model (`CodeModeResultSpec.model`) and
    `tools/tool_implementations/code_mode/stubs.py:model_declarations` renders its TypedDicts from the model's fields,
    so the stub follows the model (`LlmPythonExecutionResult`, `ImageResult`). The search tools share
    `tools/tool_implementations/utils.py:SEARCH_RESULTS_CODE_MODE_RESULT`: the
    stub declares the `SearchResult` and `SearchResults` TypedDicts from their
    source, and the result formatter builds those types; `tools/tool_implementations/code_mode/stubs.py` imports no other tool
    implementation. An error result raises
    `RuntimeError` with the error text. Each `CodeModeCall` keeps its tool call id
    (`<execute_code call id>:<index>`, the same in traces, saved history and the
    UI), the tool row id (for reconnect cards) and a bounded copy of the text
    (`MAX_SAVED_CALL_CHARS`, `MAX_SAVED_EXECUTION_CHARS`). `chat/tool_results.py`
    owns two fields with phases: `metadata` (search planning) is set while the
    turn runs and cleared on save, and `displayed_document_ids` is set on save
    and used on restore to rebuild `details.displayed_docs`.
    `chat/tool_results.py:tool_result_parts` expands a result into its nested
    calls, so `ChatAgent` folds their search context, stages their files
    (`ChatCodeModeResult`, only when the Python tool is offered) and reads their
    artifacts as for direct calls.
15. `code-mode-citation-blocks` **Only citing calls take citation numbers.**
    `CitationAllocator` gives each in-flight search, web search or open URL
    call its own block of `CITATIONS_PER_TOOL_CALL` numbers, and compacts once
    no call is in flight. `chat/tool_results.py:tool_result_sources` derives a
    code mode result's documents and citations from its calls' search details,
    in every window; [[citations]] reads them through that accessor.
16. `code-mode-store` **Only `store()` values outlive a program, and the
    conversation holds them.** Each `execute_code` call runs in a fresh
    interpreter, so variables, functions and imports do not carry over. A
    program keeps JSON values with `store(key, value)` and reads them with
    `load(key)` (None when missing); both are plain functions, declared in
    `tools/tool_implementations/code_mode/store.py:STORE_STUBS` and reserved as
    tool function names. Storing None deletes the key. Writes are buffered in
    `tools/tool_implementations/code_mode/store.py:ProgramStore`. They commit
    when the program ends by itself: it completes, or stops at an uncaught
    exception (`SandboxResult.commits_store`). A program that is stopped, times
    out or fails the type check commits nothing. A commit holds only the keys
    whose value differs from the store at commit time, so a write that undoes
    another cell's later change still commits. The commit
    (`tools/tool_implementations/code_mode/models.py:StoreCommit`) gets the next
    ordinal of the branch at that moment, so commits follow completion order,
    not the order of the calls. It also names the commit it was made against
    (`StoreCommit.follows`), and the fold applies a commit only after that one.
    A commit stays in memory until a saved result reports it, and a later
    commit can be saved first, for example by the save when a child response
    starts. After a server stop the restored store is still a prefix of the
    commit order: it drops the later commit too, and a dropped commit does not
    count toward `MAX_COMMITTED_BYTES`. The fold lists dropped commits in
    `StoreSnapshot.dropped`, and the first program that starts after the drop
    names their keys in its first observation
    (`CodeModeExecutionResult.lost_store_writes`); a cell rejected with
    `BUSY_MESSAGE` leaves the note to the next one. The report keeps one
    ordinal, the highest dropped one, and covers every dropped commit up to
    it; the fold then leaves out those commits, so the note shows once. No cell
    waits for another cell's
    commit. A cell whose closing record was saved before its program ended
    (the response ended or the run paused after `STOP_GRACE_SECONDS`) commits
    nothing, since no saved record would hold the commit. It is saved on the window that reports the
    completion (`CellWindow.commit`): the observation's, or its `CellClosing`
    when the cell completed after its last observation. The store has no table
    or cache: `tools/tool_implementations/code_mode/store.py:store_snapshot`
    folds the commits in `ToolInvocation.recorded_results`, plus this
    response's commits not yet recorded, in ordinal order, key by key. So it
    follows chat branches and checkpoint restore and survives restarts and
    compaction. Do not read
    `ToolInvocation.messages` for this: compaction hides old results from it.
    `agents/tool_execution.py:ToolBatch._recorded_before` adds this step's
    message and its completed results. A cell takes its store snapshot when it
    starts. Prior turns reach the messages
    through `chat/chat_utils.py:capture_chat_history` (`read_response_steps`
    keeps `details`). Limits (`MAX_STORED_VALUE_BYTES` 256 KB per value,
    `MAX_STORE_BYTES` 1 MB in total, `MAX_COMMITTED_BYTES` 16 MB of commits per
    chat, as JSON) raise in the program when `store()` would exceed them, so
    saved writes stay bounded; the saved-call bounds do not cut them. The
    chat-limit check counts stored values only, not deleted keys, in
    `store()`, in the commit and in the saved total
    (`tools/tool_implementations/code_mode/models.py:StoreCommit.size_bytes`).
    A commit that would exceed `MAX_STORE_BYTES` or `MAX_COMMITTED_BYTES` with the commits
    that other cells made meanwhile is discarded instead
    (`tools/tool_implementations/code_mode/cells.py:_StoreCommits.commit`), and
    the observation or closing record that reports the end lists the discarded
    keys. Inside one
    program, a released wait keeps all program state: sandbox-defined classes
    and instances survive a resume on another worker. Host `ClassInstance`
    values would not, and code mode passes none.
17. `single-settings-row` **The settings table has exactly one row.**
    `db/code_interpreter.py:fetch_code_interpreter_server` uses `.one()`. A
    migration seeds the row with `server_enabled=true`. Without the row,
    `is_available` raises and the model cannot call `run_python`.
18. `code-mode-interrupted-run` **A stopped or interrupted program keeps its
    calls and never runs twice.** On Stop, the observation that is attached to
    the cell returns no result (`AgentCancelled`) and stays attached. At the
    run's end, `CodeCells.finish` saves it: its window as the call's result
    (status `cancelled`, each call with its state), through the run's finish
    hook. A cancelled cell commits no store writes. A restored run that finds
    a call started by a lost owner saves the tool's `Tool.interrupted_result`
    instead of running it again; the result ends the call through
    `agents/runtime.py:Run.finish_tool`, as a completed call does.
    The call's status is `error`. `CodeModeTool` sets it to
    `tools/tool_implementations/code_mode/code_mode_tool.py:INTERRUPTED_PROGRAM_RESULT`
    (an error without details). `WaitCodeTool` sets it to
    `tools/tool_implementations/code_mode/code_mode_tool.py:INTERRUPTED_WAIT_RESULT`,
    an error without details: the cell's last saved observation stays
    `running`. At the end of every run, `Agent.on_finish`
    (`chat/agent.py:_finished_cells`) calls `CodeCells.finish`. It stops each
    open cell (`terminated`, or `cancelled` when Stop stopped it first), waits
    up to `STOP_GRACE_SECONDS` from the first stop request, and returns a
    `ToolResultAmendment` for each observation that Stop interrupted and for
    each cell whose last saved observation is `running`. The amendment adds a `CellClosing` (`reason="response_ended"`)
    with the calls, output, result and store commit after that observation;
    its text is formatted like an observation (`format_content`). When the
    run suspends (see `ToolInvocation.run_work`), `Agent.on_suspend`
    (`chat/agent.py:_suspended_cells`) calls `CodeCells.suspend`, which does
    the same with `reason="suspended"` before the run captures its state. A
    cell that ended keeps its end in that closing record; a later `wait_code`
    of the cell says so (`tools/tool_implementations/code_mode/prompt.py:closed_cell_text`). A cell whose program
    waits for input, with or without an observation, is saved instead
    (`CodeCells.saved`); its requests stay open. For a
    restored run, `tools/tool_implementations/code_mode/cells.py:_interrupted_amendments` closes such observations
    with `reason="interrupted"` and status `cancelled`, since what the cell did
    after them is not known; a cell that stays saved gets none. A cell that a
    restored run rebuilds takes its last running observation from the
    recorded results, so it gets its closing record as a live cell does, also
    when it ends in the background with no `wait_code`. The run applies the amendments before it saves
    and publishes `ToolResultAmendedEvent` for each, before `AgentEndEvent`.
    Their calls, also the unfinished ones, may have had effects. The final
    `code_mode_delta` has `status="cancelled"` live and on replay. A tool whose
    rerun can repeat effects must set `interrupted_result`.
19. `sandbox-program-value` **A sandbox call gives a program other data
    than the model.** `exec_command` and `write_stdin` use
    `CodeModeResultKind.DETAILS`:
    `tools/tool_implementations/code_mode/stubs.py:program_value` returns the result
    details as the spec's model declares them (`ExecCommandOutput`, a base of
    the saved `SandboxExecResult`, so `type` and `truncated` stay out), while
    the model reads the exec header text. A tool whose program value is not its
    content uses this kind; do not special-case a tool name. All sandbox
    tools set `interrupted_result`, and a patch that fails verification writes
    nothing; a sandbox error during the writes can leave some files changed,
    and the error names them and the file that failed. `edit` and `write`
    change one file, after all checks pass.

---

## Decisions

- **Code mode uses Monty in process, not the Code Interpreter service.** A
  nested tool call must call back into Onyx (search, MCP credentials,
  citations). The Code Interpreter service has no callback channel, and a
  container per call costs 100 ms or more. Monty starts a program in under a
  millisecond on a warm worker, or about 15 to 30 ms when programs that start
  together wait for a new worker process, and suspends at each tool call.
  Codex uses a V8 isolate for the same reason; Python matches the rest of
  Onyx and the model's tool stubs.
- **A code mode program can outlive its step, as a Codex cell does.** A
  program that waits on slow tools or sleeps would otherwise hold the model
  step until it ends. `execute_code` returns at `yield_time_ms` and the cell
  keeps running; the model works on and gets the rest with `wait_code`. A cell
  never outlives its response: `CodeCells.finish` stops it, and a closing
  record saves what it did after its last observation, so the saved history
  and the next turn see its side effects. Its driver and tool call threads join
  the run's work (`ToolInvocation.run_work`); the tool phase waits for the
  driver, and the run drains only after a call that outlived the program
  returns.
- **Code mode keeps values with `store()`, not interpreter state.** The
  model chooses what persists, so the saved data stays small and JSON. Workers
  stay stateless, so any worker in any process can run the next program. The
  store lives in saved tool results, so it follows edits and regenerations
  and needs no memory in the API server. Codex code mode makes the same
  choice; its store lives in process memory, this one in the conversation.

---

## Known issues

- **Uploaded input files stay on the service.** `PythonTool` does not delete
  staged files, because its upload cache reuses their IDs.
  The service removes these files when their TTL expires.
  Onyx cannot see that TTL.
- **Code mode limits.** Monty's `asyncio.gather` takes no keyword arguments,
  so the tool description teaches a `try`/`except` wrapper instead of
  `return_exceptions=True`. Parallel `internal_search` calls in one program
  each run query expansion; direct calls are merged first. A checkout waits up
  to `CHECKOUT_TIMEOUT_SECONDS` (15 s) in steps of `CHECKOUT_POLL_SECONDS`
  (0.25 s), so it notices Stop; a new program that cannot get a worker fails
  with `BUSY_MESSAGE`, and a resumed one waits up to its lifetime. Each
  checkout gets a new worker process. The pool refills `min_processes` (1) in
  the background, so one checkout at a time takes under 1 ms, but checkouts
  that arrive together beyond that one wait for a spawn, about 15 to 30 ms.
  Dumps are skipped by the worker's memory growth since checkout. Before the
  first dump that growth includes about 20 MB of type checker memory, so with
  the default limit a program with more than about 12 MB of heap keeps its
  worker while it waits. Resident memory counts only the pages a program has
  written, so the check cannot see an allocation that the program never
  writes: `bytes(36_000_000)` grows the worker by about 2 MB, and its dump
  runs out of memory, which loses the worker and fails the program with
  `DUMP_MEMORY_MESSAGE`. Monty reports no heap size, so no check here closes
  this gap.
- **The code mode store can lose old writes.** A turn that does not persist
  content (incognito) saves no tool results, so its writes last only for that
  response. Responses saved without response items replay without `details`
  and contribute nothing.
- **Stop takes effect at the next Python output chunk.**
  `run_python` waits for the next chunk before it stops reading. The result is
  discarded, and generated files that `PythonTool` already saved belong to no
  `ToolCall`.

---

## Dependencies

- [[tools-framework]]: the `Tool` interface and tool construction.
- [[file-store-and-user-files]]: generated files and their session stamp.
- [[streaming-protocol]]: Python execution packets.
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
  ([[#single-settings-row]]) and that the admin health endpoint reports healthy. The agent and per-message gates are in
  [[tools-framework#investigate-tool-not-called]].

---

## Verification

- Unit tests cover Python tool availability in `backend/tests/unit/onyx/tools/` and execution in
  `backend/tests/unit/onyx/tools/tool_implementations/python/`.
- External dependency unit tests, against a running service:
  `backend/tests/external_dependency_unit/tools/`.
- Integration: `backend/tests/integration/tests/code_interpreter/`.
- Code mode: `backend/tests/unit/onyx/tools/code_mode/`,
  `backend/tests/unit/onyx/chat/test_code_mode_chat.py`,
  `backend/tests/unit/onyx/chat/test_tool_results.py` (the shared result
  readers), the MCP `isError` cases in
  `backend/tests/unit/onyx/tools/test_mcp_tool_result.py`, and
  `backend/tests/external_dependency_unit/tools/test_code_mode.py` (a mock LLM
  calls internal search from a program), and
  `backend/tests/integration/tests/llm_workflows/test_code_mode.py` (a program
  through the real server: nested search, replay, `store()` across messages).
  CI runs the chat integration directories again with `CODE_MODE_ENABLED=true`
  (`code_mode_dirs` in `.github/workflows/pr-integration-tests.yml`) and the
  `@code-mode` Playwright specs in the `code-mode` project. Mock LLM scripts
  pick the call shape with `tool_call_reply` and `requires_code_mode`
  (`backend/tests/integration/common_utils/managers/mock_llm.py`) or
  `mockLlmToolCallReply` (`web/tests/e2e/utils/mockLlm.ts`); external
  dependency unit tests take the `code_mode` fixture
  (`backend/tests/external_dependency_unit/conftest.py`) to run in both modes. Web:
  the code mode cases in
  `web/src/app/app/message/messageComponents/AgentMessage.test.tsx`,
  `web/src/lib/timeline/chat/transformers.test.ts`,
  `web/src/lib/timeline/chat/hooks/useTimelineHeader.test.tsx`
  and the code mode block of
  `web/src/lib/timeline/chat/hooks/packetProcessor.test.ts`
  (cells and closing records, live and replay order).
  Playwright: `web/tests/e2e/chat/code_mode.spec.ts` (a call that outlives a yield reads
  as one direct call, with `wait_code` or at response end) and
  `web/tests/e2e/chat/tool_history.spec.ts` (a custom tool call, direct or from
  a program, after a reload). Mobile:
  `mobile/src/chat/timeline/__tests__/grouping.test.ts` and
  `mobile/src/chat/timeline/__tests__/transformers.test.ts`.
- By hand, set `CODE_MODE_ENABLED=true`, attach an MCP server and internal
  search to an agent, and ask a question that needs both; reload the chat,
  expand the timeline, and check that each call shows once as its own step.
- By hand, ask for a chart. The image must download, and it must still show
  after a reload. Turn the admin switch off: the next message must have no
  `run_python` call and no error.

# Code Execution

> Running code on the user's behalf: `PythonTool` (`run_python`), `BashTool` (`bash`), and
> the external Code Interpreter service both talk to.

**Domain:** core-loop
**Edition:** CE
**Owns:**
`backend/onyx/tools/tool_implementations/python/python_tool.py`,
`backend/onyx/tools/tool_implementations/python/code_interpreter_client.py`,
`backend/onyx/tools/tool_implementations/bash/bash_tool.py`,
`backend/onyx/server/manage/code_interpreter/api.py`, `models.py`,
`backend/onyx/db/code_interpreter.py`,
`web/src/app/admin/code-interpreter/page.tsx`,
`web/src/views/admin/CodeInterpreterPage/`,
`web/src/hooks/useCodeInterpreter.ts`

**Read first:** `[[tools-framework]]`. It documents the `Tool` interface both tools implement
and the fact that `BashTool` is never persona-attachable. This document does not repeat that;
it covers what the two tools actually execute and where.

---

## 1. What the user experiences

When the assistant needs to compute something, it writes and runs Python. The user sees a
code block appear, then streamed stdout/stderr, then a result. If the code produced a file
(a chart, a CSV), a file count shows and the file becomes downloadable
(`web/src/app/app/message/messageComponents/timeline/renderers/code/PythonToolRenderer.tsx`).

When the user asks the coding agent to investigate a GitHub repository, the assistant clones
it into an isolated session and runs a sequence of bash commands, shown as a timeline of
"thinking" and "bash" steps, ending in a final answer
(`web/src/app/app/message/messageComponents/timeline/renderers/code/CodingAgentRenderer.tsx`).
The user never sees or triggers the bash tool directly; it only exists inside that sub-agent
loop.

An admin visits `/admin/code-interpreter` to see whether the code-execution service is
reachable and to turn it off for the whole deployment. Turning it off does not remove the
tool from personas; it makes `run_python` and `bash` vanish from every turn's tool set
without changing any persona configuration (`[[tools-framework]]` §5, contract 9).

---

## 2. Surfaces

### Admin HTTP endpoints (router prefix `/admin/code-interpreter`, `server/manage/code_interpreter/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/admin/code-interpreter/health` | `get_code_interpreter_health` | Live reachability check against the service; not cached. Gated on `Permission.FULL_ADMIN_PANEL_ACCESS`. |
| GET | `/admin/code-interpreter` | `get_code_interpreter` | Returns `{enabled: bool}` from the `CodeInterpreterServer` row. |
| PUT | `/admin/code-interpreter` | `update_code_interpreter` | Flips the `enabled` flag. |

Registered in `backend/onyx/main.py:604` alongside the other admin routers. The frontend
calls it through the Next.js proxy at `/api/admin/code-interpreter[/health]`
(`web/src/hooks/useCodeInterpreter.ts`), consistent with the project rule to go through the
frontend, not `:8080` directly.

### Environment configuration (`backend/onyx/configs/app_configs.py:1674-1706`)

| Variable | Default | Effect |
|---|---|---|
| `CODE_INTERPRETER_BASE_URL` | `http://localhost:8000` | Base URL of the external Code Interpreter service. Required for `PythonTool` and `BashTool` to exist at all. |
| `CODE_INTERPRETER_DEFAULT_TIMEOUT_MS` | 60,000 | Per-execution timeout passed to the service for both `run_python` and `bash`. |
| `CODE_INTERPRETER_MAX_OUTPUT_LENGTH` | 50,000 | Character cap applied to stdout and stderr independently before they enter the LLM-facing response (`utils.py:truncate_output`). |
| `CODE_INTERPRETER_MAX_STAGED_FILES` | 25 | Max chat files staged into one Python execution. |
| `CODE_INTERPRETER_MAX_STAGED_BYTES` | 100 MiB | Byte budget for staged files in one execution. |
| `CODE_INTERPRETER_STAGING_CONCURRENCY` | 8 | Bounded parallelism for file reads/uploads during staging. |

There is no env var for bash-specific timeouts or output caps; `BashTool` reuses
`CODE_INTERPRETER_DEFAULT_TIMEOUT_MS` and `CODE_INTERPRETER_MAX_OUTPUT_LENGTH`
(`bash_tool.py`). The coding agent additionally hardcodes its own timeouts (see §4.4).

---

## 3. Data model

- `CodeInterpreterServer` (`backend/onyx/db/models.py:7080`): a single-row table
  (`db/code_interpreter.py:fetch_code_interpreter_server` does `.one()`, so it assumes exactly
  one row exists) holding `server_enabled: bool`. This is the deployment-wide kill switch the
  admin page writes to. It is distinct from `CODE_INTERPRETER_BASE_URL`: the env var says where
  the service is, this row says whether Onyx is willing to use it.
- No table stores code-interpreter sessions or executions. Session lifetime is entirely
  server-side state on the Code Interpreter service, referenced only by a `session_id: str`
  string that Onyx holds in memory for the duration of one coding-agent call
  (`fake_tools/coding_agent.py:_setup_session`).
- Generated files from `run_python` are persisted through the ordinary file store as
  `FileOrigin.CHAT_IMAGE_GEN` records (`python_tool.py:run`, `file_store/utils.py`). See §5 and
  §9; the access-control gap on that origin is documented in `[[file-store-and-user-files]]`
  and is not re-derived here.

---

## 4. How it works

### 4.1 The service boundary

Code never runs in the API server process. Both tools are thin HTTP clients to an external
Code Interpreter service reachable at `CODE_INTERPRETER_BASE_URL`
(`code_interpreter_client.py:CodeInterpreterClient.__init__`). The client is a plain
`requests.Session` wrapper; nothing in this codebase spawns a subprocess, container, or
sandbox for code execution. Isolation is therefore **not implemented here**: it is whatever
that external service does when it accepts `POST /v1/execute`. This repository has no code
for the service itself, so the actual sandboxing mechanism (container, VM, gVisor, or
something else) is **unverifiable from this codebase**. What is verifiable from the client
contract:
- `execute_bash_in_session` docstring states "the session pod has no network access
  (enforced at session creation)" (`code_interpreter_client.py:execute_bash_in_session`),
  which names it a session **pod**, implying container/VM-level isolation, but this claim is
  asserted by the client's docstring, not enforced by any code in this repo.
- `is_available` health-checks the service and gates on `server_enabled`
  (`python_tool.py:is_available`, `bash_tool.py:is_available`), which controls whether Onyx
  will *route* to the service, not how the service isolates code once reached.

**This is the security core of the component and the honest statement is:** whatever
isolation exists is an infrastructure assumption delegated to the Code Interpreter service,
not an application-level control enforced by `PythonTool`, `BashTool`, or
`CodeInterpreterClient`. Nothing in `backend/onyx` verifies that the service actually
sandboxes execution; Onyx trusts the URL configured in `CODE_INTERPRETER_BASE_URL`.

### 4.2 `run_python`: call chain

```
LLM emits run_python(code=...)
  └─ run_tool_calls                    tools/tool_runner.py      ([[tools-framework]])
      └─ PythonTool.run                python_tool.py
          ├─ _select_files_for_staging  python_tool.py   (choose which chat files to send)
          ├─ _upload_and_stage          python_tool.py   → CodeInterpreterClient.upload_file
          ├─ CodeInterpreterClient.execute_streaming     code_interpreter_client.py
          │    POST {CODE_INTERPRETER_BASE_URL}/v1/execute/stream  (SSE; falls back to
          │    POST .../v1/execute if the stream route 404s)
          ├─ CodeInterpreterClient.download_file / delete_file     (generated files)
          └─ get_default_file_store().save_file(..., FileOrigin.CHAT_IMAGE_GEN)
```

Each streamed SSE event maps to a `StreamOutputEvent` / `StreamResultEvent` /
`StreamErrorEvent` (`code_interpreter_client.py:_SSE_EVENT_MAP`), and `PythonTool.run` emits a
`PythonToolDelta` packet per output chunk plus a final one carrying `file_ids`
(`python_tool.py:run`).

### 4.3 `bash`: call chain, and how it differs from `run_python`

`BashTool` never calls `client.execute(...)`. It calls
`client.execute_bash_in_session(session_id, cmd, timeout_ms)`
(`bash_tool.py:run`), which posts to `POST {base}/v1/sessions/{session_id}/bash`. That
route only exists on Code Interpreter servers reporting version `>= 0.4.0`
(`code_interpreter_client.py:@requires("0.4.0")` on `create_session`,
`execute_bash_in_session`, `delete_session`), which is why `BashTool.is_available` adds a
`client.supports(...)` capability check on top of the health/env/enabled checks
`PythonTool.is_available` already does (`bash_tool.py:is_available`).

`BashTool` is constructed with a `session_id` already in hand
(`bash_tool.py:__init__(self, tool_id, session_id, emitter)`); it does not create or destroy
sessions itself. Session lifecycle belongs entirely to its one caller,
`fake_tools/coding_agent.py:_setup_session`:

```
run_coding_agent_call                    fake_tools/coding_agent.py
  └─ _setup_session (context manager)    fake_tools/coding_agent.py
      ├─ download_github_archive         utils/github.py   (tarball of the target repo)
      ├─ CodeInterpreterClient.upload_file(repo.tar.gz)
      ├─ CodeInterpreterClient.create_session(ttl_seconds=3600, files=[tarball])
      ├─ execute_bash_in_session(tar -xzf ... && rm ... && ls)   (extract, on entry)
      ├─ yield session_id
      │    ├─ BashTool(tool_id=BASH_TOOL_SENTINEL_ID, session_id, emitter)
      │    └─ _run_bash_call → bash_tool.run(...) for each LLM-issued bash call
      └─ CodeInterpreterClient.delete_session (on exit, best-effort; TTL is the backstop)
```

`BASH_TOOL_SENTINEL_ID = 0` (`fake_tools/coding_agent.py`) is used because this `BashTool`
instance is never looked up by DB tool id; it is built directly, once, for the duration of one
coding-agent call. `[[tools-framework]]` covers why this makes `bash` calls invisible to the
normal `Tool`/`Persona__Tool` machinery; this document only adds that the *session* the bash
calls run in is the same session the repo was extracted into, so file-system state persists
across bash calls within one coding-agent turn (see §4.5).

### 4.4 Availability gating

`PythonTool.is_available` (`python_tool.py:is_available`):
1. `CODE_INTERPRETER_BASE_URL` must be set.
2. `fetch_code_interpreter_server(db_session).server_enabled` must be `True` (the admin
   toggle).
3. `CodeInterpreterClient().health(use_cache=True).healthy` must be `True`. Health responses
   are cached 30s per base URL (`code_interpreter_client.py:_HEALTH_CACHE_TTL_SECONDS`).

`BashTool.is_available` (`bash_tool.py:is_available`) repeats all three checks, then adds a
fourth: `client.supports(create_session, execute_bash_in_session, delete_session)`, which
compares the service's reported version against each method's `@requires` minimum
(`code_interpreter_client.py:requires`, `supports`). An older Code Interpreter deployment that
lacks the session/bash routes therefore fails this check even if `run_python` works fine
against it.

`CodingAgentTool.is_available` simply delegates to `BashTool.is_available`
(`coding_agent/coding_agent_tool.py:is_available`), so the coding-agent tool disappears under
the exact same conditions as raw bash.

All three checks (env, admin toggle, health) failing is silent: `is_available` returns
`False`, `tool_constructor.py` drops the tool from the turn's tool set with no error surfaced
to the user or the model (`[[tools-framework]]` §5 contract 2). See §9.

### 4.5 Sessions and file retention

**Python (`run_python`) has no session.** Every `PythonTool.run` call is an independent
`POST /v1/execute[/stream]`; there is no session id, no persistent interpreter state, and no
guarantee that variables from one call survive to the next call in the same turn. The only
state that persists across calls within one `PythonTool` instance is the
`_uploaded_file_cache: dict[(filename, content_hash), ci_file_id]`
(`python_tool.py:__init__`), an in-process cache that avoids re-uploading the same chat file
bytes on a later cycle. It is not a Code Interpreter session; it is purely an upload-dedup
optimization scoped to one `PythonTool` object (one turn's worth of `run_python` calls).

**Bash (inside the coding agent) has exactly one session per coding-agent call.**
`_setup_session` creates one Code Interpreter session with a 1-hour TTL
(`CODING_AGENT_SESSION_TTL_SECONDS`), and every bash call the sub-agent makes during that call
runs `execute_bash_in_session` against that same `session_id`, so the filesystem (including
the extracted repo) persists across bash calls. The coding agent's own comment says this is
intentional: bash calls are dispatched sequentially, not in parallel, because "they share the
session filesystem and ordering matters" (`fake_tools/coding_agent.py:run_coding_agent_call`).
The session is torn down when `_setup_session`'s context manager exits; if that
best-effort `delete_session` call itself fails, the pod's own TTL is the backstop.

**Generated files from `run_python` are retained, not the execution state.** A generated file
is downloaded from the Code Interpreter (`client.download_file`), saved into Onyx's own file
store under `FileOrigin.CHAT_IMAGE_GEN` (`python_tool.py:run`), and only then is the
Code-Interpreter-side copy deleted (`client.delete_file`). Once saved, the file is served
through the ordinary chat-file path and is subject to the access-control gap
`[[file-store-and-user-files]]` documents for that origin: any authenticated user who knows or
guesses the `file_id` can read it, because `user_can_access_chat_file` grants access to every
`CHAT_IMAGE_GEN` file unconditionally (`[[file-store-and-user-files]]` §5, §9). This document
does not re-derive that gap; it only surfaces that code-interpreter output files inherit it.
Input files staged for execution are *not* cleaned up server-side by `PythonTool` (the code
comment notes they are "orphaned when the session ends"; the Code Interpreter's own TTL is
relied on to reap them, `python_tool.py:run`).

---

## 5. Contracts and invariants

1. **Executed code must never reach the API server's process, network, or credentials.**
   Nothing in `backend/onyx` enforces this; it is delegated entirely to the Code Interpreter
   service reached at `CODE_INTERPRETER_BASE_URL`. If that service is misconfigured to point
   at something inside the trust boundary (for example, an internal host with no isolation),
   nothing in this component detects or prevents it. This is an infrastructure assumption, not
   an application control (see §4.1). **Unverifiable from this codebase**: the actual sandbox
   mechanism the service uses is not part of this repository.
2. **Output must be size-bounded before it enters the prompt.** Both tools truncate stdout and
   stderr independently via `utils.py:truncate_output` before building the LLM-facing JSON
   (`python_tool.py:run`, `bash_tool.py:run`), each capped at
   `CODE_INTERPRETER_MAX_OUTPUT_LENGTH`. A change that serializes raw, untruncated output
   defeats this bound.
3. **A crashed or timed-out execution must fail the tool call, not the turn.** Both `run`
   methods catch every exception from the client call and return a `ToolResponse` describing
   the failure (`error`, `timed_out`, `exit_code=-1`) rather than raising out of `run`
   (`python_tool.py:run`, `bash_tool.py:run`). `[[tools-framework]]`'s
   `_safe_run_single_tool` is a second layer of the same guarantee; do not rely on only one.
4. **Generated files must be access-checked on read.** They are not, for `CHAT_IMAGE_GEN`
   (`[[file-store-and-user-files]]` §9). Any new code path that serves a code-interpreter
   generated file must not assume the origin check exists; check the caller's access
   explicitly if this component is extended.
5. **`BashTool` is never constructed through `tool_constructor.py`.** It cannot be reached by
   `allowed_tool_ids`, persona attachment, or `Tool.enabled`. Its only entry point is
   `fake_tools/coding_agent.py`. See `[[tools-framework]]` for the full consequence.
6. **`is_available` must not raise and must stay cheap**, per `[[tools-framework]]` contract 2.
   `PythonTool`/`BashTool`'s implementations call `health(use_cache=True)`, so a slow or down
   Code Interpreter is masked by the 30s cache rather than blocking every turn's tool
   construction on a live network call every time.
7. **The `run_python` LLM-facing function name must stay `run_python`, never `python`.** OpenAI
   rejects a tool definition named `python` outright (`python_tool.py:NAME` comment, dated
   2026-07-21). This is an external provider constraint, not an internal choice.

---

## 6. Relationships

**Depends on**
- `[[tools-framework]]`: the `Tool` interface both classes implement; the persona-attachment
  and per-message toggle machinery `run_python` participates in and `bash` bypasses.
- `[[streaming-protocol]]`: `PythonToolStart`/`PythonToolDelta`/`BashToolStart`/`BashToolDelta`
  are packet types in the shared vocabulary (`streaming_models.py`).
- `[[file-store-and-user-files]]`: where `run_python` generated files are saved
  (`FileOrigin.CHAT_IMAGE_GEN`) and the access gap that origin carries.
- `[[core-chat-loop]]`: runs the LLM cycle that calls `run_python`; the coding agent runs its
  own inner loop (`fake_tools/coding_agent.py`) that reuses `llm_step.py:run_llm_step_pkt_generator`
  directly rather than going through `run_llm_loop`.
- `[[access-control]]`: gates `/admin/code-interpreter` on `Permission.FULL_ADMIN_PANEL_ACCESS`;
  does **not** gate reads of generated files (see §5, §9).

**Depended on by**
- `[[chat-frontend]]`: `PythonToolRenderer.tsx` and `CodingAgentRenderer.tsx` render these
  packet streams.
- `[[craft-sandboxes]]`: **unverified**. This document found no code path connecting the
  Craft coding-agent sandbox infrastructure to `CodeInterpreterClient` or
  `CODE_INTERPRETER_BASE_URL`; if such a link exists it was not found under
  `backend/onyx/tools` or `backend/onyx/coding_agent`. Do not assume the two share
  infrastructure without checking `[[craft-sandboxes]]` directly.
- `[[chat-persistence]]`: `ToolCall` rows are written for `run_python` like any other tool; not
  for `bash`, per `[[tools-framework]]`.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| changes the `CodeInterpreterClient` HTTP contract (request/response shape, routes) | both `python_tool.py` and `bash_tool.py` (they share the client), the `@requires` version gates, and `is_available` for both tools |
| changes isolation assumptions (e.g. what `CODE_INTERPRETER_BASE_URL` is allowed to point at) | this is a security-relevant change with no code-level enforcement today; document the new assumption explicitly since nothing here will catch a regression |
| adds a new executable tool (a third code-execution surface) | `BUILT_IN_TOOL_MAP` and the seeding migration pattern (`[[tools-framework]]` §8), whether it needs a session like `bash` or is stateless like `run_python`, and whether its output needs the same truncation and generated-file handling |
| changes output handling (truncation, generated-file save path) | `CODE_INTERPRETER_MAX_OUTPUT_LENGTH`, `FileOrigin.CHAT_IMAGE_GEN` and its access gap in `[[file-store-and-user-files]]`, and the frontend renderers that assume `stdout`/`stderr`/`file_ids` shapes |
| changes `/admin/code-interpreter` semantics | `useCodeInterpreter.ts`'s polling and status derivation, and both `is_available` implementations that read `CodeInterpreterServer.server_enabled` |
| changes the coding-agent session lifecycle | `_setup_session`'s TTL and cleanup, and whether bash calls must stay sequential (filesystem sharing) |

---

## 8. How to verify a change

### Tests

```bash
# Unit: availability gating, streaming client parsing, upload cache, bash tool
cd backend && uv run pytest tests/unit/onyx/tools/test_python_tool_availability.py
cd backend && uv run pytest tests/unit/onyx/tools/tool_implementations/python/test_code_interpreter_client.py
cd backend && uv run pytest tests/unit/onyx/tools/tool_implementations/python/test_python_tool_upload_cache.py
cd backend && uv run pytest tests/unit/onyx/tools/tool_implementations/bash/test_bash_tool.py
cd backend && uv run pytest tests/unit/onyx/tools/test_coding_agent_repo_setup.py

# External dependency unit: talks to a real/near-real Code Interpreter service
cd backend && uv run pytest tests/external_dependency_unit/tools/test_python_tool.py
cd backend && uv run pytest tests/external_dependency_unit/tools/test_python_tool_server_enabled.py

# Integration: admin endpoints, permission checks
cd backend && uv run pytest tests/integration/tests/code_interpreter/test_code_interpreter_api.py
```

See `backend/AGENTS.md` for authoritative commands and required env.

### Manual reproduction

1. Confirm `CODE_INTERPRETER_BASE_URL` points at a running Code Interpreter service, and that
   `backend/log/api_server_debug.log` shows no connection errors on startup.
2. Open `http://localhost:3000/admin/code-interpreter`, sign in as
   `admin_user@example.com` / `TestPassword123!`. Confirm the health status renders
   `healthy` (via `useCodeInterpreter.ts` polling `/api/admin/code-interpreter/health` every
   30s) and the enable/disable toggle round-trips (`PUT /admin/code-interpreter`).
3. In a chat, ask the assistant to run Python (for example "compute the 20th Fibonacci
   number"). Confirm a code block, output, and completion render
   (`PythonToolRenderer.tsx`), and that the turn's `ToolCall` row persists
   (`[[chat-persistence]]`).
4. Toggle `enabled: false` from the admin page, start a new turn, and confirm `run_python` no
   longer appears among the tools the model can call, with no error shown to the user.
5. Trigger the coding agent against a small public repo and confirm the timeline shows
   alternating thinking/bash steps followed by a final answer
   (`CodingAgentRenderer.tsx`).

### What "working" looks like

- `run_python` and `bash` both disappear cleanly (no error, no dead tool call) when
  `CODE_INTERPRETER_BASE_URL` is unset, the admin toggle is off, or the service is unhealthy.
- Output longer than `CODE_INTERPRETER_MAX_OUTPUT_LENGTH` is truncated with the standard
  footer, never sent raw to the LLM.
- A bash command that times out or a Python execution that crashes produces a completed tool
  call with an error field, never a dead stream or an unhandled exception.

---

## 9. Footguns

- **Both tools vanish silently when unconfigured.** No error is shown to the user or logged
  at `warning` or above when `CODE_INTERPRETER_BASE_URL` is unset; `is_available` just returns
  `False` and the tool is absent from the turn (`[[tools-framework]]` §5 contract 2). Do not
  assume a missing tool call means the model chose not to use it.
- **The bash/python asymmetry is easy to miss.** `run_python` is a normal persona-attachable
  `Tool` with a DB row and `ToolCall` persistence. `bash` is constructed directly by
  `fake_tools/coding_agent.py` with a sentinel id, is never in `BUILT_IN_TOOL_MAP`'s
  persona-attach path, and its calls are not written as `ToolCall` rows. Code that assumes
  every built-in tool behaves like `run_python` will mishandle `bash`.
- **Generated files inherit the `CHAT_IMAGE_GEN` access gap.** A file produced by `run_python`
  is readable by any authenticated user who obtains its `file_id`, not just the user whose
  turn produced it (`[[file-store-and-user-files]]` §9). This is not specific to code
  execution, but code execution is a path that produces such files.
- **Isolation is asserted in a docstring, not enforced in code.** The "no network access" claim
  for bash sessions (`code_interpreter_client.py:execute_bash_in_session`) is a statement about
  the external service's behavior. Nothing in this repository can verify or test that claim
  end to end; treat it as an infrastructure assumption when reasoning about blast radius.
- **`PythonTool` has no execution session; only an upload cache.** Do not assume variables or
  files created in one `run_python` call are visible in the next call within the same turn
  unless they were written to a file the model re-reads. This differs from the coding agent's
  bash session, which does share filesystem state across calls.
- **Staged input files for `run_python` are not deleted by Onyx.** They rely on the Code
  Interpreter's own TTL to be reaped; a bug in that TTL logic on the service side is invisible
  from this codebase.

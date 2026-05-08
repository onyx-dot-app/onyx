# Craft V0 — Current Architecture

A snapshot of how Onyx Craft (a.k.a. "Build") is wired today, before the V1 work
in this directory lands. The goal of this doc is to give a reader the mental
model needed to read the V1 plans (`search.md`, `interception.md`,
`sandbox-backends.md`, `skills.md`, etc.) without having to spelunk the code
themselves.

The product surface is `/craft/v1`; the backend module is still called
`build/`. That naming split is intentional and stays for V1 (see the main plan).

## Concepts

Quick glossary of the nouns you'll see throughout this doc and the V1 plans.
Each one maps to a specific DB table, code module, or filesystem location —
links in the deeper sections.

- **Craft** — the product. A chat-driven coding-agent surface at `/craft/v1`
  where a user (or, in V1, a scheduled trigger) prompts an agent that runs
  end-to-end inside a sandbox and produces durable artifacts.
- **Build** — historical name for Craft. Still the name of the backend
  module (`backend/onyx/server/features/build/`), the DB tables (`build_session`,
  `build_message`), and most of the code. Treat "Build" and "Craft" as synonyms
  when reading the code; the V1 plans don't rename the modules.
- **Session** (`BuildSession`, table `build_session`) — one user-initiated
  conversation. Owns its message history, artifacts, snapshots, and an
  allocated Next.js port. A user can have many sessions; each session belongs
  to exactly one user. Status: `ACTIVE` / `IDLE` / `DELETED`.
- **Sandbox** (`Sandbox`, table `sandbox`) — the isolated execution
  environment the agent runs in. **One per user** (the `user_id` column is
  unique), shared across all of that user's sessions. Today this is either a
  Kubernetes pod or a directory on the host. Status: `PROVISIONING` /
  `RUNNING` / `SLEEPING` / `TERMINATED` / `FAILED`.
- **Sandbox backend** (`SANDBOX_BACKEND` env var, `local` or `kubernetes`) —
  the implementation of `SandboxManager` doing the actual provisioning. V1
  adds a `docker` backend.
- **Session workspace** — the per-session directory inside a sandbox at
  `/workspace/sessions/<session_id>/`. Holds the agent's `outputs/`, the
  user's `attachments/`, a Python `.venv/`, the rendered `AGENTS.md`, and
  `opencode.json`. Created by `setup_session_workspace`, torn down on session
  delete.
- **Knowledge corpus** — the JSON dump of the user's connector documents,
  mounted at `/workspace/files/` (or symlinked to bundled demo data when
  `demo_data_enabled=True`). Today the agent reads it via `find`/`grep`/`cat`.
  V1's `company_search` skill replaces this with permissioned hybrid search.
- **Attachments** — files the user uploads into a session, stored under
  `/workspace/sessions/<id>/attachments/`. Distinct from the knowledge
  corpus. Capped by `MAX_UPLOAD_FILES_PER_SESSION` /
  `MAX_TOTAL_UPLOAD_SIZE_BYTES`.
- **User Library** — admin-managed persistent files (xlsx, pptx, docx, ...)
  the user has uploaded to be re-indexed via the special `User Library`
  connector. Distinct from session attachments — these survive across
  sessions and live in their own connector pipeline.
- **Outputs** — what the agent produces, under
  `/workspace/sessions/<id>/outputs/`. Sub-dirs: `web/` (Next.js scaffold),
  `slides/`, `markdown/`, `graphs/`, etc. Bytes live in the sandbox; metadata
  is mirrored as `Artifact` rows.
- **Artifact** (`Artifact`, table `artifact`) — a named file produced by the
  agent that the UI surfaces (web app, deck, doc, image, ...). The row stores
  type + relative path + name; the bytes are read on demand from the sandbox
  via `read_file` / `download_artifact`.
- **Message** (`BuildMessage`, table `build_message`) — one persisted ACP
  packet (user prompt, assistant message, assistant thought, completed tool
  call, latest plan). `message_metadata` JSONB stores the raw packet.
  Grouped by `turn_index` (Nth user prompt + everything the agent emits in
  response).
- **ACP** — the Agent Communication Protocol, JSON-RPC over a duplex pipe.
  The sandbox runs `opencode acp`; the api_server speaks ACP to it through
  `kubectl exec` (K8s) or a host pipe (local). Packet types include
  `agent_message_chunk`, `agent_thought_chunk`, `tool_call_start`,
  `tool_call_progress`, `agent_plan_update`, `prompt_response`.
- **Turn** — one user prompt and the full agent response that follows.
  `turn_index` is the 0-indexed count of user messages in the session.
  All assistant `BuildMessage` rows for one turn share the same `turn_index`.
- **OpenCode** — the upstream coding-agent runtime
  (`https://opencode.ai`) baked into the sandbox image. Owns tools (`bash`,
  `read`, `write`, `edit`, `grep`, `glob`, `list`, `lsp`, `patch`, `skill`,
  `webfetch`, `question`, `todowrite`/`todoread`) and the skills mechanism.
  `opencode.json` configures provider, model, tool permissions, and the
  `external_directory` allowlist.
- **Skill** — a directory under `.opencode/skills/<slug>/` containing a
  `SKILL.md` (frontmatter + instructions) and optional helper scripts. The
  agent invokes them by name. Today: baked into the sandbox image
  (`pptx`, `image-generation`, `bio-builder`). V1's skills system makes them
  DB-backed and admin-uploadable.
- **Snapshot** (`Snapshot`, table `snapshot`) — a tar.gz of a session's
  `outputs/` + `attachments/`, stored in the file store
  (S3 in cloud, local disk in dev). Created by the idle-cleanup Celery task
  before a pod is torn down; restored when the user re-opens the session.
  K8s only — `local` doesn't snapshot.
- **`SandboxManager`** — abstract interface in `sandbox/base.py`. Two impls:
  `LocalSandboxManager` (host directory) and `KubernetesSandboxManager`
  (pods). Owns provision/terminate, session-workspace setup/cleanup,
  snapshot create/restore, file ops, ACP message streaming, and the webapp
  proxy URL. **DB-blind by design** — the api_server and Celery layer call it.
- **`SessionManager`** (`session/manager.py`) — orchestration layer that
  ties HTTP requests to DB writes to sandbox calls. Owns session create/get/
  delete, the streaming loop that drives ACP and persists the resulting
  messages and artifacts, session naming, and follow-up suggestions.
- **Demo mode** (`BuildSession.demo_data_enabled`) — when true, the
  session's `files/` symlink points at the bundled demo dataset
  (`kubernetes/docker/demo_data/`) instead of the user's real corpus, and
  `org_info/` is populated from `persona_mapping.py`. Used for onboarding
  and unauthenticated demos. V1 removes this in favor of real data only.
- **Trigger** — V1 concept (not present today): a saved Craft prompt that
  runs on a schedule. Each scheduled run gets a brand-new session. See
  `triggers.md`.
- **Approval** — V1 concept: a gate on risky agent actions (external
  writes, deliveries, destructive ops) enforced in Onyx-controlled paths.
  See `approvals.md`.

## High-Level Shape

Craft is a chat-driven coding-agent product. A user opens `/craft/v1`, gets (or
creates) a `BuildSession`, and exchanges messages with an agent that runs inside
a sandboxed environment. The agent has access to a knowledge corpus dumped into
the sandbox at provision time, a Python venv, a Next.js scaffold for building
UIs, and a small set of OpenCode "skills." Everything the agent produces lands
in the session's `outputs/` directory and is surfaced to the user as artifacts.

```
┌─────────────── web/src/app/craft/v1 ───────────────┐
│  Next.js page                                       │
│  ├─ ChatPanel  (messages, streaming, input bar)     │
│  └─ OutputPanel (file browser, previews, web app)   │
│  Hooks: useBuildSessionController, useBuildStreaming│
│         useBuildSessionStore, useBuildLlmSelection  │
└──────────────────────┬──────────────────────────────┘
                       │  /api/build/...  (cookie auth)
                       ▼
┌──────────── backend/onyx/server/features/build ─────────┐
│  api/        — FastAPI routers                          │
│  session/    — SessionManager (lifecycle, streaming)    │
│  db/         — BuildSession, Sandbox, Artifact, etc.    │
│  sandbox/    — SandboxManager (local | kubernetes)      │
│  indexing/   — persistent_document_writer (corpus dump) │
│  s3/         — s3 client used by the K8s file-sync path │
│  AGENTS.template.md — agent instructions template       │
└──────────────────────┬──────────────────────────────────┘
                       │   kubectl exec  /  subprocess
                       ▼
┌──────── Sandbox (k8s pod or host directory) ────────┐
│  /workspace/                                         │
│  ├── files/         (knowledge corpus, JSON files)   │
│  ├── sessions/<id>/                                  │
│  │   ├── outputs/   (web/, slides/, markdown/, ...)  │
│  │   ├── attachments/                                │
│  │   ├── .venv/                                      │
│  │   ├── AGENTS.md                                   │
│  │   └── opencode.json                               │
│  └── .opencode/skills/  (pptx, image-generation,     │
│                          bio-builder)                │
└──────────────────────────────────────────────────────┘
```

## Database Models (`backend/onyx/db/models.py`)

Five tables drive Craft today, all under the `build_*` / `sandbox` / `artifact`
/ `snapshot` names. No `craft_*` table exists yet — the V1 plans add them.

- **`BuildSession`** (`build_session`) — per-user chat session: id, user_id,
  name, status (`BuildSessionStatus`: ACTIVE / IDLE / DELETED), created_at,
  last_activity_at, nextjs_port, demo_data_enabled, sharing_scope.
  - Relationships: `artifacts`, `messages`, `snapshots`.
- **`Sandbox`** (`sandbox`) — one row per user (the `user_id` column is
  unique), tracking the user-shared sandbox container/pod. Fields:
  container_id, status (`SandboxStatus`: PROVISIONING / RUNNING / SLEEPING /
  TERMINATED / FAILED), created_at, last_heartbeat. There is no per-session
  Sandbox row — sessions share the user's sandbox.
- **`Artifact`** (`artifact`) — file produced by the agent and surfaced as a
  named artifact in the UI. Stores type (`ArtifactType`: web app, deck, doc,
  image, ...), the relative path under `outputs/`, name. The bytes live on the
  sandbox's filesystem; the row is just metadata.
- **`Snapshot`** (`snapshot`) — tar.gz of a session's `outputs/` +
  `attachments/`, stored in the file store (S3 in cloud, local disk in dev).
  Used to restore a session when the K8s pod has been torn down.
- **`BuildMessage`** (`build_message`) — turn-indexed message row.
  `message_metadata` JSONB stores the raw ACP packet (`user_message`,
  `agent_message`, `agent_thought`, completed `tool_call_progress`, latest
  `agent_plan_update`).

## Flow Diagrams

### Flow 1 — Cold start: user lands on `/craft/v1`, sandbox is provisioned

```
Browser                    api_server                  Postgres    SandboxManager (k8s/local)
   │                            │                          │                │
   │ GET /craft/v1              │                          │                │
   │ (page mount)               │                          │                │
   │                            │                          │                │
   │ POST /api/build/sessions   │                          │                │
   │ {llm_provider, llm_model,  │                          │                │
   │  demo_data_enabled, ...}   │                          │                │
   ├───────────────────────────►│                          │                │
   │                            │                          │                │
   │                            │ SessionManager.get_or_create_empty_session│
   │                            │   ↓                      │                │
   │                            │   get_empty_session_for_user(user, demo_match)
   │                            ├─────────────────────────►│                │
   │                            │◄──── existing or None ───│                │
   │                            │                          │                │
   │   (if existing empty AND sandbox is RUNNING AND health_check ok        │
   │    AND session_workspace_exists ⇒ return that session, skip the rest) │
   │                            │                          │                │
   │                            │ create_session__no_commit:                │
   │                            │  • check tenant cap (SANDBOX_MAX_CONCURRENT_PER_ORG)
   │                            │  • allocate_nextjs_port  (Postgres seq)   │
   │                            │  • create BuildSession row (flush, no commit)
   │                            ├─────────────────────────►│                │
   │                            │◄──── BuildSession (id, port) ─────────────│
   │                            │                          │                │
   │                            │ get_sandbox_by_user_id(user)              │
   │                            ├─────────────────────────►│                │
   │                            │◄── existing or None ─────│                │
   │                            │                                           │
   │                            │   ┌─ no sandbox row yet ───────────────┐  │
   │                            │   │ create_sandbox__no_commit (status=PROVISIONING)
   │                            │   │ ─► Postgres                        │  │
   │                            │   │ sandbox_manager.provision(sandbox_id,
   │                            │   │   user_id, tenant_id, llm_config)  │  │
   │                            │   │ ─► K8s API: create pod (image=v0.1.5,
   │                            │   │   2 SAs: runner + file-sync init)  │  │
   │                            │   │   init container: s5cmd sync s3://.../
   │                            │   │     {tenant}/knowledge/{user}/ → /workspace/files
   │                            │   │   pod becomes Ready (≤120s)        │  │
   │                            │   │ update_sandbox_status(RUNNING)     │  │
   │                            │   └────────────────────────────────────┘  │
   │                            │                                           │
   │                            │   ┌─ existing sandbox in TERMINATED/SLEEPING/FAILED
   │                            │   │  re-provision (same path as above)  │ │
   │                            │   └────────────────────────────────────┘  │
   │                            │                                           │
   │                            │   ┌─ existing sandbox in RUNNING ──────┐  │
   │                            │   │  health_check(sandbox_id, 5s)      │  │
   │                            │   │  if unhealthy ⇒ terminate + re-provision
   │                            │   │  else ⇒ reuse                      │  │
   │                            │   └────────────────────────────────────┘  │
   │                            │                                           │
   │                            │ sandbox_manager.setup_session_workspace(  │
   │                            │   sandbox_id, session_id, llm_config, port,
   │                            │   file_system_path, user_name/role,       │
   │                            │   use_demo_data, excluded_user_library_paths)
   │                            ├──────────────────────────────────────────►│
   │                            │                                       kubectl exec into pod:
   │                            │                                         mkdir sessions/<id>
   │                            │                                         cp -r outputs-template
   │                            │                                         cp -r venv-template
   │                            │                                         ln -s ../files (or demo)
   │                            │                                         materialize .opencode/skills
   │                            │                                         render AGENTS.md (placeholders)
   │                            │                                         write opencode.json
   │                            │                                         start `next dev` on port
   │                            │◄──────────────────────────────────────────│
   │                            │                                           │
   │                            │ db_session.commit()  (BuildSession + Sandbox)
   │                            │                          │                │
   │◄── 200 DetailedSessionResp ┤                          │                │
   │  {session, sandbox.status=RUNNING,                                     │
   │   session_loaded_in_sandbox=true}                                      │
   │                            │                          │                │
   │ usePreProvisionPolling     │                          │                │
   │   GET /sessions/{id}/pre-  │                          │                │
   │     provisioned-check      │                          │                │
   │   (until valid=true)       │                          │                │
   │ ───────────────────────────►                          │                │
   │◄── valid=true ─────────────│                          │                │
```

Notes worth pinning:
- One sandbox per user; one session per page-load. The first session a user
  ever has triggers a fresh `provision()`. Every subsequent session reuses the
  same pod and just runs `setup_session_workspace`.
- The "empty session" reuse path is what makes the second visit to
  `/craft/v1` feel instant — no pod creation, no port allocation.

### Flow 2 — User sends a message

```
Browser (useBuildStreaming)            api_server / SessionManager           Sandbox pod (via kubectl exec)
   │                                            │                                      │
   │ POST /api/build/sessions/{id}/             │                                      │
   │   send-message  {content}                  │                                      │
   ├───────────────────────────────────────────►│                                      │
   │                                            │ check_build_rate_limits (paid/free)  │
   │                                            │ get_sandbox_by_user_id               │
   │                                            │ update_sandbox_heartbeat (now)       │
   │                                            │                                      │
   │   StreamingResponse opens SSE              │                                      │
   │   (text/event-stream, no buffering)        │                                      │
   │◄───────────────────────────────────────────┤                                      │
   │                                            │                                      │
   │                                            │ SessionManager.send_message:         │
   │                                            │  • verify session ownership          │
   │                                            │  • require sandbox.status==RUNNING   │
   │                                            │  • count existing USER msgs ⇒        │
   │                                            │    turn_index = N                    │
   │                                            │  • create_message(USER, turn_index,  │
   │                                            │    {type: user_message, content})    │
   │                                            │                                      │
   │                                            │ sandbox_manager.send_message(        │
   │                                            │   sandbox_id, session_id, content)   │
   │                                            ├─────────────────────────────────────►│
   │                                            │                                  ACPExecClient:
   │                                            │                                  reuse-or-spawn
   │                                            │                                  `opencode acp` proc
   │                                            │                                  in sessions/<id>/
   │                                            │                                  send JSON-RPC:
   │                                            │                                    session/prompt
   │                                            │                                    {content}
   │                                            │                                      │
   │                                            │                                  agent loops, runs
   │                                            │                                  tools (bash/edit/
   │                                            │                                  read/skill/...)
   │                                            │                                      │
   │                                            │◄────── stream of ACP events ─────────┤
   │                                            │   agent_message_chunk                │
   │                                            │   agent_thought_chunk                │
   │                                            │   tool_call_start (passthrough only) │
   │                                            │   tool_call_progress (running)       │
   │                                            │   tool_call_progress (completed)     │
   │                                            │   agent_plan_update (latest only)    │
   │                                            │   ...                                │
   │                                            │   prompt_response  (terminal)        │
   │                                            │                                      │
   │                                            │ For each event:                      │
   │                                            │   • BuildStreamingState.add_*        │
   │                                            │     (accumulate chunks per turn)     │
   │                                            │   • on type-change: flush prior      │
   │                                            │     chunks → BuildMessage row        │
   │                                            │   • on tool_call_progress=completed: │
   │                                            │     create BuildMessage row          │
   │                                            │   • on agent_plan_update: upsert     │
   │                                            │     latest plan for turn             │
   │                                            │   • serialize ACP packet → SSE       │
   │  yield "event: message\ndata: {...}\n\n"   │                                      │
   │◄───────────────────────────────────────────┤                                      │
   │                                            │                                      │
   │   (every ≤15s of silence: ": keepalive\n\n")                                      │
   │◄───────────────────────────────────────────┤                                      │
   │                                            │                                      │
   │                                            │ on prompt_response:                  │
   │                                            │   • flush remaining chunks           │
   │                                            │   • _save_build_turn(state)          │
   │                                            │   • scan outputs/ for new artifacts  │
   │                                            │     ⇒ insert/upsert Artifact rows    │
   │                                            │   • db_session.commit()              │
   │                                            │                                      │
   │  SSE stream closes                         │                                      │
   │◄───────────────────────────────────────────┤                                      │
   │                                            │                                      │
   │  store updates: messages, artifacts,       │                                      │
   │   plan, output panel auto-opens for        │                                      │
   │   web-app artifacts                        │                                      │
```

Notes worth pinning:
- `BuildStreamingState` is the per-turn accumulator. The agent emits
  fine-grained `*_chunk` packets; we don't persist each chunk — we accumulate
  and flush at type boundaries to get one assistant `BuildMessage` per
  contiguous run.
- Only `tool_call_progress` packets with `status="completed"` get persisted.
  In-flight `tool_call_start` and intermediate progress are streamed to the UI
  but never written to Postgres.
- The `ACP_MESSAGE_TIMEOUT` cap (default 900s) bounds how long we'll wait for
  a `prompt_response`. SSE keepalives every `SSE_KEEPALIVE_INTERVAL` (15s)
  keep the HTTP connection alive across long thinking turns.
- Heartbeat is updated *once* per send-message at the API layer; idle
  cleanup uses that timestamp to decide which sandboxes to put to sleep.

### Flow 3 — User opens an old session

There are two cases the frontend has to distinguish: the session's workspace
is still in the running pod (cheap), or it isn't (snapshot restore + possibly
re-provision).

```
Browser                                api_server                Postgres / FileStore     SandboxManager
   │                                       │                            │                       │
   │ GET /craft/v1?sessionId=<id>          │                            │                       │
   │  (page mount, sessionId from URL)     │                            │                       │
   │                                       │                            │                       │
   │ GET /api/build/sessions/{id}          │                            │                       │
   ├──────────────────────────────────────►│                            │                       │
   │                                       │ get_session(session_id, user)                      │
   │                                       │   • update last_activity_at                        │
   │                                       │ get_sandbox_by_user_id                             │
   │                                       │ if sandbox.status==RUNNING:                        │
   │                                       │   session_workspace_exists(sandbox, session)──────►│
   │                                       │◄────────── true / false ───────────────────────────│
   │                                       │                                                    │
   │◄── DetailedSessionResp                ┤                                                    │
   │   {session, sandbox.status,           │                                                    │
   │    session_loaded_in_sandbox: bool}   │                                                    │
   │                                       │                                                    │
   │ GET /api/build/sessions/{id}/messages │                                                    │
   ├──────────────────────────────────────►│ list rows ordered by turn_index, created_at        │
   │◄── messages[] ────────────────────────┤ (ACP packets straight from message_metadata JSONB) │
   │                                       │                                                    │
   │  ┌─ Case A: session_loaded_in_sandbox=true ────────────────────────────────────────┐       │
   │  │  UI is ready immediately. Output panel can call list_directory / read_file as   │       │
   │  │  the user clicks artifacts. No restore needed.                                  │       │
   │  └─────────────────────────────────────────────────────────────────────────────────┘       │
   │                                                                                            │
   │  ┌─ Case B: session_loaded_in_sandbox=false ──────────────────────────────────────┐        │
   │                                                                                            │
   │ POST /api/build/sessions/{id}/restore │                                                    │
   ├──────────────────────────────────────►│                                                    │
   │                                       │                                                    │
   │                                       │ ┌─ sandbox.status == RUNNING ─────────────────┐    │
   │                                       │ │ health_check(10s)                           │    │
   │                                       │ │ if healthy AND session_workspace_exists:    │    │
   │                                       │ │   return immediately                        │    │
   │                                       │ │ if NOT healthy:                             │    │
   │                                       │ │   terminate(); status=TERMINATED;           │    │
   │                                       │ │   fall through to re-provision              │    │
   │                                       │ └─────────────────────────────────────────────┘    │
   │                                       │                                                    │
   │                                       │ ┌─ sandbox in SLEEPING/TERMINATED ─────────────┐   │
   │                                       │ │ status=PROVISIONING (commit so peers know)   │   │
   │                                       │ │ provision(sandbox, user, tenant, llm_config) ├──►│
   │                                       │ │   k8s create pod, init container s5cmd sync,│    │
   │                                       │ │   wait Ready                                 │   │
   │                                       │ │ status=RUNNING (commit)                      │   │
   │                                       │ └──────────────────────────────────────────────┘   │
   │                                       │                                                    │
   │                                       │ session_workspace_exists?  ───────────────────────►│
   │                                       │                                                    │
   │                                       │ ┌─ workspace missing ──────────────────────────┐   │
   │                                       │ │ allocate_nextjs_port if session.nextjs_port  │   │
   │                                       │ │   is None (commit early)                     │   │
   │                                       │ │ get_latest_snapshot_for_session              │   │
   │                                       │ │   (Snapshot row for this session)            │   │
   │                                       │ │                                              │   │
   │                                       │ │ ┌─ snapshot exists (K8s only) ────────────┐  │   │
   │                                       │ │ │ restore_snapshot(                       ├─►│   │
   │                                       │ │ │   sandbox, session,                     │  │   │
   │                                       │ │ │   snapshot.storage_path,                │  │   │
   │                                       │ │ │   port, llm_config, demo_data)          │  │   │
   │                                       │ │ │ ─► s5cmd cp s3://.../snap.tar.gz pod    │  │   │
   │                                       │ │ │ ─► tar -xzf into sessions/<id>          │  │   │
   │                                       │ │ │ ─► regen AGENTS.md, opencode.json       │  │   │
   │                                       │ │ │ ─► start `next dev` on port             │  │   │
   │                                       │ │ │ session.status=ACTIVE; commit           │  │   │
   │                                       │ │ └─────────────────────────────────────────┘  │   │
   │                                       │ │                                              │   │
   │                                       │ │ ┌─ no snapshot ───────────────────────────┐  │   │
   │                                       │ │ │ setup_session_workspace(...)            ├─►│   │
   │                                       │ │ │  (fresh outputs/, no prior artifacts)   │  │   │
   │                                       │ │ │ session.status=ACTIVE; commit           │  │   │
   │                                       │ │ └─────────────────────────────────────────┘  │   │
   │                                       │ └──────────────────────────────────────────────┘   │
   │                                       │                                                    │
   │                                       │ update_sandbox_heartbeat                           │
   │◄── DetailedSessionResp                ┤                                                    │
   │   {session_loaded_in_sandbox=true}    │                                                    │
   │                                       │                                                    │
   │ list artifacts, get webapp URL,       │                                                    │
   │  poll Next.js /_next/static for ready │                                                    │
   │  → output panel populated             │                                                    │
   │  └─────────────────────────────────────────────────────────────────────────────────┘       │
```

Notes worth pinning:
- The cheap path is most-common-case: a returning user whose pod is still
  RUNNING and whose session dir was never cleaned up. UI just renders the
  message list and is done.
- `restore_snapshot` only does meaningful work on Kubernetes. On `local`,
  workspaces persist on disk so this is largely a no-op.
- The `Snapshot` table is per-session, append-only — `get_latest_snapshot_for_session`
  picks the most recent. Snapshots are written by the idle-cleanup Celery
  task at sleep time, *not* on every send-message.

## Known Constraints That V1 Plans Address

These are deliberately current-state observations; the V1 plans in this
directory propose how to fix each.

1. **Knowledge corpus is dumped as JSON files into the sandbox.** No ACL,
   no freshness, no parity with chat search. (`search.md` replaces this
   with a `company_search` HTTP tool/skill.)
2. **`local` is the docker-compose default and offers no isolation.**
   (`sandbox-backends.md` adds a `docker` backend.)
3. **Skills are baked into the sandbox image.** No customer uploads, no
   per-user grants. (`skills.md` introduces a DB-backed skills primitive.)
4. **No path for the agent to call external services safely.** Skill
   authors who want Linear/HubSpot/etc. have no way to inject credentials
   without leaking them. (`interception.md` adds the egress proxy. OAuth-
   for-apps and approvals are companion projects.)
5. **No durable run/audit layer beyond the message stream.** Every search
   the agent ran, every external call, every approval — none of it is
   queryable without scraping the chat transcript.
6. **No scheduled/triggered runs.** Craft is interactive-only today.
7. **Backend modules are still named `build/` even though the product is
   "Craft."** The V1 plans explicitly do not rename to avoid migration risk.

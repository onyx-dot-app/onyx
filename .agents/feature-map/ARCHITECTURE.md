# Onyx Architecture

How the processes, the data stores and the main flows fit together. Each step
links to the component that owns its detail. This page owns only the paths that
cross several components: ingestion, a chat turn, and a Craft turn. For a rule
that applies to every new route, table, task or LLM call, read
[CROSS-CUTTING.md](CROSS-CUTTING.md).

---

## Processes

| Process | Entry point | Job | Owner |
|---|---|---|---|
| Web server | `web/` (Next.js) | The browser UI. | [[chat-frontend]], [[craft-frontend]] |
| API server | `backend/onyx/main.py` | Every `/api` route. A chat turn and a Craft turn runner run in its threads. | [[core-chat-loop]], [[craft-sessions]] |
| Celery workers and beat | `backend/onyx/background/celery/versioned_apps/` | Ingestion, sync, pruning, deletion, user files, scheduled Craft runs. | [[background-jobs]] |
| Model servers | `backend/model_server/main.py` | Self-hosted embedding models, one deployment for queries and one for indexing. A cloud embedding provider is called directly, not through it. | [[document-index]] |
| Slack bot | `backend/onyx/onyxbot/slack/listener.py` | Socket Mode listener. Runs the chat turn in its own process. | [[slack-bot]] |
| Discord bot | `backend/onyx/onyxbot/discord/client.py` | Gateway listener. Calls the API server over HTTP. | [[discord-bot]] |
| MCP server | `backend/onyx/mcp_server_main.py` | Onyx as an MCP server. No database; forwards each call to the API server. | [[mcp-server]] |
| Code interpreter | `code-interpreter` service in `deployment/docker_compose/docker-compose.yml` | Runs the Python tool's code. | [[code-execution]] |
| Craft sandbox pods | `deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml` | One pod per Craft user, or one container with the Docker backend, running `opencode serve`. | [[craft-sandboxes]] |
| Sandbox egress proxy | `backend/onyx/sandbox_proxy/` | Every outbound request from a sandbox. | [[craft-external-apps]] |
| Nginx | `deployment/data/nginx/` | Routes `/api`, SAML and SCIM to the API server, `/mcp` to the MCP server, the rest to the web server. `/mcp/oauth/callback` is an exact match that goes to the web server (`deployment/data/nginx/mcp.conf.inc.template`). | None ([PATHS.md](PATHS.md#not-mapped)). [[mcp-server]] owns the `/mcp` routing. |

`backend/AGENTS.md` lists the Celery workers and their roles. The `-Q` flags in
`backend/supervisord.conf` and the Helm worker templates decide which worker
reads which queue. A deployment with `DISABLE_VECTOR_DB` runs no Celery. In
that mode a poller in the API server does the small periodic jobs
(`background/periodic_poller.py:start_periodic_poller`).

---

## Data stores

- **Postgres** is the source of truth. Each tenant has its own schema
  (`db/models.py:Base`, migrated by `backend/alembic/`). The `public` schema
  holds the cross-tenant catalog (`PublicBase`, migrated by
  `backend/alembic_tenants/`). See [[multi-tenancy]].
- **OpenSearch** holds chunks, vectors and a copy of each document's ACL,
  document sets, boost and cc-pair IDs. The copy can lag Postgres until the
  metadata sync runs. During a reindex two index generations exist. See
  [[document-index]].
- **Redis** is the Celery broker and result backend. It also holds locks,
  fences, tenant-prefixed keys and, by default, login sessions. Code that only
  needs a key-value store uses `cache/factory.py:get_cache_backend`, which can
  run on Postgres. The chat resume buffer and the stop signal use it. See
  [[background-jobs]] and [[multi-tenancy]].
- **The file store** (`file_store/file_store.py:get_default_file_store`) is S3
  by default, or GCS, Azure Blob or Postgres large objects. It holds uploads,
  staged ingestion batches, connector checkpoints and Craft snapshots. See
  [[file-store-and-user-files]].

---

## User journeys

A journey crosses components. Judge a change against the journey, then read
the **User experience** section of each component it names. A developer who
builds on an internal component, such as [[background-jobs]] or
[[tools-framework]], is a user too; that component's **Callers** section
states what they see.

- **An admin connects a source, and users find its documents.** The first run
  starts without a click, and the document count grows as batches finish. A
  bad document shows as its own error. A run that dies resumes; a run with no
  heartbeat fails. Users find the documents once a batch is written. Read
  [[connectors]], [[indexing-pipeline]] and [[internal-search]]; the trace is
  Flow 1.
- **A source removes a person's access.** An admin removes a person from a
  Drive folder. The person keeps seeing the document until the next doc sync
  and the next metadata sync, which is the source's sync interval plus queue
  time. A failed sync keeps the last ACL, so access does not widen. A change to
  a person's Onyx group membership applies on the next query. Read [[google-drive]],
  [[permission-sync]], [[document-index]] and [[access-control]].
- **A user asks a question in chat.** Tool steps and the answer stream, with
  citations. Leaving the page does not stop the run; Stop keeps the partial
  answer. A failure before the run shows one error; a usage limit shows the
  reset time. Read [[chat-frontend]], [[core-chat-loop]], [[citations]] and
  [[rate-and-usage-limits]]; the trace is Flow 2.
- **A user asks the bot in a Slack channel.** A public channel post answers
  from public indexed documents only. Federated Slack results follow the
  Slack token instead ([[federated-search#slack-results-have-no-acl]]). A DM, a slash command or an ephemeral reply uses
  the asker's own access when their email matches an Onyx user. Read
  [[slack-bot]] and [[federated-search]], and the acting-user table in
  [CROSS-CUTTING.md](CROSS-CUTTING.md).
- **A user builds something in Craft.** The turn runs on the server; a reload
  attaches to it again. An action that needs permission pauses the turn for
  approval. Files under `outputs/` appear as cards. A sleeping sandbox wakes on
  the next turn. Read [[craft-sessions]], [[craft-frontend]],
  [[craft-sandboxes]] and [[craft-external-apps]]; the trace is Flow 3.
- **A license expires.** Admins see warnings first, then a grace period. After
  it, pages other than billing and user management show an access-restricted
  screen and API calls get 402. The Slack bot replies that the subscription has expired. The Discord
  bot gives a gated cloud tenant no reply, and on a self-hosted deployment it
  posts its generic error. Read [[billing]], [[slack-bot]] and [[discord-bot]].

---

## Flow 1: ingestion

```
beat: check_for_indexing (primary worker)            [[indexing-pipeline]]
  creates an IndexAttempt per cc-pair and SearchSettings generation that is due
docfetching_proxy_task (docfetching worker)          [[indexing-pipeline]]
  spawned process runs the connector                 [[connectors]]
  per batch: stage Documents in the file store, save the checkpoint,
             send one docprocessing task
docprocessing_task, one per batch (docprocessing)    [[indexing-pipeline]]
  upsert Document rows; dedup gate skips unchanged documents
  chunk -> contextual RAG (optional) -> embed        [[llm-providers]], [[document-index]]
  attach ACL, document sets, boost                   [[access-control]]
  write to the index of the attempt's own SearchSettings only
  count the batch under the IndexAttempt row lock,   [[indexing-pipeline#batch-completion-row-lock]]
  then resolve the batch's open errors
beat: check_for_doc_permissions_sync (EE)            [[permission-sync]]
  heavy worker: source ACL -> Postgres; bump Document.last_modified only on a change
beat: check_for_external_group_sync (EE)             [[permission-sync]]
  heavy worker: group membership -> Postgres only; no index write
beat: check_for_vespa_sync_task (primary)            [[document-index]]
  last_modified > last_synced -> document_index_metadata_sync_task (light)
  rewrites ACL, sets, boost, hidden, cc-pair IDs in both generations; no re-embed
```

- **Why two phases.** Docfetching isolates third-party SDK code in a process that
  a watchdog can kill. Docprocessing scales embedding on its own pool. The
  staged batch is the handoff and the recovery unit ([[indexing-pipeline]]).
- **Postgres changes reach the index only through the metadata sync.** Any
  writer that changes a document's ACL inputs, sets, boost or cc-pair links
  bumps `last_modified`. The chunk keeps the old value until the sync runs
  ([[document-index#bump-last-modified]]). A change to a user's group
  membership needs no sync, because the query reads the user's current groups.
- **Removal.** Pruning (`check_for_pruning`) and connector deletion
  (`check_for_connector_deletion_task`) both fan out
  `background/celery/tasks/shared/tasks.py:document_by_cc_pair_cleanup_task`. It deletes a
  document that this pair owned alone, or removes only this pair's link and
  access ([[background-jobs]], [[connectors]]).
- **Other ways in.** A user upload runs the same pipeline through
  `UserFileIndexingAdapter` on the `user_file_processing` worker, with no fetch
  phase ([[file-store-and-user-files]]). A push to `/onyx-api/ingestion` runs
  it inside the request ([[onyx-api]]). A reindex copies and re-embeds stored
  chunks into the new generation instead of fetching again ([[document-index]]).
- **Query time.** Search filters chunks by the user's ACL in the index, then
  censors the results ([[access-control]]). A wrong ACL on a chunk is fixed by
  the next metadata sync, not by re-indexing.

---

## Flow 2: a chat turn

```
POST /api/chat/send-chat-message                     server/query_and_chat/chat_backend.py
  identity and tenant                                [[auth-and-identity]], [[multi-tenancy]]
  token budgets, API-call cap (Depends)              [[rate-and-usage-limits]]
handle_stream_message_objects                        [[core-chat-loop]]
  (or handle_multi_model_stream) -> _stream_chat_turn
  reject document-set filters the user cannot see    [[access-control]]
build_chat_turn:
  agent                                              [[agents-personas]]
  managed-key cost cap, then the LLM                 [[rate-and-usage-limits]], [[llm-providers]]
  load history                                       [[chat-persistence]]
  Query Processing hook                              [[hooks]]
  save the user message                              [[chat-persistence]]
  reserve one assistant row per model
_run_models: one worker thread per model, one writer thread
  construct_tools                                    [[tools-framework]]
  run_llm_loop, each cycle:
    construct_message_history                        [[context-assembly]]
    run_llm_step: stream from the provider           [[llm-providers]]
    run_tool_calls: search, web, code, MCP ...       [[internal-search]], [[web-search]],
                                                     [[mcp-and-custom-tools]]
    citation processor rewrites [n] markers          [[citations]]
  Emitter -> writer -> resume buffer + NDJSON        [[streaming-protocol]]
_persist_model_outcome -> llm_loop_completion_handle
  -> save_chat_turn                                  [[chat-persistence]]
  optional history compression                       [[context-assembly]]
generation spans -> user_usage                       [[observability]]
```

- **The writer thread owns the run.** A browser that disconnects does not stop
  it. Only the stop fence stops it, and every exit path saves once
  ([[core-chat-loop]]).
- **Other callers of the same turn.** The Slack bot calls
  `handle_stream_message_objects` in its own process, so it skips the route's
  `Depends` checks. It calls `check_token_rate_limits` itself, but no API-call
  cap applies ([[slack-bot]]). The Discord bot, the widget and API callers
  use the HTTP route. Deep research and the agent tools reuse the loop pieces
  ([[core-chat-loop]]). The acting user for each caller is in
  [CROSS-CUTTING.md](CROSS-CUTTING.md).
- **Budgets lag.** Usage reaches `user_usage` from tracing spans in batches, so
  a budget check sees usage a few seconds late
  ([[rate-and-usage-limits#budgets-lag-usage]]).

---

## Flow 3: a Craft turn

```
POST /build/sessions/{id}/send-message               server/features/build/session/messages.py:send_message
  save the user message, create InteractiveTurn      [[craft-sessions]]
  start_interactive_turn_runner (daemon thread), return turn_id
runner:
  ensure_session_ready -> ensure_sandbox_ready       [[craft-sandboxes]]
    reserve (ensure the Craft PAT) -> provision or wake the pod -> finalize
  rebuild the session workspace from its snapshot if the pod lacks it
  prompt_slot: one prompt per session
  drive_one_prompt -> opencode serve in the pod      [[craft-streaming]]
    the agent loop runs inside opencode:
      model calls  -> /gateway/v1 with the Craft PAT [[llm-gateway]]
      other HTTP   -> sandbox egress proxy: policy,  [[craft-external-apps]]
                      approval, credential injection
    PodEventBus -> translate_opencode_event -> persist_sandbox_event
      (saves finished blocks and tool results, not each delta)
  persist_turn_outputs, finish_turn                  [[craft-sessions]]
GET /build/sessions/{id}/turns/{turn_id}/events      [[craft-streaming]], [[craft-frontend]]
```

- **The opposite split from chat.** In chat, the API server runs the LLM loop
  and calls each tool. In Craft, the API server sends one prompt and records
  events. Planning, tools and model calls happen in the sandbox
  ([[craft-sessions]]).
- **Attach never drives the turn.** The runner and each browser attach
  subscribe to the same per-pod event bus. An attach may only restart a stalled
  runner ([[craft-streaming#attach-never-drives]]). It has no replay buffer; a
  page that reattaches reads saved history at the end of the turn
  ([[craft-streaming#no-replay-buffer]]).
- **The sandbox outlives the turn but not the idle timeout.** Sleep saves
  `outputs/`, `attachments/` and the opencode history, then removes the pod.
  The next turn restores them ([[craft-sandboxes]]).
- **Scheduled runs** create a headless session in the owner's sandbox and run
  one turn through their own executor on the `scheduled_tasks` worker
  ([[craft-scheduled-tasks]]).

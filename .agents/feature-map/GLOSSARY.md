# Onyx Glossary

Onyx overloads several words. The product name and the code name often differ,
and one word can mean different things in different layers. Read this before
you trust a name. Each entry is a definition and a link to the component that
owns the rules.

---

## Product words and code words

| Product word | Code identifier | Note |
|---|---|---|
| Agent | `Persona` (`backend/onyx/db/models.py:Persona`) | The same thing. The product says Agent; the `persona` table, the `/persona` API paths and most Python names say Persona. Search for both words. See [[agents-personas]]. |
| Default assistant | `DEFAULT_PERSONA_ID` (0) | The built-in Persona that a chat with no named agent uses. See [[agents-personas]]. |
| Default Chat | the default assistant's `Persona__Tool` rows | The chat with no custom agent. Its plugin tools are tool rows of the default assistant. See [[plugins#default-chat-is-persona-tool]]. |
| Onyx | Danswer | Some identifiers and comments say Danswer. It is the same product. |
| Craft | `build` | The product is Craft. The backend directory `backend/onyx/server/features/build/`, the `/build` API paths and `BUILD_MODE_FEATURE_ID` say build. |
| Action | `Tool` | Some UI text calls tools "Actions". The code calls them Tools. |
| Plugin | MCP server, OpenAPI `Tool`, or Craft external app | The UI word for all three. See [[plugins]]. |
| Free plan | `Tier.COMMUNITY` | The web UI shows the Community tier as the Free plan. |
| Workspace | the tenant | The tenant-wide scope, as in workspace setting, workspace default and workspace policy. An admin sets it. Not the session workspace (see Craft vocabulary). See [[multi-tenancy]]. |

## The collisions

**`SearchDoc`** exists twice.
- `backend/onyx/context/search/models.py:SearchDoc` is the in-flight Pydantic model a
  search returns.
- `backend/onyx/db/models.py:SearchDoc` is the table row that saves a document a
  turn surfaced, linked to the `ToolCall` that found it.

**`Tool`** exists three ways.
- `backend/onyx/tools/interface.py:Tool` is the abstract class every tool implements.
- The `Tool` table has one row per configured tool: a built-in, an OpenAPI action
  or an MCP tool. The column that is set tells them apart: `in_code_tool_id`,
  `openapi_schema` or `mcp_server_id`. See [[tools-framework]].
- `backend/onyx/agents/tools.py:AgentTool` is the tool the shared runtime runs.
  A chat `Tool` becomes one through `Tool.bind`. The control tools of the
  research and coding agents, such as `think_tool` and `generate_report`, are
  `AgentTool` objects only, with no `Tool` class and no table row. See
  [[tools-framework]].

**"Turn"** means three things.
- Chat backend: one user message plus everything the assistant does before it
  finishes.
- `Placement.turn_index`: a rendering block, not a backend turn. See
  [[streaming-protocol#turn-index-is-not-a-turn]].
- Craft: one user message and the agent's response in a Craft session, tracked
  by an interactive turn record with a `turn_id`. Craft's `turn_index` is not
  chat's. See [[craft-streaming#no-chat-packet-placement]].

**"Search"** covers four mechanisms.
- `internal_search`: the tool over your indexed company data. See [[internal-search]].
- `web_search`: a separate tool that calls an external provider. See [[web-search]].
- Federated search: a search of a source at query time through its own API, with
  no indexing. The federated Slack connector is not the indexed Slack connector.
  See [[federated-search]].
- Chat search: `GET /chat/search` searches the user's own conversation history.
  See [[chat-persistence]].

**"Agent"** means three things: a `Persona`; an `agents/runtime.py:Agent` of
the shared runtime, such as `ChatAgent`, the deep research agent, the research
agent or the coding agent ([[agent-runtime]]); or the AI assistant in general.

**"Flow"** means two things.
- `LLMModelFlowType` (`backend/onyx/db/enums.py`) and the `LLMModelFlow`
  table (`backend/onyx/db/models.py:LLMModelFlow`): a model capability or a
  per-task model designation, such as CHAT, VISION or CHAT_NAMING. See
  [[llm-providers]].
- `LLMFlow` (`backend/onyx/tracing/flows.py`): the tag on a tracing span that says
  what an LLM call was for. See [[observability]].

**"Settings"** means three things.
- The workspace `Settings` record (`backend/onyx/server/settings/models.py:Settings`):
  one key-value record per tenant that holds workspace options. See
  [[chat-preferences]].
- The user's Settings page: per-user preferences. See [[chat-preferences]].
- Search settings (`SearchSettings`): the embedding model and index
  configuration. See [[document-index]].

**"Gated"** means three unrelated things.
- `GATED_ACCESS`: a self-hosted license state, expired past the grace period.
  See [[billing]].
- `gated_tenants`: the cloud set of tenants whose subscription lapsed. See
  [[billing]].
- `GatedApp`: the Craft action-policy identity of one external app or one MCP
  server. It has nothing to do with billing. See [[craft-external-apps]].

**"Public" (API)** means two unrelated things. `PUBLIC_API_TAGS` marks a route that
is documented for integrators; it still needs authentication. `PUBLIC_ENDPOINT_SPECS`
exempts a route from the startup auth check; its handler does its own check, if any. See [[onyx-api#two-meanings-of-public]].

**"Hook"** in [[hooks]] means a hook extension: a customer HTTPS endpoint that Onyx
calls at a `HookPoint`. It is not a React hook, an agent hook or a Celery signal.

**"Telemetry"** means two things. Fleet telemetry is the allowlisted health and
usage events sent to the Onyx fleet service ([[fleet-telemetry]]).
`backend/onyx/utils/telemetry.py` is cloud PostHog product analytics
([[observability]]); `DISABLE_TELEMETRY` does not turn it off.

**MCP** goes both ways. Onyx is an MCP client of servers that an admin connects
([[mcp-and-custom-tools]]), and an MCP server for external clients
([[mcp-server]]). Check the direction before you change code named `mcp`.

**`message_end`** is not a chat packet. `AgentEventType.MESSAGE_END` in
`backend/onyx/agents/events.py` belongs to the agent runtime. The chat backend
never sends `message_end`, but the web and mobile packet enums list it, and
mobile code checks for it. See [[streaming-protocol]].

## The retrieval vocabulary

| Term | Meaning |
|---|---|
| Document | One item from a source: a page, a ticket, a message thread. |
| Chunk | A slice of a document, sized for embedding. The unit the index stores. |
| Section (`InferenceSection`) | Adjacent chunks from one document, joined again. The unit the LLM reads. See [[internal-search]]. |
| Lane | One parallel retrieval job inside `SearchTool.search`. Lanes fuse with weighted RRF. See [[internal-search]]. |
| Expansion | Two meanings. **Query expansion** rewrites one query into several. **Section expansion** pulls the chunks around a selected section. |
| Selection | The LLM stage that picks which retrieved sections to expand. Onyx uses it instead of a reranking model. |
| Content provider | The web-search backend that fetches page content for `open_url`. It is separate from the search provider that returns result lists. See [[web-search]]. |

## Ingestion vocabulary

| Term | Meaning |
|---|---|
| Connector | The code that pulls documents from one source type. See [[connectors]]. |
| Credential | The stored, encrypted secret for one account on a source. See [[cc-pairs-and-creds]]. |
| cc-pair (`ConnectorCredentialPair`) | One connector config joined to one credential, and the unit that indexing, access, scheduling and deletion act on. See [[cc-pairs-and-creds#pair-is-the-unit]] and [[cc-pairs-and-creds#pair-id-is-not-the-primary-key]]. |
| Run resolution | An admin mark that moves a failed run, or a run with document errors, out of the open lists. It does not resolve the run's error rows; see the Decisions in [[cc-pairs-and-creds]]. |
| Gateway | A `SourceOperations` subclass in `<source>/source_operations.py`. It is the only module that imports the source SDK. Indexing, EE permission sync and capability checks call it. Not the [[llm-gateway]]. See [[connectors]]. |
| Slim listing | `retrieve_all_slim_docs` and its perm-sync variant. They list document ids, and for perm sync the readers, with no bodies. Pruning compares the index with it. See [[connectors]]. |
| Field policy | The `connectors/field_policy.py:FieldPolicy` annotation on a connector config field. It tells an edit plan what work a change needs. See [[connectors]]. |
| Capability check | A named probe of one credential or config assumption. It is not `validate_connector_settings`. See [[connector-capability-checks]]. |
| Draft run | A capability-check run on the unsaved add-connector form, or an edit's dry run. Its results live in the cache backend, not in database rows. See [[connector-capability-checks]]. |
| Indexing hold | The rule that keeps a pair's first index attempt from starting while its checks run or after a required check failed. See [[connector-capability-checks]]. |
| Index attempt | One run of indexing for a cc-pair and one `SearchSettings` generation. See [[indexing-pipeline]]. |
| Fence (Celery) | A Redis key that marks a flow as running, such as a pair's pruning or deletion. It differs from the chat fences below. See [[background-jobs]]. |
| Docfetching / docprocessing | The two indexing phases. Docfetching runs the connector and stages document batches. Docprocessing chunks, embeds and writes one batch per task. See [[indexing-pipeline]]. |
| Builder (Outlook) | The mailbox that writes a thread's shared document: the sender of the first message, or else the lowest mailbox id that the first message names and that the run can open. See [[outlook]]. |
| Document set | An admin-defined group of cc-pairs and federated connectors, used to scope an agent or a search. See [[access-control]]. |
| User file | A file a user gave Onyx directly, as opposed to a connector document. See [[file-store-and-user-files]]. |
| `file_id` and `UserFile.id` | `FileRecord.file_id` names a blob. `UserFile.id` is the UUID that the frontend, the LLM and the index use. See [[file-store-and-user-files]]. |
| Project | A user's files and instructions kept across sessions. See [[projects]]. |
| Fit check | `chat/files.py:extract_context_files` decides whether project and agent files go inline or through retrieval. See [[projects]]. |

## Index vocabulary

| Term | Meaning |
|---|---|
| Search settings (`SearchSettings`) | The row that defines the embedding model and index configuration. |
| PRESENT / FUTURE | `IndexModelStatus`. PRESENT is the live index. FUTURE is a second index that a reindex builds; code calls its settings the secondary settings. See [[document-index]]. |
| Reindex port | Copies and re-embeds PRESENT chunks into a FUTURE index. It does not fetch the sources again. See [[document-index]]. |
| Metadata sync | The task (`vespa` in Celery names) that copies a document's ACL, document sets and flags from Postgres into its chunks with no re-embed. See [[document-index]]. |
| `hybrid_alpha` | A caller-level keyword-versus-semantic hint. Do not assume it controls scoring. See [[document-index]]. |

## Access vocabulary

| Term | Meaning |
|---|---|
| ACL | The access control list stored on each indexed document and compiled into every search query as a filter. See [[access-control]]. |
| External permissions | Permissions copied from the source system, as opposed to Onyx groups. See [[permission-sync]]. |
| Lease (permission sync) | The open attempt row that locks one pair's sync, kept alive by a heartbeat. See [[permission-sync]]. |
| Open / ACL / hidden cc-pairs | The three sets in `CCPairAccessFilter` that query-time cc-pair filtering uses. See [[access-control]]. |
| Curator | A user with `is_group_manager` and the scoped manager bundle, limited to the groups they manage. See [[authorization#user-role-is-dead]]. |
| GATE 1 / GATE 2 | GATE 1 is `require_permission` at the route; with `allow_scope=True` it lets a scoped manager reach the handler. GATE 2 is the scope check in the handler. See [[authorization#allow-scope-is-reach-only]]. |
| Scoped PAT | A personal access token whose scopes limit the routes it can reach. See [[authorization#scoped-pat-fails-closed]]. |
| Tenant | On cloud, a Postgres schema on one shard. Self-hosted has one tenant. See [[multi-tenancy]]. |
| CE / EE | Community Edition (MIT, `backend/onyx/`) and Enterprise Edition (`backend/ee/onyx/`, which mirrors the CE layout). See [[editions-and-gating]]. |
| Tier | The plan a deployment resolves to: COMMUNITY, BUSINESS or ENTERPRISE. It is not the edition: loaded EE code is not an unlocked tier. See [[editions-and-gating]]. |
| Tier vs CustomerTier | `Tier` is the internal tier in `backend/onyx/server/settings/models.py`. `CustomerTier` is the control-plane value in `backend/ee/onyx/server/license/models.py`, with no COMMUNITY. See [[billing]]. |

## Chat internals

| Term | Meaning |
|---|---|
| Step / cycle | One model generation and the tool calls it requests. A chat response has up to `MAX_LLM_CYCLES` of them. See [[agent-runtime]]. |
| Run | One execution of an agent on the shared runtime (`agents/runtime.py:Run`). Its `RunState` records the input, steps, outcome and child runs. A chat response's root run ID is its assistant `ChatMessage` ID. See [[agent-runtime#run-id-is-message-id]]. |
| Stream ID | The key that the processing fence, the stop fence and the stream buffer share. See [[core-chat-loop]]. |
| Presenter and renderer | `ResponsePresenter` and `MessageRenderer` turn runtime events into packets. They never drive execution. See [[core-chat-loop#presentation-does-not-drive-execution]]. |
| Emitter | The object that stamps `model_index` on a packet and hands it to delivery. See [[streaming-protocol#emitter-sets-model-index]]. |
| Reminder | A trailing message with one or two critical instructions. See [[context-assembly]]. |
| Custom agent prompt | The agent's instructions, sent as a user message near the newest user message. See [[context-assembly]]. |
| Fence (chat) | A cache key that acts as a flag: the stop fence means the user pressed stop, and the processing fence holds the live stream ID. The admission owner key, not a fence, marks a busy session. See [[core-chat-loop#session-admission]]. |
| Stopping tool | A tool after which the next step offers no tools, such as `generate_image`. See [[core-chat-loop#stopping-tools]]. |
| `BASH_TOOL_SENTINEL_ID` | The id that the coding agent gives its in-memory `BashTool`. See [[code-execution#bash-tool-sentinel]]. |
| Message types | `ChatMessage` (the row), `ChatResponseItem` (the saved steps of a response), `llm/models.py:Message` (the conversation type the runtime uses) and `llm/model_request.py:ChatCompletionMessage` (the provider wire form). See [[core-chat-loop#three-message-types]]. |
| Active branch | The chain of `latest_child_message_id` pointers from a session's root message. See [[chat-persistence]]. |
| Reserved message | An assistant `ChatMessage` row created with placeholder text before streaming starts. See [[chat-persistence]]. |
| Incognito and record mode | `IncognitoRecordMode` is fixed on a session and decides what the database keeps. See [[chat-persistence]]. |
| Child session | A `ChatSession` with `spawned_by_message_id` set. Research and coding child agents get one in a session that keeps content. See [[chat-persistence]]. |
| Not wired | A part of the shared runtime that no product path reaches: suspension, input requests, and checkpoint handoff and resume. See [[agent-runtime#wire-module]]. |
| `use_memories` vs `enable_memory_tool` | `use_memories` controls whether memories reach the prompt. `enable_memory_tool` controls whether the memory tool can write them. See [[chat-preferences]]. |
| Decision model | A model that answers typed predicate, choice or score questions with probabilities, not through LiteLLM. See [[llm-providers]]. |
| Passthrough (LLM gateway) | A native OpenAI Responses or Anthropic Messages forward that skips `LitellmLLM`. See [[llm-gateway]]. |
| Root trace | The trace that a span needs to reach any processor. See [[observability#root-trace-required]]. |
| Fail strategy (hooks) | HARD stops the pipeline with an error. SOFT keeps the caller's default. See [[hooks#hard-aborts-soft-falls-back]]. |
| Global notification | A `Notification` row with no `user_id`. See [[notifications]]. |

## Bots

| Term | Meaning |
|---|---|
| Standard answer | An admin-written canned reply that the Slack bot posts instead of an LLM answer when a keyword set or a regex matches. EE only. See [[standard-answers]]. |
| Slack service account | The `SERVICE_ACCOUNT` user (`get_or_create_slack_service_account`) that is charged for Slack bot usage when the sender has no Onyx account. See [[slack-bot]]. |
| Discord service API key | One `ApiKey` per tenant, named `DISCORD_SERVICE_API_KEY_NAME`, that the Discord bot uses for every member. See [[discord-bot]]. |
| Logotype | The wordmark variant of the custom logo. See [[whitelabelling-and-theme]]. |

## Craft vocabulary

| Term | Meaning |
|---|---|
| Session workspace | The sandbox directory of one Craft session (`/workspace/sessions/<id>`), with its outputs, attachments and agent config. Not the tenant-wide workspace. See [[craft-sandboxes]]. |
| Action policy | `ALWAYS` (Auto-approve), `ASK` (Ask) or `DENY` (Disabled) for each catalog action or MCP tool. See [[craft-external-apps]]. |
| Workspace policy, personal choice, task choice | The three policy layers. See [[craft-external-apps]]. |
| `unspecified` | The synthetic whole-domain action for a connected-app request that matches no catalog action. See [[craft-external-apps]]. |
| Session grant | "Approve for session" for specific Ask actions in one Craft session. See [[craft-external-apps]]. |
| Sandbox sleep | Snapshot, then remove the pod. See [[craft-sandboxes]]. |
| Prompt slot | A renewable per-session cache lease (`server/features/build/sandbox/serve_transport.py`) that serializes the work on one opencode session. It is not the active-turn lock. See [[craft-sessions]]. |
| `turn_completed` | The Craft packet that the attach endpoint sends after the turn finishes. It is not opencode's `prompt_response`. See [[craft-streaming]]. |
| Settlement (Craft) | The browser step that replaces the live transcript with saved history after the turn ends, and then releases the prompt queue. See [[craft-frontend]]. |
| Built-in skill and custom skill | A built-in skill's files are on disk. A custom skill is an uploaded bundle with an installation policy. See [[skills]]. |

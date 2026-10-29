# Onyx Component Index

Every component in the map, grouped by domain, and the recipes for common tasks.
How to use the map is in [README.md](README.md). How the domains connect is in
[ARCHITECTURE.md](ARCHITECTURE.md). Rules that every change must follow are in
[CROSS-CUTTING.md](CROSS-CUTTING.md).

Onyx is two products on one platform. **Chat and Search** answers questions
from connected company data with citations. **Craft** runs a coding agent in a
sandbox. Both use the platform domain.

---

## Core loop

A chat turn: assemble context, run the agent loop with tools, stream packets, save the turn.

| Component | Summary |
|---|---|
| [core-chat-loop](components/core-chat-loop.md) | The turn engine. It takes one user message, claims the session, runs one shared-runtime agent per selected model in its own thread, delivers packets through one turn-level delivery path, and reports one final save outcome per model. |
| [context-assembly](components/context-assembly.md) | What the LLM sees on each step of a turn: the system prompt, the per-user block, the custom agent prompt, project files, history, file notices and the trailing reminder, kept within the token budget by the runtime's compaction. A wrong change here rarely raises an error; the answers just get worse. |
| [streaming-protocol](components/streaming-protocol.md) | The wire contract between the chat backend and every client: the packet vocabulary, the `Placement` coordinates, the path from a worker thread to the HTTP body, and the buffer that lets a client resume a stream it lost. |
| [tools-framework](components/tools-framework.md) | The shared machinery for every tool the chat model can call: the `Tool` interface, the built-in tool registry, per-model tool construction and gating, and the research and coding sub-agents. Concrete tools live in their own components; this one owns the rules that they all depend on. |
| [code-execution](components/code-execution.md) | Runs code for the user: `run_python` runs Python, and the coding agent's `bash` runs shell commands in a repository. Both are HTTP clients of an external Code Interpreter service, so no user code runs in an Onyx process. |
| [image-generation](components/image-generation.md) | Turns a prompt, and optional reference images, into an image through one admin-chosen provider. It serves the `generate_image` chat tool and a standalone endpoint that the CLI and Craft use. |
| [citations](components/citations.md) | The chain that turns a retrieved document into a numbered marker the model emits, and turns that marker back into a clickable source in the UI. A break at any point in the tools, prompt, stream parser, database or renderer fails without an error. |
| [chat-persistence](components/chat-persistence.md) | How a conversation is stored and read back: the session, the message tree and its branches, model steps, tool calls, surfaced documents, feedback, sharing, incognito, history search and retention. Each answer row is reserved before the run, filled while it runs, and finalized in one transaction; every reload, share link and later turn reads that record. |
| [agent-runtime](components/agent-runtime.md) | A Python engine that runs chat, deep research, research and coding agents through model steps and parallel tools, with child agents, cancellation, compaction and suspension. This document is the one record of which chat adapters implement its interfaces, and which runtime features no product path reaches. |
| [llm-providers](components/llm-providers.md) | Admins configure LLM providers, their models and the default model for each task, and a factory resolves the model for every call. The factory builds `LitellmLLM`, the wrapper that owns streaming, retries and managed-key cost tracking. |
| [chat-preferences](components/chat-preferences.md) | Per-user preferences that reach the prompt (profile, language, memories) and prompt shortcuts, plus the workspace `Settings` store that the admin Chat Preferences page and other admin pages edit. |
| [projects](components/projects.md) | A named set of files and instructions that one user keeps across chat sessions. This component owns the project row, its links to files and sessions, and the per-turn choice between inline files and retrieval. |
| [file-store-and-user-files](components/file-store-and-user-files.md) | Files that users give Onyx directly (chat attachments, project files and agent files) and the files that tools generate. This component owns the blob store, the `UserFile` lifecycle from upload to deletion, text extraction and token counts, user-file indexing, and the route that serves a file back. |
| [chat-frontend](components/chat-frontend.md) | The web chat at `/app`: it sends a turn, reads the packet stream, keeps each session's message tree in a client store, and renders timeline steps and the answer. It also drives the actions that change the saved conversation, and owns the development proxy that forwards `/api` to the backend. |

## Search and retrieval

Turn a query into ranked context that the user may see.

| Component | Summary |
|---|---|
| [internal-search](components/internal-search.md) | The `internal_search` tool: it expands a query into parallel lanes over the document index and federated sources, fuses them, and has an LLM select and expand the best sections. The `/search` API and the EE Search page reuse it. |
| [document-index](components/document-index.md) | The OpenSearch index that stores document chunks with their vectors and metadata, with the query and filter builder, the metadata sync that pushes ACL and document-set changes into chunks, and the reindex that moves search to a new embedding model. |
| [access-control](components/access-control.md) | Who can retrieve which document. Indexing stores an access control list (ACL) on every chunk, and every query passes through one filter built from the acting user's ACL. |
| [web-search](components/web-search.md) | Search of the public internet and fetch of web pages: the `web_search` and `open_url` tools, the admin page that picks the active providers, and the `/web-search` API for callers outside the chat loop. |
| [federated-search](components/federated-search.md) | Search of a source at query time through its own API, with no indexing. `FederatedConnectorSource` lists the sources, and their results join the same ranked set, document cards and citations as indexed documents. |

## Ingestion

Get company data into the index, keep it fresh, and copy its permissions.

| Component | Summary |
|---|---|
| [connectors](components/connectors.md) | The boundary between Onyx and an outside source: the connector interfaces, the registry and factory, typed configs with the edit plan, and source gateways. A connector yields documents, hierarchy nodes and failures; it never chunks, embeds or writes to the index. |
| [connector-capability-checks](components/connector-capability-checks.md) | Named probes that test whether a credential and a connector config can sign in, list the scope, read content and sync permissions. They run on the unsaved form, at creation, on an edit, on a schedule and on demand, and their results can block Create and hold the first index attempt. |
| [cc-pairs-and-creds](components/cc-pairs-and-creds.md) | The connector config, the credential that holds the secret for one source account, and the connector-credential pair (cc-pair) that joins them and is the unit that indexing, access, scheduling and deletion act on. |
| [indexing-pipeline](components/indexing-pipeline.md) | Turns the documents a connector yields into chunks in the search index, in two Celery phases: docfetching runs the connector and stages batches, and docprocessing chunks, embeds and writes each batch. It owns the `IndexAttempt` record that the admin sees, and the chunking of spreadsheets. |
| [permission-sync](components/permission-sync.md) | Copies permissions from a source system into Postgres: doc sync records who can see each document, and group sync records who is in each external group. [[access-control]] turns the data into query-time ACLs, and the metadata sync in [[document-index]] pushes it into the index. |
| [confluence](components/connectors/confluence.md) | The Confluence connector indexes pages and attachments from Confluence Cloud or Data Center, with page and attachment URLs as document ids. A mode sets its scope, and its client renews a rotating credential under the credential provider's lock. |
| [google-drive](components/connectors/google-drive.md) | The Google Drive connector indexes files from shared drives, My Drives, folders and files shared with a user, as one OAuth user or as a service account that impersonates every user in the domain. Its checkpoint is a staged crawl, not a cursor. |
| [microsoft-graph](components/connectors/microsoft-graph.md) | The shared Microsoft layer gives every Microsoft connector app-only Entra auth, national-cloud hosts, Graph error mapping, drive delta paging and SharePoint REST permission reads. This document also covers the SharePoint and OneDrive connectors; Outlook and Teams have their own documents. |
| [outlook](components/connectors/outlook.md) | The Outlook connector indexes mail as one document per thread, shared across the mailboxes that hold it, plus optional calendar events. Each mailbox decides its part of a thread from its own copy, so mailbox walks share no state. |
| [slack](components/connectors/slack.md) | The Slack connector indexes channel threads as one document per thread. It reads Slack only through its gateway, the one module that imports `slack_sdk` in the connector and its EE permission sync. |
| [teams](components/connectors/teams.md) | The Microsoft Teams connector indexes channel threads, channel files, meeting transcripts and the days of meeting chats from one app credential. It reads channel messages through the Graph export API when the tenant allows it, and walks channel by channel when it does not. |

## Configuration surfaces

What an admin or a user configures to change how chat behaves.

| Component | Summary |
|---|---|
| [agents-personas](components/agents-personas.md) | Agents (`Persona` in the database and most Python code): the configurable row of instructions, tools, knowledge and model that a user talks to. This component owns the row, who can see and change it, sharing, pins and the default assistant. |
| [plugins](components/plugins.md) | The admin and member surfaces for MCP servers and OpenAPI actions, the Plugins pages that also host Craft apps, and the rules that decide whether a plugin is on in Default Chat. |
| [mcp-and-custom-tools](components/mcp-and-custom-tools.md) | Onyx as an MCP client to servers that an admin connects, and the OpenAPI custom tools that an admin describes with a schema: how they become `Tool` rows, how their credentials are stored and resolved, and how one call succeeds or fails. |
| [standard-answers](components/standard-answers.md) | Admin-written canned answers that the Slack bot posts in place of an LLM answer when a message matches a keyword set or a regex. The match runs before retrieval, so the answer text never passes a document ACL. |
| [voice](components/voice.md) | Speech-to-text (STT) and text-to-speech (TTS) for chat, through providers that an admin configures and activates for each direction. The Zoom provider row also holds the credential for Zoom Decisions. |

## Platform

Services that every feature depends on.

| Component | Summary |
|---|---|
| [auth-and-identity](components/auth-and-identity.md) | Who is making a request. It covers every way a person or a machine proves identity, how a session lives and ends, the OAuth provider and outgoing action OAuth, the user lifecycle, and the SSRF guard for outbound fetches. |
| [authorization](components/authorization.md) | What an identity may do. Group grants and group-manager scope decide which routes a user, service account or token can reach and which resources a route lets them change. |
| [multi-tenancy](components/multi-tenancy.md) | How one deployment serves many isolated workspaces. A tenant is a Postgres schema on a physical shard, and a context variable that must hold the right tenant in every session, thread and task that a request or job creates. |
| [background-jobs](components/background-jobs.md) | The shared asynchronous machinery: worker apps, queues, the beat schedule, tenant context on each task, fences and task conventions. It also owns the two flows that remove documents, pruning and connector deletion. |
| [editions-and-gating](components/editions-and-gating.md) | How a call reaches Community (CE) or Enterprise (EE) code, and how a paid feature is locked below its tier. Every standard image loads the EE code, so the license decides what is unlocked, not the build. |
| [billing](components/billing.md) | The commercial layer: Stripe checkout and portal through the Onyx control plane, the signed self-hosted license, seats, the tier each deployment resolves to, and what happens when a subscription lapses. |
| [observability](components/observability.md) | How operators and admins watch Onyx: Prometheus metrics, LLM tracing to Braintrust or Langfuse, the per-user usage and cost ledger, the audit log stream, the support log export and query history. |
| [fleet-telemetry](components/fleet-telemetry.md) | The outbound health, usage and indexing events that each Onyx deployment sends to the Onyx fleet service. It must never slow or fail the work it observes. |
| [hooks](components/hooks.md) | Hook extensions: a customer HTTPS endpoint that Onyx calls and waits on at a fixed point in chat or indexing, to rewrite or reject a query, rewrite or drop a document, or receive each indexed document. The hook decides what enters the pipeline, so a failure must follow its fail strategy exactly. |
| [rate-and-usage-limits](components/rate-and-usage-limits.md) | Separate mechanisms that throttle or cap usage: token and cost budgets, tenant usage limits, the API-call cap, HTTP rate limits, and signup and invite limits. Each has its own storage, scope and enforcement point. |
| [notifications](components/notifications.md) | The in-product messages Onyx shows a user: the bell feed, the banner queue for loud messages, release notes and the admin site-wide banner. Every producer writes one table through two idempotent insert helpers. |
| [whitelabelling-and-theme](components/whitelabelling-and-theme.md) | The admin-set branding layer: application name, logo, greeting, header, footer and login text, first-visit notice, consent screen and help link, stored as one key-value blob per tenant plus two logo files. The read routes need no login, because the login page needs the branding before any user is known. |

## Integrations and clients

Ways to reach Onyx other than the web chat.

| Component | Summary |
|---|---|
| [slack-bot](components/slack-bot.md) | A separate listener process answers questions in Slack: it turns each Slack event into an in-process chat turn and posts the answer to the thread. It skips the HTTP chat route, so each check on that route must be repeated here or accepted as absent. |
| [discord-bot](components/discord-bot.md) | A `discord.py` client that answers messages in registered Discord servers by calling the public chat API over HTTP. It uses one service API key per tenant, so every Discord member in a tenant is answered as the same Onyx identity. |
| [onyx-api](components/onyx-api.md) | The HTTP surface that external software programs against: the ordinary routes that carry the `public` tag, their reference-docs pipeline, and the router that pushes documents into the index without a connector. |
| [mcp-server](components/mcp-server.md) | Onyx as an MCP server: an external MCP client such as Claude Code or Codex searches the company knowledge base with the user's own access. The server is a separate process with no database that forwards every call, with the caller's token, to the API server. |
| [mobile-app](components/mobile-app.md) | The React Native and Expo client, and the bearer-token auth gateway it signs in through. It is a second client of the chat backend, built apart from the web chat frontend, with its own copy of the stream parser and packet enum. |
| [desktop-widget-extensions](components/desktop-widget-extensions.md) | Thin clients that bring Onyx outside the main web app: a Tauri desktop shell, a chat widget that a site embeds, and a Chrome extension. None runs product logic, and only the widget calls the chat endpoints itself. |
| [llm-gateway](components/llm-gateway.md) | Onyx as an OpenAI- and Anthropic-compatible LLM API for external tools and Craft sandboxes, authorized by a scoped Personal Access Token (PAT). Onyx picks the provider, supplies the real credential, and meters every call. |

## Craft

The product that runs a coding agent in a sandbox for each user.

| Component | Summary |
|---|---|
| [craft-admin](components/craft-admin.md) | The admin controls for Onyx Craft: who may use it, which apps and MCP servers a sandbox may act through with which action policies, and the organization instructions and default model that each session starts with. |
| [craft-sessions](components/craft-sessions.md) | A Craft session is one conversation with a coding agent that runs in the user's sandbox; this component owns the session row, the interactive turn (start, run, stop, finish), attachments, output cards, the user library and the session's model. |
| [craft-frontend](components/craft-frontend.md) | The browser side of Craft: the session store, the app-wide stream owner, turn settlement, the prompt queue, and the output panel with its file viewers. Its rules decide which of several async sources may write one session's state. |
| [craft-streaming](components/craft-streaming.md) | How a Craft turn's output gets from the agent in the sandbox to the browser: the `opencode serve` client, the per-pod event bus, the translation to Craft events, which events are saved, and the attach-only SSE endpoint, which has no replay buffer. |
| [craft-sandboxes](components/craft-sandboxes.md) | The sandbox a user's Craft sessions run in, on Kubernetes or Docker: provisioning, the sidecar daemon, snapshot and restore, idle sleep, resource cleanup, and the network lockdown that sends all traffic to the egress proxy. |
| [craft-webapp-proxy](components/craft-webapp-proxy.md) | Lets a user see, inside Onyx, the web app that their Craft session builds and the static HTML files it writes; it is the trust boundary between code that an LLM wrote and the viewer's browser. |
| [craft-external-apps](components/craft-external-apps.md) | The egress proxy that every outbound request from a Craft sandbox goes through, and the external apps it gates. A request to a connected app or MCP server gets an action policy check, an approval wait for Ask actions, and the real credential; other public traffic goes out with no policy check. |
| [craft-scheduled-tasks](components/craft-scheduled-tasks.md) | A user schedules a Craft prompt to run on a timer. Each fire creates a new headless Craft session in the owner's sandbox, runs one agent turn with nobody watching, and records a run row the user can open later. |
| [skills](components/skills.md) | Agent Skills for Craft: instruction bundles that Onyx renders for each user and pushes into that user's Craft sandbox, where the coding agent reads them. This component owns skill sharing, installation policy, per-user rendering and the hashed push; skills do not reach the chat product. |

---

## Common tasks

For new work that needs recipes from more than one document. This table is the
only record of the order of recipes for a task. Follow the links in order. A
step in parentheses applies only in the case it names. Also read the matching
section of [CROSS-CUTTING.md](CROSS-CUTTING.md).

| Task | Recipes, in order |
|---|---|
| A new packet type | [[streaming-protocol#packet-type]] → [[chat-frontend#packet-type-renderer]] → [[chat-frontend#mock-stream-test]] → [[mobile-app#add-tool-renderer]] → [[desktop-widget-extensions#widget-packet-type]] → [[streaming-protocol#cli-packet-type]] → [[chat-persistence#replay-new-tool]] |
| A new built-in tool | [[tools-framework#built-in-tool]] → [[citations#citeable-tool]] (if it cites) → [[context-assembly#tool-guidance-section]] → the packet type row (if it reuses the search packets, only the search branch of [[chat-persistence#replay-new-tool]]) → [[tools-framework#gate-a-tool]] |
| A tool that generates files | [[tools-framework#built-in-tool]] → [[file-store-and-user-files#add-generated-file-writer]] |
| A new feature on the agent runtime | [[agent-runtime#new-feature]] → [[observability#add-llm-call-site]] → [[rate-and-usage-limits#add-llm-entry-point]] (if a user starts the run) → [[agent-runtime#wire-module]] (if it uses suspension or checkpoint transfer) |
| A new in-process chat caller (a bot or an integration) | [[core-chat-loop#in-process-caller]] → [[multi-tenancy#new-thread]] (if it starts a thread) → [CROSS-CUTTING.md: Who is the acting user](CROSS-CUTTING.md#who-is-the-acting-user) |
| A field saved with each turn | [[core-chat-loop#turn-state-field]] → [[chat-persistence#chat-message-column]] |
| A user preference that reaches the prompt | [[chat-preferences#new-user-setting]] → [[context-assembly#new-context-element-decisions]] (where the section goes) |
| An agent field | [[agents-personas#add-agent-field]] → [[internal-search#new-filter-field]] (if search reads it) → [[context-assembly]] (if the prompt reads it) |
| A file type that users can upload | [[file-store-and-user-files#add-file-type]] → [[indexing-pipeline#tabular-chunking-change]] (only for a tabular type) |
| A new API middleware | [[streaming-protocol#api-middleware]] → [[multi-tenancy#tenant-from-auth-only]] (if it reads or sets the tenant) |
| A new connector | [[connectors#new-connector]] → [[connectors#source-gateway]] → [[connector-capability-checks#named-checks]] |
| A new connector with permission sync | the connector row → [[permission-sync#doc-sync-source]] → [[connector-capability-checks#perm-sync-checks]] → [[permission-sync#group-sync-source]] (if the source has groups) |
| A field on indexed chunks | [[indexing-pipeline#chunk-field]] → [[document-index#chunk-field]] |
| A search filter | [[internal-search#new-filter-field]] → [[document-index#add-filter]] |
| A federated search source | [[federated-search#new-federated-source]] → [[internal-search#new-lane]] (if it runs as its own lane) |
| An LLM step at index time | [[llm-providers#new-task-designation]] → [[document-index#contextual-rag-validator]] (if an index setting turns it on) → [[indexing-pipeline#llm-enrichment-step]] → [[indexing-pipeline#docprocessing-long-step]] → [[observability#add-llm-call-site]] |
| A new LLM call site in a request | [[llm-providers#new-call-site]] → [[observability#add-llm-call-site]] → [[rate-and-usage-limits#add-llm-entry-point]] → [CROSS-CUTTING.md: A new LLM call site](CROSS-CUTTING.md#a-new-llm-call-site) |
| A new gateway endpoint or dialect | [[llm-gateway#new-endpoint]] → [[llm-gateway#new-caller-type]] (if a new caller type) → [[observability#add-llm-call-site]] |
| A voice provider | [[voice#new-voice-provider]] → [[observability#add-llm-call-site]] (STT and TTS flow tags) |
| A public API route | [[onyx-api#add-public-route]] → [[rate-and-usage-limits#add-llm-entry-point]] (if it drives LLM work) → [[onyx-api#check-generated-reference]] |
| A PAT scope for a new API route | [CROSS-CUTTING.md: A new route](CROSS-CUTTING.md#a-new-route) → [[onyx-api#add-public-route]] (if it is published) → [[authorization#new-pat-scope]] → [[mcp-server#oauth-token-route-allowlist]] (if an MCP tool calls the route) |
| A new admin page | [CROSS-CUTTING.md: A new route](CROSS-CUTTING.md#a-new-route) → [[authorization#scoped-manager-route]] (if managers use it) → add a [PATHS.md](PATHS.md) row for the page |
| A resource that can be shared with a group | [[access-control#group-shareable-resource]] → [[authorization#scoped-manager-route]] |
| A new ACL source | [[access-control#new-acl-source]] → [[permission-sync#group-sync-source]] |
| A new credential or token type | [[auth-and-identity#new-credential-type]] → [[multi-tenancy#tenant-from-auth-only]] → [[authorization#new-pat-scope]] (if it carries scopes) |
| A new periodic task | [[background-jobs#periodic-task]] → [[multi-tenancy#new-celery-task]] → [[background-jobs#add-queue]] (only for a new queue) |
| A paid feature | [[editions-and-gating#add-paid-route]] or [[editions-and-gating#add-paid-field]] → [[billing#add-paid-feature-to-downgrade]] (if its rows or values keep taking effect after a downgrade) |
| A paid workspace setting | [[chat-preferences#new-workspace-option]] → [[context-assembly#workspace-setting-in-prompt]] (if the prompt reads it) → [[editions-and-gating#add-paid-field]] → [[billing#add-paid-feature-to-downgrade]] |
| A branding field | [[whitelabelling-and-theme#add-branding-field]] → [[editions-and-gating#add-paid-field]] (tier check) |
| An MCP authentication type | [[mcp-and-custom-tools#mcp-auth-type]] → [[plugins#mcp-auth-type-ui]] |
| A new Craft packet or opencode event type | [[craft-streaming#new-opencode-event-type]] → [[craft-streaming#new-packet-type]] → [[craft-frontend#new-session-state]] |
| A new Craft output file type or viewer | [[craft-webapp-proxy#new-static-preview-type]] → [[craft-frontend#new-viewer]] |
| A new writer into a Craft session workspace | [[craft-sessions#new-workspace-writer]] → [[craft-sandboxes#cleanup-proof-not-cache]] |
| A built-in Craft app | [[craft-external-apps#built-in-app]] → [[skills#add-built-in-skill]] → [[craft-admin#external-app-admin-field]] (if the app needs one) |
| A new host for an existing built-in Craft app | [[craft-external-apps#new-host-for-built-in-app]] → [[skills#add-built-in-skill]] (update the skill files) |
| A Craft workspace setting | [[craft-admin#workspace-setting]] → [[editions-and-gating#add-paid-field]] (if paid) → [[craft-sandboxes]] (if the sandbox reads it) |
| A Celery task for Craft scheduled tasks | [[background-jobs#periodic-task]] → [[craft-scheduled-tasks#celery-task]] |
| A skill mutation or sharing route | [[skills#add-skill-mutation-route]] → [[craft-sandboxes]] (the push transport) |
| Investigate a leak: a user sees a document they should not, or cannot see one they should | [[access-control#investigate-acl-mismatch]] → [[permission-sync#investigate-leak]] → [[document-index#investigate-stale-acl]] |
| Investigate a private document in a Slack or Discord answer | [[slack-bot#investigate-private-doc-in-answer]] → [[discord-bot#no-member-identity]] → [[federated-search#investigate-slack-leak]] |
| Investigate "search did not find my document" | [[internal-search#document-not-found]] → [[access-control#investigate-acl-mismatch]] → [[indexing-pipeline#investigate-stuck-attempt]] |
| Investigate indexing that is stuck or slow | [[indexing-pipeline#investigate-stuck-attempt]] → [[background-jobs#investigate-task-not-running]] |
| Investigate documents that a prune removed, or did not remove | [[background-jobs#investigate-prune]] → [[connectors#investigate-prune-deletions]] → [[google-drive#investigate-refused-prune]] (Google Drive) |
| Investigate a connector stuck in `DELETING` | [[cc-pairs-and-creds#stuck-deleting]] → [[background-jobs#investigate-deletion]] → [[background-jobs#investigate-stuck-fence]] |
| Investigate missing or wrong citations | [[citations#investigate-missing-citations]] → [[chat-persistence#investigate-reload-differs]] |
| Investigate a missing answer block, a stop that does nothing, or a broken resume | [[core-chat-loop#investigate-stuck-turn]] → [[streaming-protocol#investigate-missing-block]] → [[mobile-app#investigate-empty-step]] (mobile) |
| Investigate "the assistant forgot a file" or ignored a project file | [[context-assembly#investigate-forgotten-file]] → [[projects#investigate-project-file-answer]] → [[file-store-and-user-files#investigate-file-processing]] |
| Investigate a 404 on a file or an agent file | [[file-store-and-user-files#investigate-file-404]] → [[agents-personas#investigate-agent-visibility]] |
| Investigate a tool that the model never calls, or that is missing in chat | [[tools-framework#investigate-tool-not-called]] → the tool's own recipe: [[code-execution#investigate-python-not-run]], [[image-generation#investigate-image-tool-missing]], [[web-search#no-web-search]], or [[plugins#investigate-missing-default-chat-tool]] then [[mcp-and-custom-tools#investigate-missing-mcp-tools]] |
| Investigate a limit that did not apply, or usage that is missing | [[rate-and-usage-limits#investigate-limit-not-applied]] → [[observability#investigate-missing-usage]] |
| Investigate a locked (access-restricted) deployment | [[billing#investigate-access-restricted]] → [[billing#load-license-locally]] → [[editions-and-gating#find-loaded-edition]] |
| Investigate a chat bot that does not answer | [[slack-bot#investigate-no-answer]] or [[discord-bot#investigate-no-reply]] → [[standard-answers#investigate-not-fired]] |
| Investigate a Craft turn that hangs or shows no output | [[craft-sessions#investigate-stuck-turn]] → [[craft-streaming#investigate-stream]] → [[craft-frontend#reproduce-queue-bug]] |
| Investigate a Craft web app preview that stays offline | [[craft-webapp-proxy#investigate-preview-offline]] → [[craft-sandboxes#investigate-craft-fails-to-start]] |
| Investigate a blocked or failed Craft app call | [[craft-external-apps#investigate-app-call-failed]] → [[craft-sandboxes#investigate-craft-fails-to-start]] (if no proxy line appears) |
| Investigate a Craft scheduled task that did not run | [[craft-scheduled-tasks#investigate-task-did-not-run]] → [[craft-admin#investigate-craft-off]] (if the run is skipped because Craft is off for the owner) |
| Test paid features locally | [[billing#load-license-locally]] → [[editions-and-gating#test-ce-or-ee]] |
